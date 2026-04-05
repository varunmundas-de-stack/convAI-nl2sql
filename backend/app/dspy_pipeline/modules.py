"""
DSPy Modules for Intent Extraction Pipeline.

Each module wraps a single Signature and contains:
  - Typed predict call via dspy.Predict
  - Lightweight post-validation using Pydantic schemas
  - No catalog logic here — that belongs in schemas.py constants

Following RULE M1: One Module class per Signature
Following RULE M2: forward() returns the typed Pydantic output, not the raw dspy Prediction
Following RULE M3: Validation/correction belongs in the module, not the caller
Following RULE M4: Modules are stateless; all context is passed as arguments
"""

import json
import logging
import uuid
import time
from datetime import date
from typing import Optional

import dspy
from opentelemetry.trace import Status, StatusCode

from app.utils.tracer import get_tracer

from .schemas import (
    # Decomposition output
    DecomposedQuery,
    # Intermediate outputs
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    MetricsResult,
    DimensionsResult,
    ComparisonConfig,
    RankingConfig,
    PostProcessingResult,
    Intent,
    CATALOG_METRICS,
    METRICS_CATALOG,
    TIME_WINDOWS,
    TimeSpec,
    MetricSpec,
    get_valid_dimensions_for_scope,

)
from .clarification_tool import (
    ClarificationRequired,
    MultipleClarificationsRequired,
    Clarification,
    build_scope_clarification,
    build_metric_clarification,
    build_individual_metric_clarifications,
    build_dimension_clarification,
    build_individual_dimension_clarifications,
    build_time_clarification,
)
from .signatures import (
    DecomposeQuery,
    ClassifyQuery,
    ResolveScope,
    ResolveTime,
    ExtractMetrics,
    ResolveDimensions,
    ResolvePostProcessing,
)
from app.dspy_pipeline.schemas import FilterCondition
logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


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


# =============================================================================
# QUERY DECOMPOSER — Before Agent Pipeline
# =============================================================================

class QueryDecomposerModule(dspy.Module):
    """
    Decomposes compound queries into independent analytical sub-queries.

    This is the first agent in the pipeline and determines if a query
    contains multiple independent intents that should be processed separately.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(DecomposeQuery)

    def forward(self, query: str, previous_context=None) -> DecomposedQuery:
        with tracer.start_as_current_span("dspy.decomposer") as span:
            _span_set(span, input_query=query, input_has_context=previous_context is not None)

            try:
                start_time = time.monotonic()

                context_str = ""
                if previous_context:
                    # Handle different context types
                    try:
                        if hasattr(previous_context, 'to_decomposer_context'):
                            # It's a QCO object
                            context_str = previous_context.to_decomposer_context()
                        elif isinstance(previous_context, dict):
                            # It's a dict, convert to QCO
                            from app.models.qco import QueryContextObject
                            qco = QueryContextObject(**previous_context)
                            context_str = qco.to_decomposer_context()
                        else:
                            # It's already a string
                            context_str = str(previous_context)
                    except Exception:
                        # Fallback to JSON if conversion fails
                        context_str = json.dumps(previous_context) if isinstance(previous_context, dict) else str(previous_context)

                prediction = self.predict(query=query, session_context=context_str)
                result = prediction.decomposed_query

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_is_compound=result.is_compound,
                    output_subquery_count=len(result.sub_queries),
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy Decomposer] Completed in {duration_ms}ms | compound={result.is_compound} | subqueries={len(result.sub_queries)}")
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Decomposer] Error: {e}")
                raise


# =============================================================================
# AGENT 1 — ClassifierModule
# =============================================================================
class ClassifierModule(dspy.Module):
    """
    Classifies each term in a natural-language query and determines query intent.

    Inputs  : raw query string
    Outputs : ClassifiedQuery (typed Pydantic model)
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ClassifyQuery)

    def forward(self, query: str, session_context=None) -> ClassifiedQuery:
        """
        Run ClassifyQuery signature and return a validated ClassifiedQuery.

        Args:
            query: Raw natural-language query from the user.
            session_context: Previous context from session for better intent determination.

        Returns:
            ClassifiedQuery with classified_terms, query_intent,
            filter_hints, and explicit_scope populated.
        """
        with tracer.start_as_current_span("dspy.classifier") as span:
            _span_set(span, input_query=query, input_has_context=session_context is not None)

            try:
                start_time = time.monotonic()

                # Handle different context types - convert to string for LLM
                context_str = ""
                if session_context:
                    if hasattr(session_context, 'to_prompt_context'):
                        # It's a QCO object
                        context_str = session_context.to_prompt_context()
                    elif isinstance(session_context, dict):
                        context_str = json.dumps(session_context)
                    else:
                        # Already a string
                        context_str = str(session_context)

                prediction = self.predict(query=query, session_context=context_str)
                classified: ClassifiedQuery = prediction.classified_query

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_intent=classified.query_intent,
                    output_terms_count=len(classified.classified_terms or []),
                    output_explicit_scope=classified.explicit_scope or "",
                    output_duration_ms=duration_ms,
                    output_value=classified.model_dump() if hasattr(classified, "model_dump") else str(classified)
                )

                logger.debug(f"[DSPy Classifier] Completed in {duration_ms}ms | intent={classified.query_intent} | terms={len(classified.classified_terms or [])}")

                # No alias resolution — downstream modules handle ambiguity
                return classified

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Classifier] Error: {e}")
                raise

