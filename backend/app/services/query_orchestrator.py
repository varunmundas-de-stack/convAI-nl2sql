"""
Query Orchestrator

PIPELINE STEPS:
  0  load_qco        — reset clarification state, load previous QCO
  1  extract_intent  — LLM call to extract intent from query
  2  drill_merge     — detect drill-down mutation, merge intent with QCO
  3  validate_intent — normalize + validate intent against catalog
  4  build_query     — determine period strategy, build Cube query
  5  execute_query   — HTTP call(s) to Cube (primary + optional secondary)
  6  gen_insights    — insight engine → refiner → visual spec
  7  resolve_qco     — persist QCO snapshot for next query
  8  complete        — mark success, cleanup clarification tool state

run_pipeline(ctx, start_step=N) chains steps N..8.
  Fresh query   → start_step=0
  Clarification resume → start_step=3  (skip load/extract/merge, re-enter at validate)
  Retry         → start_step=0  (same as fresh, different query)
"""

import logging
import time
import json
import uuid
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer

from app.services.intent_extractor import (
    extract_intent, ExtractionError, LLMCallError, LLMTimeoutError,
)
from app.services.intent_errors import IntentValidationError, IntentIncompleteError
from app.services.intent_validator import validate_intent
from app.services.intent_normalizer import normalize_intent, patch_trend_intent
from app.services.intent_merger import merge_intent
from app.services.drill_detector import detect_drill, apply_drill_mutation
from app.services.cube_query_builder import (
    build_cube_query, build_comparison_query, build_total_query, CubeQueryBuildError,
)
from app.services.cube_client import CubeClient, CubeHTTPError, CubeQueryExecutionError
from app.services.period_planner import determine_strategy, QueryStrategy, transform_intent_for_strategy
from app.services.catalog_manager import CatalogManager
from app.services.insight_engine import generate_insights, InsightEngineError
from app.services.insight_refiner import refine_insights
from app.services.visual_spec_generator import generate_visual_spec
from app.services.qco_resolver import resolve_qco
from app.pipeline.state_store import save_state, load_state, delete_state, PipelineStateNotFound
from app.pipeline.pipeline_state import PipelineState as PersistedState
from app.pipeline.qco_store import save_qco, load_qco
from app.models.qco import QueryContextObject


logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


# =============================================================================
# STAGE CONSTANTS
# =============================================================================

class Stage:
    RECEIVED                = "received"
    QCO_LOADED              = "qco_loaded"
    INTENT_EXTRACTED        = "intent_extracted"
    INTENT_MERGED           = "intent_merged"
    CLARIFICATION_REQUESTED = "clarification_requested"
    INTENT_VALIDATED        = "intent_validated"
    CUBE_QUERY_BUILT        = "cube_query_built"
    CUBE_EXECUTED           = "cube_executed"
    INSIGHTS_GENERATED      = "insights_generated"
    INSIGHTS_REFINED        = "insights_refined"
    VISUAL_SPEC_GENERATED   = "visual_spec_generated"
    QCO_RESOLVED            = "qco_resolved"
    COMPLETED               = "completed"


# =============================================================================
# PIPELINE CONTEXT
# =============================================================================

@dataclass
class OrchestratorError:
    stage: str
    error_type: str
    message: str = ""
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details or {},
        }