# =============================================================================
# AGENT 2 — ScopeModule
# =============================================================================

class ScopeModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveScope)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        overrides: Optional[dict] = None,
    ) -> ScopeResult:
        with tracer.start_as_current_span("dspy.scope") as span:
            scope_terms = [t for t in classified_query.classified_terms if t.role == "SCOPE"]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_scope_terms=len(scope_terms),
                input_explicit_scope=classified_query.explicit_scope or "",
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override
                # -------------------------
                if "sales_scope" in overrides:
                    result = ScopeResult(sales_scope=overrides["sales_scope"])
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_scope=result.sales_scope,
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Scope] Override used: {result.sales_scope}")
                    return result

                # -------------------------
                # 2. LLM extraction
                # -------------------------
                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role == "SCOPE"]
                prediction = self.predict(classified_terms=json.dumps(relevant_terms))
                result: ScopeResult = prediction.scope_result

                # -------------------------
                # 3. Ambiguity / Missing handling
                # -------------------------

                # If LLM couldn't determine scope → clarify
                has_scope_term = any(
                    t.role == "SCOPE"
                    for t in classified_query.classified_terms
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)

                if not has_scope_term:
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="scope"
                    )
                    logger.debug(f"[DSPy Scope] Clarification required - no scope terms")
                    raise ClarificationRequired(build_scope_clarification())

                _span_set(span,
                    output_source="llm_extraction",
                    output_scope=result.sales_scope,
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy Scope] Completed in {duration_ms}ms | scope={result.sales_scope}")
                return result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Scope] Error: {e}")
                raise

# =============================================================================
# AGENT 3 — TimeModule
# =============================================================================

class TimeModule(dspy.Module):
    """
    Determines time window and granularity from the classified query.

    Inputs  : ClassifiedQuery, current_date, query_intent, previous_context
    Outputs : TimeResult
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveTime)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        current_date: Optional[date] = None,
        previous_context=None,
        overrides: Optional[dict] = None,
    ) -> TimeResult:
        with tracer.start_as_current_span("dspy.time") as span:
            time_terms = [t for t in classified_query.classified_terms if t.role in ("TIME_RANGE", "TIME_GRANULARITY")]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_time_terms=len(time_terms),
                input_has_context=previous_context is not None,
                input_has_overrides=bool(overrides),
                input_current_date=current_date.isoformat() if hasattr(current_date, 'isoformat') else str(current_date or "")
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override
                # -------------------------
                if "time" in overrides:
                    result = TimeResult(time_window=overrides["time"])
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_time_window=result.time_window or "",
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Time] Override used: {result.time_window}")
                    return result

                intent = classified_query.query_intent
                resolved_date = current_date or date.today()

                if isinstance(resolved_date, str):
                    resolved_date = date.fromisoformat(resolved_date)

                # Handle different context types - convert to string for LLM
                context_str = ""
                if previous_context:
                    if hasattr(previous_context, 'to_prompt_context'):
                        # It's a QCO object
                        context_str = previous_context.to_prompt_context()
                    elif isinstance(previous_context, dict):
                        context_str = json.dumps(previous_context)
                    else:
                        # Already a string
                        context_str = str(previous_context)

                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("TIME_RANGE", "TIME_GRANULARITY")]
                prediction = self.predict(
                    classified_terms=json.dumps(relevant_terms),
                    current_date=resolved_date.isoformat(),
                    query_intent=intent,
                    previous_context=context_str,
                )

                result: TimeResult = prediction.time_result

                # -------------------------
                # 2. Rule 5 — STRUCTURAL
                # -------------------------
                if intent in ["STRUCTURAL", "MINIMAL_MESSAGE"]:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="time",
                        clarification_reason="structural_intent"
                    )
                    logger.debug(f"[DSPy Time] Clarification required for structural intent")
                    raise ClarificationRequired(build_time_clarification(ambiguous_expression="time period", candidate_windows=sorted(TIME_WINDOWS)))

                # -------------------------
                # 3. Detect explicit time
                # -------------------------
                has_time_terms = any(
                    t.role == "TIME_RANGE"
                    for t in classified_query.classified_terms
                )

                has_window = bool(result.time_window or result.start_date or result.end_date)

                # -------------------------
                # 4. Rule 1 — Explicit time
                # -------------------------
                if has_time_terms:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="explicit_terms",
                        output_time_window=result.time_window or "",
                        output_start_date=result.start_date or "",
                        output_end_date=result.end_date or "",
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] Explicit terms - completed in {duration_ms}ms")
                    return result  # trust extraction fully

                # -------------------------
                # 5. Rule 2 — TREND
                # -------------------------
                if intent == "TREND":
                    if not has_window:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="time",
                            clarification_reason="trend_missing_window"
                        )
                        logger.debug(f"[DSPy Time] Clarification required for TREND without window")
                        raise ClarificationRequired(
                            build_time_clarification(
                                ambiguous_expression="time period",
                                candidate_windows=sorted(TIME_WINDOWS)
                            )
                        )

                    # default granularity
                    if not result.granularity:
                        result.granularity = "week"

                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="trend_logic",
                        output_time_window=result.time_window or "",
                        output_granularity=result.granularity,
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] TREND logic - completed in {duration_ms}ms")
                    return result

                # -------------------------
                # 6. Rule 3 — COMPARISON
                # -------------------------
                if intent == "COMPARISON":
                    # If explicit TIME_RANGE terms exist (feb, last quarter, etc.)
                    # trust the LLM extraction fully — dates or window are the comparison period
                    if has_time_terms:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="comparison_explicit",
                            output_time_window=result.time_window or "",
                            output_duration_ms=duration_ms,
                            output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                        )
                        logger.debug(f"[DSPy Time] COMPARISON explicit - completed in {duration_ms}ms")
                        return result

                    # No explicit time terms — fall back to previous context
                    if not has_window and previous_context:
                        if hasattr(previous_context, 'time_range') and previous_context.time_range:
                            context_result = TimeResult(
                                start_date=previous_context.time_range.start_date,
                                end_date=previous_context.time_range.end_date,
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="context_qco",
                                output_start_date=context_result.start_date,
                                output_end_date=context_result.end_date,
                                output_duration_ms=duration_ms
                            )
                            logger.debug(f"[DSPy Time] COMPARISON from QCO context - completed in {duration_ms}ms")
                            return context_result
                        elif isinstance(previous_context, dict):
                            prev_time = previous_context.get("time")
                            if prev_time:
                                context_result = TimeResult(**prev_time)
                                duration_ms = int((time.monotonic() - start_time) * 1000)
                                _span_set(span,
                                    output_source="context_dict",
                                    output_duration_ms=duration_ms,
                                    output_value=context_result.model_dump() if hasattr(context_result, "model_dump") else str(context_result)
                                )
                                logger.debug(f"[DSPy Time] COMPARISON from dict context - completed in {duration_ms}ms")
                                return context_result

                    # Has window or nothing available — return as-is
                    # PostProcessingResolver will map time_window → comparison_window
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="comparison_fallback",
                        output_time_window=result.time_window or "",
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] COMPARISON fallback - completed in {duration_ms}ms")
                    return result

                # -------------------------
                # 7. Rule 4 — KPI / DISTRIBUTION / RANKING
                # -------------------------
                if intent in ["KPI", "DISTRIBUTION", "RANKING"]:

                    # explicit handled already
                    # fallback to context
                    if not has_window and previous_context:
                        # Handle QCO object for time context
                        prev_time = None
                        if hasattr(previous_context, 'time_range') and previous_context.time_range:
                            # Convert QCO time_range to TimeResult format
                            prev_time = {
                                "start_date": previous_context.time_range.start_date,
                                "end_date": previous_context.time_range.end_date
                            }
                        elif isinstance(previous_context, dict):
                            prev_time = previous_context.get("time")

                        if prev_time:
                            context_result = TimeResult(**prev_time)
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="kpi_context",
                                output_duration_ms=duration_ms,
                                output_value=context_result.model_dump() if hasattr(context_result, "model_dump") else str(context_result)
                            )
                            logger.debug(f"[DSPy Time] KPI/DIST/RANK from context - completed in {duration_ms}ms")
                            return context_result

                    # still nothing → ask
                    if not has_window:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="time",
                            clarification_reason="kpi_missing_window"
                        )
                        logger.debug(f"[DSPy Time] Clarification required for KPI/DIST/RANK without window")
                        raise ClarificationRequired(
                            build_time_clarification(
                                ambiguous_expression="time period",
                                candidate_windows=sorted(TIME_WINDOWS)
                            )
                        )

                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="kpi_window",
                        output_time_window=result.time_window or "",
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] KPI/DIST/RANK with window - completed in {duration_ms}ms")
                    return result

                # -------------------------
                # Default fallback
                # -------------------------
                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_source="default_fallback",
                    output_time_window=result.time_window or "",
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )
                logger.debug(f"[DSPy Time] Default fallback - completed in {duration_ms}ms")
                return result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Time] Error: {e}")
                raise
# =============================================================================
# AGENT 4 — MetricsModule
# =============================================================================

class MetricsModule(dspy.Module):
    """
    Extracts canonical metric names and their aggregations from the classified query.

    Design:
        - LLM returns candidate metrics from catalog
        - Module enforces:
            1 candidate → accept
            >1 candidates → clarification
            0 candidates → clarification
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ExtractMetrics)

        # Build once from schema
        self._catalog_str = json.dumps(METRICS_CATALOG)

        # Aggregation lookup
        self._agg_map = {
            m["name"]: m["aggregation"]
            for m in METRICS_CATALOG
        }

    def forward(
        self,
        classified_query: ClassifiedQuery,
        sales_scope: str,
        overrides: Optional[dict] = None,
    ) -> MetricsResult:
        with tracer.start_as_current_span("dspy.metrics") as span:
            metric_terms = [t for t in classified_query.classified_terms if t.role == "METRIC"]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_metric_terms=len(metric_terms),
                input_sales_scope=sales_scope,
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override (resume flow)
                # -------------------------
                if "metrics" in overrides:
                    metrics_list = overrides["metrics"]
                    if isinstance(metrics_list, str):
                        metrics_list = [metrics_list]

                    result = MetricsResult(
                        metrics=[
                            MetricSpec(
                                name=m,
                                aggregation=self._agg_map.get(m, "sum")
                            )
                            for m in metrics_list
                        ],
                        aggregations=[
                            self._agg_map.get(m, "sum")
                            for m in metrics_list
                        ],
                    )

                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_metrics=str([m.name for m in result.metrics]),
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Metrics] Override used: {[m.name for m in result.metrics]}")
                    return result

                # -------------------------
                # 2. LLM extraction
                # -------------------------
                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role == "METRIC"]
                prediction = self.predict(
                    original_query=classified_query.original_query,
                    classified_terms=json.dumps(relevant_terms),
                    sales_scope=sales_scope,
                    available_metrics=self._catalog_str,
                )

                result: MetricsResult = prediction.metrics_result

                # -------------------------
                # 3. Validate against catalog
                # -------------------------
                valid_metrics = [
                    m for m in result.metrics
                    if m.name in CATALOG_METRICS
                ]

                # -------------------------
                # 4. Ambiguity handling
                # -------------------------

                metric_terms = [
                    t.term for t in classified_query.classified_terms
                    if t.role == "METRIC"
                ]

                # ❗ No valid metric → ask user
                if len(valid_metrics) == 0:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="metrics",
                        clarification_reason="no_valid_metrics"
                    )
                    logger.debug(f"[DSPy Metrics] Clarification required - no valid metrics")
                    raise ClarificationRequired(
                        build_metric_clarification(
                            ambiguous_terms=metric_terms or ["metric"],
                            candidate_metrics=sorted(CATALOG_METRICS),
                        )
                    )

                # ❗ Multiple candidates or multiple terms → sequential clarification
                if len(valid_metrics) > 1 or len(metric_terms) > 1:

                    # For multiple terms, use term-specific field names to track individual resolutions
                    if len(metric_terms) > 1:
                        resolved_metrics = []
                        pending_terms = []

                        # Check which terms have been resolved using term-specific override keys
                        for term in metric_terms:
                            term_field_key = f"metric_term_{term}"
                            if term_field_key in overrides:
                                resolved_metric = overrides[term_field_key]
                                if resolved_metric in CATALOG_METRICS:
                                    resolved_metrics.append(MetricSpec(
                                        name=resolved_metric,
                                        aggregation=self._agg_map.get(resolved_metric, "sum")
                                    ))
                            else:
                                pending_terms.append(term)

                        if pending_terms:
                            # Loop through pending terms — auto-resolve singletons, ask only when truly ambiguous
                            for first_pending in list(pending_terms):
                                term_field_key = f"metric_term_{first_pending}"

                                # Create context message about progress
                                total_terms = len(metric_terms)
                                resolved_count = total_terms - len(pending_terms)
                                context = f"Resolving metric term {resolved_count + 1} of {total_terms}: '{first_pending}'"

                                # Get term-specific candidates by running LLM scoped to just this term
                                term_classified = [t.model_dump() for t in classified_query.classified_terms if t.role == "METRIC" and t.term == first_pending]
                                term_prediction = self.predict(
                                    original_query=classified_query.original_query,
                                    classified_terms=json.dumps(term_classified),
                                    sales_scope=sales_scope,
                                    available_metrics=self._catalog_str,
                                )
                                term_candidates = [
                                    m.name for m in (term_prediction.metrics_result.metrics or [])
                                    if m.name in CATALOG_METRICS
                                ]

                                if len(term_candidates) == 1:
                                    # Exactly one match — auto-resolve, no question needed
                                    resolved_metrics.append(MetricSpec(
                                        name=term_candidates[0],
                                        aggregation=self._agg_map.get(term_candidates[0], "sum")
                                    ))
                                    pending_terms.remove(first_pending)
                                else:
                                    # 0 or 2+ candidates — ask the user
                                    duration_ms = int((time.monotonic() - start_time) * 1000)
                                    _span_set(span,
                                        output_source="clarification_required",
                                        output_duration_ms=duration_ms,
                                        clarification_field=term_field_key,
                                        clarification_reason="multiple_term_ambiguity",
                                        clarifying_term=first_pending
                                    )
                                    term_options = sorted(term_candidates) if term_candidates else sorted(CATALOG_METRICS)
                                    logger.debug(f"[DSPy Metrics] Clarification required for term: {first_pending}")
                                    raise ClarificationRequired(Clarification(
                                        request_id=str(uuid.uuid4()),
                                        field=term_field_key,
                                        question=f"Which metric do you mean by '{first_pending}'?",
                                        options=term_options,
                                        multi_select=False,
                                        context=context,
                                        clarifying_term=first_pending,
                                    ))

                            # All pending terms auto-resolved — return immediately
                            final_result = MetricsResult(
                                metrics=resolved_metrics,
                                aggregations=[self._agg_map.get(m.name, "sum") for m in resolved_metrics],
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="auto_resolved",
                                output_metrics=str([m.name for m in resolved_metrics]),
                                output_duration_ms=duration_ms,
                                output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                            )
                            logger.debug(f"[DSPy Metrics] Auto-resolved multiple terms - completed in {duration_ms}ms")
                            return final_result

                        else:
                            # All terms resolved
                            if resolved_metrics:
                                final_result = MetricsResult(
                                    metrics=resolved_metrics,
                                    aggregations=[self._agg_map.get(m.name, "sum") for m in resolved_metrics],
                                )
                                duration_ms = int((time.monotonic() - start_time) * 1000)
                                _span_set(span,
                                    output_source="resolved_terms",
                                    output_metrics=str([m.name for m in resolved_metrics]),
                                    output_duration_ms=duration_ms,
                                    output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                                )
                                logger.debug(f"[DSPy Metrics] All terms resolved - completed in {duration_ms}ms")
                                return final_result
                            else:
                                # Fallback if resolution failed
                                duration_ms = int((time.monotonic() - start_time) * 1000)
                                _span_set(span,
                                    output_source="clarification_required",
                                    output_duration_ms=duration_ms,
                                    clarification_field="metrics",
                                    clarification_reason="resolution_failed"
                                )
                                logger.debug(f"[DSPy Metrics] Resolution fallback clarification required")
                                raise ClarificationRequired(
                                    build_metric_clarification(
                                        ambiguous_terms=metric_terms,
                                        candidate_metrics=sorted(CATALOG_METRICS),
                                    )
                                )

                    else:
                        # Single term, multiple candidates → standard clarification
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="metrics",
                            clarification_reason="single_term_multiple_candidates"
                        )
                        logger.debug(f"[DSPy Metrics] Single term with multiple candidates - clarification required")
                        raise ClarificationRequired(
                            build_metric_clarification(
                                ambiguous_terms=metric_terms,
                                candidate_metrics=[m.name for m in valid_metrics],
                            )
                        )

                # -------------------------
                # 5. Single metric → accept
                # -------------------------
                metric = valid_metrics[0]

                final_result = MetricsResult(
                    metrics=[metric],
                    aggregations=[self._agg_map[metric.name]],
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_source="single_match",
                    output_metrics=str([metric.name]),
                    output_duration_ms=duration_ms,
                    output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                )

                logger.debug(f"[DSPy Metrics] Single metric resolved - completed in {duration_ms}ms | metric={metric.name}")
                return final_result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Metrics] Error: {e}")
                raise