@dataclass
class PipelineContext:
    """Single object threaded through every pipeline step."""

    # inputs
    query: str
    session_id: Optional[str] = None
    original_query: Optional[str] = None
    skip_reset_overrides: bool = False
    resolved_clarifications: Optional[Dict[str, Any]] = None

    # pipeline tracking
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stage: str = Stage.RECEIVED
    success: bool = False
    start_time: float = field(default_factory=time.monotonic)
    duration_ms: int = 0

    # step outputs
    previous_qco: Optional[QueryContextObject] = None
    raw_intent: Optional[Dict[str, Any]] = None
    merged_intent: Optional[Dict[str, Any]] = None
    validated_intent: Optional[Any] = None
    original_intent: Optional[Any] = None
    cube_query: Optional[Dict[str, Any]] = None
    period_strategy: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    comparison_data: Optional[List[Dict[str, Any]]] = None
    insights: Optional[Any] = None
    refined_insights: Optional[Any] = None
    visual_spec: Optional[Any] = None

    # clarification
    clarification: Optional[bool] = None
    missing_fields: Optional[List[str]] = None
    clarification_message: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    clarification_answers: Optional[Dict[str, Any]] = None

    # error
    error: Optional[OrchestratorError] = None

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.start_time) * 1000)

    def fail(self, stage: str, error_type: str, message: str, details=None) -> "PipelineContext":
        """Stamp a hard error onto the context. The runner stops after this."""
        self.error = OrchestratorError(stage=stage, error_type=error_type, message=message, details=details)
        self.duration_ms = self.elapsed_ms()
        return self

    def to_dict(self) -> Dict[str, Any]:
        def _dump(obj):
            return obj.model_dump() if obj is not None and hasattr(obj, "model_dump") else obj

        effective = self.query
        if self.clarification_answers and self.original_query:
            parts = [f"{k}: {v}" for k, v in self.clarification_answers.items() if isinstance(v, str) and v.strip()]
            if parts:
                effective = f"{self.original_query} ({', '.join(parts)})"

        return {
            "query": self.query,
            "original_query": self.original_query,
            "effective_query": effective,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "success": self.success,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "has_previous_context": self.previous_qco is not None,
            "raw_intent": self.raw_intent,
            "merged_intent": self.merged_intent,
            "validated_intent": _dump(self.validated_intent),
            "original_intent": _dump(self.original_intent),
            "cube_query": self.cube_query,
            "period_strategy": self.period_strategy,
            "data": self.data,
            "comparison_data": self.comparison_data,
            "insights": _dump(self.insights),
            "refined_insights": _dump(self.refined_insights),
            "visual_spec": _dump(self.visual_spec),
            "clarification": self.clarification,
            "missing_fields": self.missing_fields,
            "clarification_message": self.clarification_message,
            "allowed_values": self.allowed_values,
            "clarification_answers": self.clarification_answers,
            "error": self.error.to_dict() if self.error else None,
        }


# =============================================================================
# SPAN HELPER
# =============================================================================

def _span_set(span, **kwargs) -> None:
    """
    Write key/value pairs onto an OTel span in one call.

    Key convention: first underscore → dot  (input_query → "input.query").
    Values are auto-serialized:
      dict/list → json.dumps (≤ 2000 chars)
      str       → truncated to 1000 chars
      None      → ""
      other     → str()
    """
    for raw_key, value in kwargs.items():
        key = raw_key.replace("_", ".", 1)
        if isinstance(value, (dict, list)):
            span.set_attribute(key, json.dumps(value, default=str)[:2000])
        elif isinstance(value, str):
            span.set_attribute(key, value[:1000])
        elif value is None:
            span.set_attribute(key, "")
        else:
            span.set_attribute(key, str(value))


def _span_error(span, err: OrchestratorError) -> None:
    span.set_status(Status(StatusCode.ERROR, err.message))
    _span_set(span, error_type=err.error_type, error_stage=err.stage, error_message=err.message)


# =============================================================================
# STEP DECORATOR
# =============================================================================