# =============================================================================
# AGENT 5 — DimensionsModule
# =============================================================================

class DimensionsModule(dspy.Module):
    """
    Resolves group-by dimensions and filter conditions from the classified query.

    Design:
        - LLM returns candidate dimensions from catalog
        - Module enforces:
            1 candidate → accept
            >1 candidates → clarification
            0 candidates → clarification
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveDimensions)

    @staticmethod
    def _build_dimensions_catalog(sales_scope: str) -> str:
        """Return JSON catalog of valid dimensions (minimal, LLM-friendly)."""
        valid_dims = get_valid_dimensions_for_scope(sales_scope)

        catalog = [
            {
                "name": d,
                "description": d.replace("_", " ")
            }
            for d in sorted(valid_dims)
        ]

        return json.dumps(catalog)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        sales_scope: str,
        previous_context=None,
        x_axis_values: Optional[list[str]] = None,
        overrides: Optional[dict] = None,
    ) -> DimensionsResult:
        with tracer.start_as_current_span("dspy.dimensions") as span:
            dim_terms = [t for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE")]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_dim_terms=len(dim_terms),
                input_sales_scope=sales_scope,
                input_has_context=previous_context is not None,
                input_has_x_axis_values=x_axis_values is not None,
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override
                # -------------------------
                if "group_by" in overrides:
                    gb = overrides["group_by"]
                    if isinstance(gb, str):
                        gb = [gb]

                    result = DimensionsResult(group_by=gb, filters=None)
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_group_by=str(gb),
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Dimensions] Override used: {gb}")
                    return result

                valid_dims = get_valid_dimensions_for_scope(sales_scope)

                # -------------------------
                # 2. LLM extraction
                # -------------------------
                # Handle different context types - convert to string for LLM
                context_str = ""
                x_axis_labels_str = "[]"
                if previous_context:
                    if hasattr(previous_context, 'to_prompt_context'):
                        x_axis_list = getattr(previous_context, "x_axis_labels", [])
                        x_axis_dim = getattr(previous_context, "group_by", [None])[0]  # e.g. "zone"
                        if x_axis_list and x_axis_dim:
                            x_axis_labels_str = json.dumps({
                                "dimension": x_axis_dim,
                                "values": x_axis_list
                            })
                    elif isinstance(previous_context, dict):
                        x_axis_list = previous_context.get("x_axis_labels", [])
                        x_axis_dim = (previous_context.get("group_by") or [None])[0]
                        if x_axis_list and x_axis_dim:
                            x_axis_labels_str = json.dumps({
                                "dimension": x_axis_dim,
                                "values": x_axis_list
                            })
                    else:
                        # Already a string
                        context_str = str(previous_context)

                # Override with explicit parameter if provided
                if x_axis_values:
                    x_axis_labels_str = json.dumps(x_axis_values)

                catalog_str = self._build_dimensions_catalog(sales_scope)

                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE")]
                prediction = self.predict(
                    original_query=classified_query.original_query,
                    classified_terms=json.dumps(relevant_terms),
                    sales_scope=sales_scope,
                    available_dimensions=catalog_str,
                    previous_context=context_str,
                    x_axis_values=x_axis_labels_str,
                )

                result: DimensionsResult = prediction.dimensions_result

                # -------------------------
                # 3. Validate candidates
                # -------------------------
                valid_group_by = [
                    d for d in (result.group_by or [])
                    if d in valid_dims and d != "invoice_date"
                ]

                # Compute valid_filters early so it's available in all branches below
                valid_filters = None
                if result.filters:
                    valid_filters = [
                        f for f in result.filters
                        if f.dimension in valid_dims
                    ] or None

                # -------------------------
                # 4. Ambiguity handling (CORE)
                # -------------------------
                dim_terms = [
                    t.term for t in classified_query.classified_terms
                    if t.role == "DIMENSION"
                ]

                # ❗ No valid dimension
                if len(valid_group_by) == 0 and classified_query.query_intent in ["DISTRIBUTION", "RANKING"]:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="dimensions",
                        clarification_reason="no_valid_dimensions"
                    )
                    logger.debug(f"[DSPy Dimensions] Clarification required - no valid dimensions for {classified_query.query_intent}")
                    raise ClarificationRequired(
                        build_dimension_clarification(
                            ambiguous_terms=dim_terms or ["dimension"],
                            candidate_dimensions=sorted(valid_dims),
                        )
                    )

                # ❗ Multiple candidates or multiple terms → sequential clarification
                if len(valid_group_by) > 1 or len(dim_terms) > 1:

                    # For multiple terms, use term-specific field names to track individual resolutions
                    if len(dim_terms) > 1:
                        resolved_dimensions = []
                        pending_terms = []

                        # Check which terms have been resolved using term-specific override keys
                        for term in dim_terms:
                            term_field_key = f"dimension_term_{term}"
                            if term_field_key in overrides:
                                resolved_dimension = overrides[term_field_key]
                                if resolved_dimension in valid_dims and resolved_dimension != "invoice_date":
                                    resolved_dimensions.append(resolved_dimension)
                            else:
                                pending_terms.append(term)

                        if pending_terms:
                            # Loop through pending terms — auto-resolve singletons, ask only when truly ambiguous
                            for first_pending in list(pending_terms):
                                term_field_key = f"dimension_term_{first_pending}"

                                # Create context message about progress
                                total_terms = len(dim_terms)
                                resolved_count = total_terms - len(pending_terms)
                                context = f"Resolving dimension term {resolved_count + 1} of {total_terms}: '{first_pending}'"

                                # Get term-specific candidates by running LLM scoped to just this term
                                term_classified = [t.model_dump() for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE") and t.term == first_pending]
                                term_prediction = self.predict(
                                    original_query=classified_query.original_query,
                                    classified_terms=json.dumps(term_classified),
                                    sales_scope=sales_scope,
                                    available_dimensions=catalog_str,
                                    previous_context=context_str,
                                    x_axis_values=x_axis_labels_str,
                                )
                                term_candidates = [
                                    d for d in (term_prediction.dimensions_result.group_by or [])
                                    if d in valid_dims and d != "invoice_date"
                                ]

                                if len(term_candidates) == 1:
                                    # Exactly one match — auto-resolve, no question needed
                                    resolved_dimensions.append(term_candidates[0])
                                    pending_terms.remove(first_pending)
                                else:
                                    # 0 or 2+ candidates — ask the user
                                    duration_ms = int((time.monotonic() - start_time) * 1000)
                                    _span_set(span,
                                        output_source="clarification_required",
                                        output_duration_ms=duration_ms,
                                        clarification_field=term_field_key,
                                        clarification_reason="multiple_term_ambiguity",
                                        clarifying_term=first_pending
                                    )
                                    term_options = sorted(term_candidates) if term_candidates else sorted(valid_dims)
                                    logger.debug(f"[DSPy Dimensions] Clarification required for term: {first_pending}")
                                    raise ClarificationRequired(Clarification(
                                        request_id=str(uuid.uuid4()),
                                        field=term_field_key,
                                        question=f"Which dimension do you mean by '{first_pending}'?",
                                        options=term_options,
                                        multi_select=False,
                                        context=context,
                                        clarifying_term=first_pending,
                                    ))

                            # All pending terms auto-resolved — return immediately
                            final_result = DimensionsResult(
                                group_by=resolved_dimensions if resolved_dimensions else None,
                                filters=valid_filters,
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="auto_resolved",
                                output_group_by=str(resolved_dimensions),
                                output_duration_ms=duration_ms,
                                output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                            )
                            logger.debug(f"[DSPy Dimensions] Auto-resolved multiple terms - completed in {duration_ms}ms")
                            return final_result

                        else:
                            # All terms resolved via overrides
                            final_result = DimensionsResult(
                                group_by=resolved_dimensions if resolved_dimensions else None,
                                filters=valid_filters,
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="override_resolved",
                                output_group_by=str(resolved_dimensions),
                                output_duration_ms=duration_ms,
                                output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                            )
                            logger.debug(f"[DSPy Dimensions] All terms resolved via overrides - completed in {duration_ms}ms")
                            return final_result

                    else:
                        # Single term, multiple candidates → standard clarification
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="dimensions",
                            clarification_reason="single_term_multiple_candidates"
                        )
                        logger.debug(f"[DSPy Dimensions] Single term with multiple candidates - clarification required")
                        raise ClarificationRequired(
                            build_dimension_clarification(
                                ambiguous_terms=dim_terms,
                                candidate_dimensions=valid_group_by,
                            )
                        )

                # -------------------------
                # 5. Final result
                # -------------------------
                final_result = DimensionsResult(
                    group_by=valid_group_by if valid_group_by else None,
                    filters=valid_filters,
                )
                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_source="final_result",
                    output_group_by=str(valid_group_by),
                    output_filters_count=len(valid_filters or []),
                    output_duration_ms=duration_ms,
                    output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                )

                logger.debug(f"[DSPy Dimensions] Final result - completed in {duration_ms}ms | group_by={valid_group_by} | filters={len(valid_filters or [])}")
                return final_result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Dimensions] Error: {e}")
                raise

# =============================================================================
# AGENT 6 — PostProcessingModule
# =============================================================================

## HELPER CLASS

class PostProcessingResolver:
    def resolve(
        self,
        classified_query: ClassifiedQuery,
        time_result: TimeResult,
        dimensions_result: DimensionsResult,
        llm_output: PostProcessingResult,
    ) -> PostProcessingResult:

        intent = classified_query.query_intent

        # Extract LLM hints safely
        llm_ranking = llm_output.ranking
        llm_comparison = llm_output.comparison
        llm_metric = llm_output.derived_metric

        # =====================================================
        # HARD CONSTRAINT: ranking requires group_by
        # =====================================================
        has_grouping = bool(dimensions_result and dimensions_result.group_by)

        # =====================================================
        # INTENT: RANKING
        # =====================================================
        if intent == "RANKING" and has_grouping:

            order = (
                llm_ranking.order
                if llm_ranking and llm_ranking.order
                else "desc"
            )

            limit = (
                llm_ranking.limit
                if llm_ranking and llm_ranking.limit
                else 10
            )

            return PostProcessingResult(
                ranking=RankingConfig(
                    enabled=True,
                    order=order,
                    limit=limit,
                ),
                comparison=None,
                derived_metric="none",
            )

        # If no grouping → ranking invalid
        if intent == "RANKING" and not has_grouping:
            return PostProcessingResult(
                ranking=None,
                comparison=None,
                derived_metric="none",
            )

        # =====================================================
        # INTENT: COMPARISON
        # =====================================================
        if intent == "COMPARISON":
            time_range_terms = [
                t for t in classified_query.classified_terms
                if t.role == "TIME_RANGE"
            ]

            comparison_window = None
            if llm_comparison and llm_comparison.comparison_window:
                # LLM explicitly resolved a window
                comparison_window = llm_comparison.comparison_window
            elif time_range_terms and time_result and time_result.time_window:
                # TIME_RANGE terms present and TimeModule resolved a window → use as comparison
                comparison_window = time_result.time_window
            # else: explicit start/end dates (feb vs march case) → leave as None

            return PostProcessingResult(
                ranking=None,
                comparison=ComparisonConfig(
                    type="period",
                    comparison_window=comparison_window,
                ),
                derived_metric=llm_metric if llm_metric != "none" else "period_change",
            )

        # =====================================================
        # INTENT: TREND
        # =====================================================
        if intent == "TREND":

            window = time_result.time_window if time_result else None

            if window == "last_7_days":
                metric = "wow_growth"
            elif window in ["last_30_days", "month_to_date"]:
                metric = "mom_growth"
            elif window in ["last_year", "year_to_date"]:
                metric = "yoy_growth"
            else:
                metric = "none"

            return PostProcessingResult(
                ranking=None,
                comparison=None,
                derived_metric=metric,
            )

        # =====================================================
        # DEFAULT: KPI / DISTRIBUTION / DRILL_DOWN / etc.
        # =====================================================
        return PostProcessingResult(
            ranking=None,
            comparison=None,
            derived_metric="none",
        )

class PostProcessingModule(dspy.Module):

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolvePostProcessing)
        self.resolver = PostProcessingResolver()

    def forward(
        self,
        classified_query: ClassifiedQuery,
        time_result: TimeResult,
        dimensions_result: DimensionsResult,
    ) -> PostProcessingResult:
        with tracer.start_as_current_span("dspy.post_processing") as span:
            relevant_terms = [t for t in classified_query.classified_terms if t.role in ("RANKING", "COMPARISON", "TREND")]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_relevant_terms=len(relevant_terms),
                input_has_time_result=time_result is not None,
                input_has_dimensions_result=dimensions_result is not None
            )

            try:
                start_time = time.monotonic()

                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("RANKING", "COMPARISON", "TREND")]
                llm_output = self.predict(
                    query_intent=classified_query.query_intent,
                    classified_terms=json.dumps(relevant_terms),
                    time_result=time_result,
                    dimensions_result=dimensions_result,
                ).post_processing_result

                result = self.resolver.resolve(
                    classified_query,
                    time_result,
                    dimensions_result,
                    llm_output,
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_ranking=str(result.ranking) if result.ranking else "",
                    output_comparison=str(result.comparison) if result.comparison else "",
                    output_derived_metric=result.derived_metric or "",
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy PostProcessing] Completed in {duration_ms}ms | ranking={bool(result.ranking)} | comparison={bool(result.comparison)} | derived={result.derived_metric}")
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy PostProcessing] Error: {e}")
                raise


# =============================================================================
# AGENT 7 — AssemblerModule
# =============================================================================

# class AssemblerModule(dspy.Module):
#     """
#     Merges all upstream agent outputs into the final typed Intent.

#     Inputs  : ClassifiedQuery, ScopeResult, TimeResult, MetricsResult, DimensionsResult
#     Outputs : Intent
#     """

#     def __init__(self):
#         super().__init__()
#         self.predict = dspy.Predict(AssembleIntent)

#     def forward(
#         self,
#         classified_query: ClassifiedQuery,
#         scope_result: ScopeResult,
#         time_result: TimeResult,
#         metrics_result: MetricsResult,
#         dimensions_result: DimensionsResult,
#         post_processing_result: PostProcessingResult,
#     ) -> Intent:
#         """
#         Assemble the final Intent from all upstream results.

#         The LLM handles post_processing derivation (RANKING/COMPARISON/TREND
#         logic) as described in the AssembleIntent signature.  The module
#         trusts Pydantic validation on the Intent model to catch structural
#         issues, logging a warning and re-raising for the caller to handle.

#         Args:
#             classified_query   : Output of ClassifierModule.
#             scope_result       : Output of ScopeModule.
#             time_result        : Output of TimeModule.
#             metrics_result     : Output of MetricsModule.
#             dimensions_result  : Output of DimensionsModule.

#         Returns:
#             Fully populated Intent object.
#         """
#         prediction = self.predict(
#             classified_query=classified_query,
#             scope_result=scope_result,
#             time_result=time_result,
#             metrics_result=metrics_result,
#             dimensions_result=dimensions_result,
#             post_processing_result=post_processing_result,
#         )
#         intent: Intent = prediction.final_intent
#         return intent