def pipeline_step(span_name: str):
    """
    Wraps a step function with an OTel span.
    The step receives (ctx, span) so it can call _span_set directly.
    Signals pipeline halt by raising _Halt (clarification) or setting ctx.error (hard fail).
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(ctx: PipelineContext) -> PipelineContext:
            with tracer.start_as_current_span(span_name) as span:
                fn(ctx, span)
                return ctx
        return wrapper
    return decorator


class _Halt(Exception):
    """Raised inside a step to stop the pipeline without setting ctx.error."""


# =============================================================================
# CATALOG SINGLETON
# =============================================================================

_catalog: Optional[CatalogManager] = None

def _get_catalog() -> CatalogManager:
    global _catalog
    if _catalog is None:
        catalog_path = Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"
        _catalog = CatalogManager(str(catalog_path))
    return _catalog


# =============================================================================
# PIPELINE STEPS
# =============================================================================

@pipeline_step("qco.load")
def step_load_qco(ctx: PipelineContext, span) -> None:
    """Step 0 — reset clarification tool, load QCO."""

    # Reset clarification tool for brand-new sessions
    if not ctx.skip_reset_overrides and not ctx.session_id:
        try:
            from app.dspy_pipeline.clarification_tool import clarification_tool as _ct
            _ct.reset_for_new_request()
        except Exception as e:
            logger.warning(f"Failed to reset clarification tool: {e}")

    _span_set(span, input_session_id=ctx.session_id or "")

    if ctx.session_id:
        try:
            qco = load_qco(ctx.session_id)
            if qco:
                ctx.previous_qco = qco
                ctx.stage = Stage.QCO_LOADED
                _span_set(span, output_found=True, output_metric=qco.metric or "", output_sales_scope=qco.sales_scope or "")
                logger.info(f"Loaded QCO for session {ctx.session_id}: metric={qco.metric}")
            else:
                _span_set(span, output_found=False)
                logger.info(f"No previous QCO for session {ctx.session_id} (first query)")
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.warning(f"Failed to load QCO for session {ctx.session_id}: {e}")


@pipeline_step("intent.extract")
def step_extract_intent(ctx: PipelineContext, span) -> None:
    """Step 1 — LLM call to extract intent from the query."""
    _span_set(span,
        input_query=ctx.query[:500],
        input_has_previous_qco=ctx.previous_qco is not None,
        input_previous_qco_metric=getattr(ctx.previous_qco, "metric", "") or "",
        input_previous_qco_scope=getattr(ctx.previous_qco, "sales_scope", "") or "",
    )
    try:
        logger.info("Step 1: Extracting intent...")
        raw_intent = extract_intent(
            ctx.query,
            previous_qco=ctx.previous_qco,
            skip_reset_overrides=ctx.skip_reset_overrides,
            overrides=ctx.resolved_clarifications,
        )
        ctx.raw_intent = raw_intent
        ctx.stage = Stage.INTENT_EXTRACTED
        _span_set(span,
            output_intent_type=str(raw_intent.get("intent_type", "")),
            output_metric=str(raw_intent.get("metric", "")),
            output_value=raw_intent,
        )
        logger.info(f"Intent extracted: {raw_intent}")

    except IntentIncompleteError as e:
        logger.warning(f"Clarification needed at extraction: {e}")
        ctx.clarification = True
        ctx.missing_fields = e.missing_fields
        ctx.clarification_message = e.clarification_message
        ctx.allowed_values = e.allowed_values
        ctx.raw_intent = e.partial_intent or {}
        ctx.stage = Stage.CLARIFICATION_REQUESTED
        ctx.duration_ms = ctx.elapsed_ms()
        _span_set(span, output_clarification_requested=True, output_missing_fields=str(e.missing_fields))
        raise _Halt

    except LLMTimeoutError as e:
        logger.error(f"LLM timeout: {e}")
        span.record_exception(e)
        ctx.fail(Stage.RECEIVED, "LLMTimeoutError", str(e))
        _span_error(span, ctx.error)

    except LLMCallError as e:
        logger.error(f"LLM call error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.RECEIVED, "LLMCallError", str(e))
        _span_error(span, ctx.error)

    except ExtractionError as e:
        logger.error(f"Extraction error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.RECEIVED, "ExtractionError", str(e))
        _span_error(span, ctx.error)


@pipeline_step("intent.drill_merge")
def step_drill_merge(ctx: PipelineContext, span) -> None:
    """Step 2 — detect drill-down mutation, then merge intent with previous QCO."""

    # Drill detection
    if ctx.previous_qco and ctx.raw_intent:
        drill_result = detect_drill(ctx.raw_intent, ctx.previous_qco)
        _span_set(span, output_drill_case=drill_result.case)
        if drill_result.case != "none":
            ctx.raw_intent = apply_drill_mutation(ctx.raw_intent, ctx.previous_qco, drill_result)
            _span_set(span,
                output_drill_prev=drill_result.prev_dimension or "",
                output_drill_next=drill_result.next_dimension or "",
            )
            logger.info(f"Drill [{drill_result.case}]: {drill_result.prev_dimension} → {drill_result.next_dimension}")

    # Merge
    if ctx.previous_qco and ctx.raw_intent:
        ctx.merged_intent = merge_intent(ctx.raw_intent, ctx.previous_qco)
        ctx.stage = Stage.INTENT_MERGED
        _span_set(span, output_merged_with_qco=True, output_value=ctx.merged_intent)
        logger.info("Intent merged with previous QCO")
    else:
        ctx.merged_intent = ctx.raw_intent
        _span_set(span, output_merged_with_qco=False)


@pipeline_step("intent.validate")
def step_validate_intent(ctx: PipelineContext, span) -> None:
    """Step 3 — normalize + validate intent against catalog."""
    intent_to_log = ctx.merged_intent or ctx.raw_intent or {}
    _span_set(span,
        input_intent_source="merged" if ctx.merged_intent else "raw",
        input_value=intent_to_log,
    )
    try:
        logger.info("Step 3: Validating intent...")
        normalized = normalize_intent(ctx.merged_intent or ctx.raw_intent)
        normalized = patch_trend_intent(normalized, ctx.query)
        validated = validate_intent(normalized, _get_catalog(), original_query=ctx.query)
        ctx.validated_intent = validated
        ctx.stage = Stage.INTENT_VALIDATED
        _span_set(span,
            output_intent_type=str(getattr(validated, "intent_type", "")),
            output_metrics=str(getattr(validated, "metrics", ""))[:500],
            output_dimensions=str(getattr(validated, "group_by", ""))[:500],
            output_value=getattr(validated, "model_dump", lambda: str(validated))(),
        )
        logger.info(f"Intent validated: {validated}")

    except IntentIncompleteError as e:
        logger.warning(f"Incomplete intent: {e}")
        ctx.clarification = True
        ctx.missing_fields = e.missing_fields
        ctx.clarification_message = e.clarification_message
        ctx.allowed_values = e.allowed_values
        ctx.stage = Stage.CLARIFICATION_REQUESTED
        ctx.duration_ms = ctx.elapsed_ms()
        _span_set(span, output_clarification_requested=True, output_missing_fields=str(e.missing_fields))
        raise _Halt

    except IntentValidationError as e:
        logger.error(f"Intent validation failed: {e}")
        span.record_exception(e)
        ctx.fail(Stage.INTENT_EXTRACTED, "IntentValidationError", str(e))
        _span_error(span, ctx.error)


@pipeline_step("cube.build_query")
def step_build_query(ctx: PipelineContext, span) -> None:
    """Step 4 — determine period strategy, transform intent, build Cube query."""
    try:
        logger.info("Step 4: Building Cube query...")

        try:
            strategy = determine_strategy(ctx.validated_intent)
            ctx.period_strategy = strategy.value
        except Exception as e:
            logger.warning(f"Period strategy determination failed (non-fatal): {e}")
            strategy = QueryStrategy.SINGLE_QUERY
            ctx.period_strategy = strategy.value

        _span_set(span, output_strategy=ctx.period_strategy)

        ctx.original_intent = ctx.validated_intent
        transformed = transform_intent_for_strategy(ctx.validated_intent, strategy)
        ctx.validated_intent = transformed

        ctx.cube_query = build_cube_query(transformed)
        ctx.stage = Stage.CUBE_QUERY_BUILT
        _span_set(span,
            input_value=getattr(transformed, "model_dump", lambda: str(transformed))(),
            output_measures=str(ctx.cube_query.get("measures", [])),
            output_dimensions=str(ctx.cube_query.get("dimensions", [])),
            output_filters=str(ctx.cube_query.get("filters", []))[:500],
            output_value=ctx.cube_query,
        )
        logger.info(f"Cube query built: {ctx.cube_query}")

    except CubeQueryBuildError as e:
        logger.error(f"Cube query build error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.INTENT_VALIDATED, "CubeQueryBuildError", str(e))
        _span_error(span, ctx.error)


@pipeline_step("cube.execute")
def step_execute_query(ctx: PipelineContext, span) -> None:
    """Step 5 — execute primary Cube query, plus comparison/total if strategy requires."""
    strategy = ctx.period_strategy or QueryStrategy.SINGLE_QUERY.value
    _span_set(span, input_strategy=strategy, input_cube_query=str(ctx.cube_query)[:1000])

    try:
        client = CubeClient()
        logger.info(f"Step 5: Executing Cube query (strategy={strategy})...")

        # Primary query
        with tracer.start_as_current_span("cube.primary_query") as primary_span:
            try:
                client.get_sql(ctx.cube_query)
                ctx.data = client.load(ctx.cube_query).data
                _span_set(primary_span,
                    output_row_count=len(ctx.data),
                    output_sample_row=str(ctx.data[0])[:500] if ctx.data else "",
                )
                logger.info(f"Primary query: {len(ctx.data)} rows")
            except CubeHTTPError as e:
                primary_span.set_status(Status(StatusCode.ERROR, str(e)))
                ctx.fail(Stage.CUBE_QUERY_BUILT, "CubeHTTPError", "Cube query failed",
                         details=e.to_dict() if hasattr(e, "to_dict") else None)
                _span_error(span, ctx.error)
                return  # stop this step; runner will halt on ctx.error

        _span_set(span, output_primary_row_count=len(ctx.data))

        # Secondary query (strategy-dependent, non-fatal if it fails)
        if strategy == QueryStrategy.DUAL_QUERY.value:
            with tracer.start_as_current_span("cube.comparison_query") as s:
                try:
                    q = build_comparison_query(ctx.validated_intent)
                    client.get_sql(q)
                    ctx.comparison_data = client.load(q).data
                    _span_set(s, output_row_count=len(ctx.comparison_data))
                    logger.info(f"Comparison query: {len(ctx.comparison_data)} rows")
                except Exception as e:
                    s.set_status(Status(StatusCode.ERROR, str(e)))
                    s.record_exception(e)
                    logger.warning(f"Comparison query failed (non-fatal): {e}")

        elif strategy == QueryStrategy.CONTRIBUTION.value:
            with tracer.start_as_current_span("cube.total_query") as s:
                try:
                    q = build_total_query(ctx.validated_intent)
                    client.get_sql(q)
                    ctx.comparison_data = client.load(q).data
                    _span_set(s, output_row_count=len(ctx.comparison_data))
                    logger.info(f"Total query: {len(ctx.comparison_data)} rows")
                except Exception as e:
                    s.set_status(Status(StatusCode.ERROR, str(e)))
                    s.record_exception(e)
                    logger.warning(f"Total query failed (non-fatal): {e}")

        ctx.stage = Stage.CUBE_EXECUTED

    except CubeQueryExecutionError as e:
        logger.error(f"Cube execution error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.CUBE_QUERY_BUILT, "CubeQueryExecutionError", str(e))
        _span_error(span, ctx.error)


@pipeline_step("insights")
def step_gen_insights(ctx: PipelineContext, span) -> None:
    """Step 6 — insight engine → refiner → visual spec."""
    _span_set(span,
        input_data_row_count=len(ctx.data or []),
        input_has_comparison_data=ctx.comparison_data is not None,
        input_strategy=ctx.period_strategy or "",
    )
    try:
        # 6a — Insight engine
        with tracer.start_as_current_span("insights.engine") as s:
            logger.info("Step 6a: Generating insights...")
            result = generate_insights(
                data=ctx.data or [],
                intent=ctx.validated_intent,
                previous_qco=ctx.previous_qco,
                strategy=ctx.period_strategy,
                comparison_data=ctx.comparison_data,
            )
            ctx.insights = result
            ctx.stage = Stage.INSIGHTS_GENERATED
            try:
                _span_set(s,
                    output_insight_count=len(result.insights),
                    output_total_formatted=result.total_formatted or "",
                    output_intent_type=result.intent_type or "",
                    output_primary_label=getattr(result.primary_insight, "label", ""),
                    output_value=getattr(result, "model_dump", lambda: str(result))(),
                )
            except Exception as _e:
                logger.debug(f"Non-fatal span log error: {_e}")
            logger.info(f"Insights generated: {len(result.insights)}")

        # 6b — Refiner (non-fatal)
        with tracer.start_as_current_span("insights.refine") as s:
            logger.info("Step 6b: Refining insights...")
            try:
                refined = refine_insights(
                    insight_result=result,
                    data=ctx.data or [],
                    query=ctx.query,
                    previous_qco=ctx.previous_qco,
                )
                ctx.refined_insights = refined
                ctx.stage = Stage.INSIGHTS_REFINED
                try:
                    _span_set(s,
                        output_refined_count=len(refined.insights),
                        output_executive_summary=refined.executive_summary or "",
                        output_value=getattr(refined, "model_dump", lambda: str(refined))(),
                    )
                except Exception as _e:
                    logger.debug(f"Non-fatal span log error: {_e}")
                logger.info(f"Insights refined: {len(refined.insights)}")
            except Exception as e:
                s.set_status(Status(StatusCode.ERROR, str(e)))
                s.record_exception(e)
                logger.warning(f"Insight refinement failed (non-fatal): {e}")
                ctx.refined_insights = None

        # 6c — Visual spec
        with tracer.start_as_current_span("visual_spec") as s:
            logger.info("Step 6c: Generating visual spec...")
            spec = generate_visual_spec(
                data=ctx.data or [],
                insights=ctx.refined_insights or result,
                chart_type_hint=None,
                query=ctx.query,
                comparison_data=ctx.comparison_data,
                strategy=ctx.period_strategy,
                intent=ctx.validated_intent,
            )
            ctx.visual_spec = spec
            ctx.stage = Stage.VISUAL_SPEC_GENERATED
            _span_set(s,
                output_chart_type=spec.chart_type or "",
                output_annotations_count=len(spec.annotations),
                output_markers_count=len(spec.markers),
                output_title=getattr(spec, "title", "") or "",
                output_value=getattr(spec, "model_dump", lambda: str(spec))(),
            )
            logger.info(f"Visual spec generated: chart_type={spec.chart_type}")

    except InsightEngineError as e:
        logger.error(f"Insight engine error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.CUBE_EXECUTED, e.__class__.__name__, str(e))
        _span_error(span, ctx.error)

    except Exception as e:
        span.set_status(Status(StatusCode.ERROR, str(e)))
        span.record_exception(e)
        logger.warning(f"Insight/spec generation failed (non-fatal): {e}")


@pipeline_step("qco.resolve")
def step_resolve_qco(ctx: PipelineContext, span) -> None:
    """Step 7 — persist QCO snapshot for the next query in this session."""
    if not ctx.session_id or not ctx.validated_intent:
        return

    _span_set(span, input_session_id=ctx.session_id)
    try:
        qco = resolve_qco(ctx.original_intent or ctx.validated_intent, ctx.query)
        save_qco(ctx.session_id, qco)
        ctx.stage = Stage.QCO_RESOLVED
        _span_set(span, output_resolved=True, output_qco_metric=qco.metric or "")
        logger.info(f"QCO resolved and saved for session {ctx.session_id}")
    except Exception as e:
        span.set_status(Status(StatusCode.ERROR, str(e)))
        span.record_exception(e)
        _span_set(span, output_resolved=False)
        logger.warning(f"Failed to resolve/save QCO: {e}")


@pipeline_step("pipeline.complete")
def step_complete(ctx: PipelineContext, span) -> None:
    """Step 8 — mark success, cleanup clarification tool state."""
    try:
        from app.dspy_pipeline.clarification_tool import clarification_tool as _ct
        cleaned = _ct.cleanup_request_state(request_id_prefix=ctx.request_id, max_entries=100)
        if cleaned > 0:
            logger.debug(f"Cleaned up {cleaned} clarification entries for {ctx.request_id}")
    except Exception as e:
        logger.warning(f"Failed to cleanup clarification tool: {e}")

    ctx.success = True
    ctx.stage = Stage.COMPLETED
    ctx.duration_ms = ctx.elapsed_ms()
    logger.info(f"Pipeline completed in {ctx.duration_ms}ms")
    _span_set(span, output_duration_ms=ctx.duration_ms)


# =============================================================================
# STEP REGISTRY  +  RUNNER
# =============================================================================

PIPELINE_STEPS: List[Callable[[PipelineContext], PipelineContext]] = [
    step_load_qco,        # 0
    step_extract_intent,  # 1
    step_drill_merge,     # 2
    step_validate_intent, # 3
    step_build_query,     # 4
    step_execute_query,   # 5
    step_gen_insights,    # 6
    step_resolve_qco,     # 7
    step_complete,        # 8
]


def run_pipeline(ctx: PipelineContext, start_step: int = 0) -> PipelineContext:
    """
    Chain PIPELINE_STEPS[start_step:] against ctx.

    Stops early on:
      - ctx.error set            → hard failure
      - _Halt raised             → soft stop (clarification requested)
    """
    with tracer.start_as_current_span("pipeline") as root_span:
        _span_set(root_span,
            input_query=ctx.query[:500],
            input_session_id=ctx.session_id or "",
            input_start_step=start_step,
        )
        logger.info(f"Pipeline started: '{ctx.query[:100]}' (session={ctx.session_id}, request={ctx.request_id}, start_step={start_step})")

        for step_fn in PIPELINE_STEPS[start_step:]:
            try:
                step_fn(ctx)
            except _Halt:
                _span_set(root_span,
                    output_clarification_requested=True,
                    output_missing_fields=str(ctx.missing_fields or []),
                    output_clarification_message=ctx.clarification_message or "",
                )
                return ctx

            if ctx.error:
                _span_error(root_span, ctx.error)
                return ctx

        _span_set(root_span,
            output_success=ctx.success,
            output_stage=ctx.stage,
            output_duration_ms=ctx.duration_ms,
            output_row_count=len(ctx.data or []),
            output_chart_type=getattr(ctx.visual_spec, "chart_type", "") or "",
            output_primary_insight=getattr(getattr(ctx.insights, "primary_insight", None), "label", ""),
            output_value=ctx.to_dict(),
        )
        return ctx


# =============================================================================
# PUBLIC API
# =============================================================================

def execute_query(
    query: str,
    session_id: Optional[str] = None,
    _skip_reset_overrides: bool = False,
    _resolved_clarifications: Optional[Dict[str, Any]] = None,
) -> PipelineContext:
    """Run the full pipeline from step 0."""
    ctx = PipelineContext(
        query=query,
        session_id=session_id,
        original_query=query,
        skip_reset_overrides=_skip_reset_overrides,
        resolved_clarifications=_resolved_clarifications,
    )
    ctx = run_pipeline(ctx, start_step=0)

    if ctx.stage == Stage.CLARIFICATION_REQUESTED:
        save_state(PersistedState(
            request_id=ctx.request_id,
            original_query=query,
            intent=ctx.raw_intent or {},
            missing_fields=ctx.missing_fields or [],
            session_id=session_id,
            resolved_clarifications=_resolved_clarifications or {},
        ))
        logger.info(f"Clarification state saved: {ctx.request_id}")

    return ctx


def execute_query_dict(query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience wrapper — returns a JSON-serializable dict."""
    return execute_query(query, session_id=session_id).to_dict()