class AssemblerModule:
    def forward(
        self,
        classified_query,
        scope_result,
        time_result,
        metrics_result,
        dimensions_result,
        post_processing_result,
    ) -> Intent:
        with tracer.start_as_current_span("dspy.assembler") as span:
            _span_set(span,
                input_intent=classified_query.query_intent if classified_query else "",
                input_has_scope=scope_result is not None,
                input_has_time=time_result is not None,
                input_has_metrics=metrics_result is not None,
                input_has_dimensions=dimensions_result is not None,
                input_has_post_processing=post_processing_result is not None
            )

            try:
                start_time = time.monotonic()

                # -------------------------
                # Metrics (already structured)
                # -------------------------
                # MetricsResult.metrics is already List[MetricSpec]
                metrics = metrics_result.metrics if metrics_result else []

                # -------------------------
                # Time
                # -------------------------
                time_spec = None
                if time_result and (
                    time_result.time_window or
                    time_result.start_date or
                    time_result.end_date
                ):
                    time_spec = TimeSpec(
                        # alias handles mapping internally
                        time_window=time_result.time_window,
                        start_date=time_result.start_date,
                        end_date=time_result.end_date,
                        granularity=time_result.granularity,
                    )

                # -------------------------
                # Filters — merge dimensions filters + classifier filter_hints
                # -------------------------
                filters = dimensions_result.filters if dimensions_result else None

                if not filters and classified_query.filter_hints:
                    filters = [
                        FilterCondition(
                            dimension=hint.dimension,
                            operator="equals",
                            value=hint.value,
                        )
                        for hint in classified_query.filter_hints
                    ]

                # -------------------------
                # Final Intent
                # -------------------------
                result = Intent(
                    sales_scope=scope_result.sales_scope if scope_result else "SECONDARY",
                    metrics=metrics,
                    group_by=dimensions_result.group_by if dimensions_result else None,
                    filters=filters,  # ← use merged filters
                    time=time_spec,
                    post_processing=post_processing_result,
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_sales_scope=result.sales_scope,
                    output_metrics_count=len(metrics),
                    output_group_by_count=len(result.group_by or []),
                    output_filters_count=len(filters or []),
                    output_has_time=time_spec is not None,
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy Assembler] Completed in {duration_ms}ms | metrics={len(metrics)} | group_by={len(result.group_by or [])} | filters={len(filters or [])}")
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Assembler] Error: {e}")
                raise

# =============================================================================
# PIPELINE — IntentExtractionPipeline
# # =============================================================================

# class IntentExtractionPipeline(dspy.Module):
#     """
#     Orchestrates all six agents in sequence and returns the final Intent.

#     Usage:
#         pipeline = IntentExtractionPipeline()
#         intent   = pipeline(query="top 5     The pipeline is stateless. Multi-turn context must be supplied via
#     `previous_context` on each call.
#     """

#     def __init__(self):
#         super().__init__()
#         self.classifier  = ClassifierModule()
#         self.scope       = ScopeModule()
#         self.time        = TimeModule()
#         self.metrics     = MetricsModule()
#         self.dimensions  = DimensionsModule()
#         self.assembler   = AssemblerModule()

#     def forward(
#         self,
#         query: str,
#         current_date: Optional[date] = None,
#         previous_context: Optional[dict] = None,
#     ) -> Intent:
#         """
#         Run the full intent extraction pipeline for a single query.

#         Execution order:
#             1. ClassifierModule  — classify all terms and determine query_intent
#             2. ScopeModule       — resolve PRIMARY / SECONDARY (parallel-safe)
#             3. TimeModule        — resolve time window + granularity (parallel-safe)
#             4. MetricsModule     — extract and validate metrics (parallel-safe)
#             5. DimensionsModule  — resolve group_by and filters (parallel-safe)
#             6. AssemblerModule   — merge outputs into final Intent

#         Steps 2–5 are data-independent after step 1 and can be parallelised if
#         the execution framework supports it (e.g. dspy.Parallel or asyncio).

#         Args:
#             query            : Raw natural-language query from the user.
#             current_date     : Today's date; defaults to date.today().
#             previous_context : Prior QCO result dict for multi-turn conversations.

#         Returns:
#             Intent object ready for downstream query construction.
#         """
#         # Step 1: Classify
#         classified_query = self.classifier(query=query)

#         # Steps 2-5: Resolve independently (sequential for now)
#         scope_result = self.scope(classified_query=classified_query)

#         time_result = self.time(
#             classified_query=classified_query,
#             current_date=current_date,
#             previous_context=previous_context,
#         )

#         metrics_result = self.metrics(
#             classified_query=classified_query,
#             sales_scope=scope_result.sales_scope,
#         )

#         dimensions_result = self.dimensions(
#             classified_query=classified_query,
#             sales_scope=scope_result.sales_scope,
#             previous_context=previous_context,
#         )

#         # Step 6: Assemble
#         intent = self.assembler(
#             classified_query=classified_query,
#             scope_result=scope_result,
#             time_result=time_result,
#             metrics_result=metrics_result,
#             dimensions_result=dimensions_result,
#         )

#         return intent