def resume_query(
    request_id: str,
    clarification_answers: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resume a pipeline paused at CLARIFICATION_REQUESTED.

    Loads saved state, patches intent with user answers,
    re-enters at step 3 (validate_intent).
    """
    with tracer.start_as_current_span("pipeline.resume") as span:
        _span_set(span,
            input_request_id=request_id,
            input_session_id=session_id or "",
            input_clarification_keys=str(list(clarification_answers.keys())),
            input_value=clarification_answers,
        )

        try:
            state = load_state(request_id)
        except PipelineStateNotFound:
            logger.warning(f"Pipeline state not found: request_id={request_id}")
            return {
                "success": False,
                "stage": "invalid_request",
                "request_id": request_id,
                "session_id": session_id,
                "error": {
                    "error_type": "PipelineStateNotFound",
                    "message": "Invalid or expired request_id. Please start a new query.",
                    "details": {"request_id": request_id, "hint": "State expires after 1 hour or on server restart"},
                },
            }

        resolved_session_id = session_id or state.session_id

        # DSPy clarification — resolved overrides, full re-run from step 0
        if state.intent.get("dspy_clarification_request_id"):
            logger.info(f"Handling DSPy clarification for {state.intent.get('dspy_clarification_request_id')}")
            try:
                resolved = getattr(state, "resolved_clarifications", {}) or {}
                for f, answer in clarification_answers.items():
                    if f not in state.missing_fields:
                        continue
                    resolved[f] = [str(a).strip() for a in answer] if isinstance(answer, list) else str(answer).strip()
                logger.info(f"DSPy resolved overrides: {resolved}")
                try:
                    delete_state(state.request_id)
                except Exception:
                    pass
                result = execute_query(
                    query=state.original_query,
                    session_id=resolved_session_id,
                    _skip_reset_overrides=True,
                    _resolved_clarifications=resolved,
                ).to_dict()
                _span_set(span, output_success=result.get("success", False), output_stage=result.get("stage", ""))
                return result
            except Exception as e:
                logger.error(f"DSPy clarification resume error: {e}")
                # fall through to standard path

        # Standard clarification — patch intent, re-enter at step 3
        previous_qco = None
        if resolved_session_id:
            try:
                previous_qco = load_qco(resolved_session_id)
            except Exception as e:
                logger.warning(f"Could not load QCO on resume: {e}")

        patched_intent = {
            **state.intent,
            **{k: v for k, v in clarification_answers.items() if k in state.missing_fields},
        }
        # BUG-02 FIX: merge so QCO context (filters, group_by, etc.) is inherited
        merged_intent = merge_intent(patched_intent, previous_qco) if previous_qco else patched_intent
        logger.info(f"Resume merged intent: {merged_intent}")

        try:
            from app.rlhf.prompt_manager import get_ab_version
            prompt_version, ab_group = get_ab_version(resolved_session_id or request_id)
        except Exception as e:
            logger.warning(f"RLHF version resolution failed (non-fatal): {e}")
            prompt_version, ab_group = "v1", None

        ctx = PipelineContext(
            query=state.original_query,
            session_id=resolved_session_id,
            original_query=state.original_query,
            request_id=request_id,          # preserve original so callers can correlate
            prompt_version=prompt_version,
            ab_group=ab_group,
            previous_qco=previous_qco,
            raw_intent=patched_intent,
            merged_intent=merged_intent,
            clarification_answers=clarification_answers,
            stage=Stage.INTENT_EXTRACTED,
        )

        # BUG-01 FIX: do NOT delete state here — only after full success
        ctx = run_pipeline(ctx, start_step=3)

        if ctx.stage == Stage.CLARIFICATION_REQUESTED:
            save_state(PersistedState(
                request_id=request_id,
                original_query=state.original_query,
                intent=merged_intent,
                missing_fields=ctx.missing_fields or [],
                session_id=resolved_session_id,
                resolved_clarifications=getattr(state, "resolved_clarifications", {}) or {},
            ))

        if ctx.success:
            delete_state(request_id)

        result = ctx.to_dict()
        _span_set(span,
            output_success=result.get("success", False),
            output_stage=result.get("stage", ""),
            output_row_count=len(result.get("data") or []),
            output_value=result,
        )
        if not result.get("success") and result.get("error"):
            err = result["error"]
            span.set_status(Status(StatusCode.ERROR, err.get("message", "")))
            _span_set(span, error_type=err.get("error_type", ""), error_message=err.get("message", ""))

        return result


def execute_retry_query(
    original_request_id: str,
    modified_query: str,
    session_id: str,
    original_query: str,
) -> PipelineContext:
    """
    Log the retry for RLHF analysis, then run the full pipeline on the modified query.

    Args:
        original_request_id: Request ID of the query being retried.
        modified_query:      The user's revised query text.
        session_id:          Session ID for context continuity.
        original_query:      Original query kept for comparison/logging.
    """
    request_id = f"retry_{uuid.uuid4().hex[:12]}"
    logger.info(f"Starting retry: retry_id={request_id}, original_id={original_request_id}, session={session_id}")

    with tracer.start_as_current_span("pipeline.retry") as span:
        _span_set(span,
            pipeline_type="retry",
            input_original_request_id=original_request_id,
            input_retry_request_id=request_id,
            input_modified_query=modified_query[:500],
            input_session_id=session_id,
            input_original_query=original_query[:500],
        )
        try:
            from app.rlhf.feedback_service import log_retry
            retry_log_id = log_retry(
                original_request_id=original_request_id,
                retry_request_id=request_id,
                original_query=original_query,
                modified_query=modified_query,
                session_id=session_id,
            )
            _span_set(span, retry_log_id=retry_log_id)
            logger.info(f"Retry logged: {retry_log_id}")
        except Exception as e:
            logger.warning(f"Failed to log retry (non-fatal): {e}")

        ctx = execute_query(query=modified_query, session_id=session_id)
        ctx.request_id = request_id
        ctx.original_query = original_query

        _span_set(span,
            output_success=ctx.success,
            output_duration_ms=ctx.duration_ms,
            output_row_count=len(ctx.data or []),
            output_chart_type=getattr(ctx.visual_spec, "chart_type", "") or "",
        )
        if ctx.error:
            _span_error(span, ctx.error)
        else:
            logger.info(f"Retry completed in {ctx.duration_ms}ms")

        return ctx