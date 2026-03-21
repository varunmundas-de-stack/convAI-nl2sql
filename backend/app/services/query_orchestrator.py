"""
Query Orchestrator

PIPELINE FLOW:
1. Receive query + session_id
2. Retrieve previous QCO (if any) from session
3. Call Intent Extractor (QCO injected as LLM context)
4. Merge extracted intent with previous QCO (override rules)
5. Normalize intent (semantic → Cube IDs)
6. Validate intent (Pydantic + catalog)
7. Build Cube Query (mechanical translation)
8. Execute Cube Query (HTTP call to Cube)
9. Generate visualization
10. Resolve QCO (save snapshot for next query)
11. Return structured response

"""

import logging
import time
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path
import uuid
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.services.intent_extractor import (
    extract_intent,
    ExtractionError,
    LLMCallError,
    LLMTimeoutError,
    JSONParseError,
)
from app.services.intent_validator import validate_intent
from app.services.intent_errors import IntentValidationError, IntentIncompleteError
from app.services.cube_query_builder import build_cube_query, build_comparison_query, build_total_query, CubeQueryBuildError
from app.services.cube_client import (
    CubeClient,
    CubeClientError,
    CubeResponse,
    CubeQueryExecutionError,
    CubeHTTPError,
)
from app.services.intent_normalizer import normalize_intent, patch_trend_intent
from app.services.intent_merger import merge_intent
from app.services.qco_resolver import resolve_qco
from app.services.drill_detector import detect_drill, apply_drill_mutation
from app.services.period_planner import determine_strategy, QueryStrategy, transform_intent_for_strategy

from app.services.catalog_manager import CatalogManager
from app.services.insight_engine import generate_insights, InsightResult, InsightEngineError
from app.services.insight_refiner import refine_insights, RefinedInsightResult, InsightRefinerError
from app.services.visual_spec_generator import generate_visual_spec
from app.models.visual_spec import VisualSpec
from app.pipeline.pipeline_state import PipelineState
from app.pipeline.state_store import save_state, load_state, delete_state, PipelineStateNotFound
from app.pipeline.qco_store import save_qco, load_qco
from app.models.intent import Intent
from app.models.qco import QueryContextObject


# =============================================================================
# LOGGING
# =============================================================================

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


# =============================================================================
# PIPELINE STAGE ENUM
# =============================================================================

class PipelineStage:
    """
    Explicit stage names for tracking where the pipeline stopped.
    """
    RECEIVED = "received"
    QCO_LOADED = "qco_loaded"
    INTENT_EXTRACTED = "intent_extracted"
    INTENT_MERGED = "intent_merged"
    CLARIFICATION_REQUESTED = "clarification_requested"
    INTENT_VALIDATED = "intent_validated"
    CUBE_QUERY_BUILT = "cube_query_built"
    CUBE_EXECUTED = "cube_executed"
    INSIGHTS_GENERATED = "insights_generated"
    INSIGHTS_REFINED = "insights_refined"
    VISUAL_SPEC_GENERATED = "visual_spec_generated"
    QCO_RESOLVED = "qco_resolved"
    COMPLETED = "completed"


# =============================================================================
# RESPONSE DATA CLASSES
# =============================================================================

@dataclass
class OrchestratorError:
    """
    Structured error information.
    
    Every failure produces one of these - no exceptions hidden.
    """
    stage: str                          # Where the pipeline stopped
    error_type: str                     # Exception class name
    error_code: Optional[str] = None    # Error code if available (e.g., UNKNOWN_METRIC)
    message: str = ""                   # Human-readable message
    details: Optional[Dict[str, Any]] = None  # Additional error context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details or {},
        }


@dataclass
class OrchestratorResponse:
    """
    Complete response from the orchestrator.
    
    Contains EVERYTHING for debugging, auditing, and demo purposes.
    All fields are exposed - nothing is hidden.
    """
    # Input
    query: str
    
    # Pipeline state
    success: bool
    stage: str                          # Final stage reached
    
    # Optional context
    session_id: Optional[str] = None
    duration_ms: int = 0               # Total pipeline time
    
    # Step outputs (None if step wasn't reached)
    previous_qco: Optional[QueryContextObject] = None
    raw_intent: Optional[Dict[str, Any]] = None
    merged_intent: Optional[Dict[str, Any]] = None
    clarification: Optional[Dict[str, Any]] = None
    validated_intent: Optional[Dict[str, Any]] = None
    original_intent: Optional[Dict[str, Any]] = None
    cube_query: Optional[Dict[str, Any]] = None
    period_strategy: Optional[str] = None   # QueryStrategy value for period/growth queries
    data: Optional[List[Dict[str, Any]]] = None
    comparison_data: Optional[List[Dict[str, Any]]] = None  # Secondary Cube rows (data_b)
    insights: Optional[Any] = None        # InsightResult from insight engine
    refined_insights: Optional[Any] = None  # RefinedInsightResult from insight refiner
    visual_spec: Optional[Any] = None     # VisualSpec from visual spec generator
    
    # RLHF tracking
    prompt_version: Optional[str] = None   # Prompt version used for intent extraction
    ab_group: Optional[str] = None         # A/B test group ("A" or "B", None if no test)
    original_query: Optional[str] = None   # Original user query (before clarifications)
    clarification_answers: Optional[Dict[str, Any]] = None  # Clarification answers provided
    
    
    # Error (None if success)
    error: Optional[OrchestratorError] = None
    
    # Metadata
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    missing_fields: Optional[List[str]] = None
    clarification_message: Optional[str] = None
    allowed_values: Optional[List[str]] = None

    def _get_effective_query(self) -> str:
        """Generate a human-readable effective query combining original query with clarifications."""
        if not self.clarification_answers or not self.original_query:
            return self.query or self.original_query or ""

        # Start with original query
        effective = self.original_query

        # Add clarification context
        clarifications = []
        for field, value in self.clarification_answers.items():
            if isinstance(value, str) and value.strip():
                clarifications.append(f"{field}: {value}")

        if clarifications:
            effective += f" ({', '.join(clarifications)})"

        return effective
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "query": self.query,
            "original_query": self.original_query,
            "clarification_answers": self.clarification_answers,
            "effective_query": self._get_effective_query(),
            "session_id": self.session_id,
            "success": self.success,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "has_previous_context": self.previous_qco is not None,
            "raw_intent": self.raw_intent,
            "merged_intent": self.merged_intent,
            "clarification": self.clarification,
            "missing_fields": self.missing_fields,
            "clarification_message": self.clarification_message,
            "allowed_values": self.allowed_values,
            "validated_intent": (
                self.validated_intent.model_dump()
                if self.validated_intent is not None
                else None
            ),
            "original_intent": (
                self.original_intent.model_dump()
                if self.original_intent is not None and hasattr(self.original_intent, "model_dump")
                else self.original_intent
            ),
            "cube_query": self.cube_query,
            "period_strategy": self.period_strategy,
            "data": self.data,
            "insights": (
                self.insights.model_dump()
                if self.insights else None
            ),
            "refined_insights": (
                self.refined_insights.model_dump()
                if self.refined_insights else None
            ),
            "visual_spec": (
                self.visual_spec.model_dump()
                if self.visual_spec else None
            ),
            "error": self.error.to_dict() if self.error else None,
            "request_id": self.request_id,
            "prompt_version": self.prompt_version,
            "ab_group": self.ab_group,
        }
        return result


# =============================================================================
# CATALOG SINGLETON (Loaded once)
# =============================================================================

_catalog: Optional[CatalogManager] = None

def _get_catalog() -> CatalogManager:
    """
    Get or initialize the catalog manager.
    
    Catalog is loaded once and cached.
    """
    global _catalog
    if _catalog is None:
        catalog_path = Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"
        _catalog = CatalogManager(str(catalog_path))
    return _catalog


# =============================================================================
# ORCHESTRATOR - THE MAIN FUNCTION
# =============================================================================

def execute_query(query: str, session_id: Optional[str] = None, _skip_reset_overrides: bool = False, _resolved_clarifications: Optional[Dict[str, Any]] = None) -> OrchestratorResponse:
    """
    Execute a natural language query through the complete pipeline.
    
    This is the ONLY public function in this module.
    
    Pipeline steps:
    1. Receive query + session_id
    2. Load previous QCO from session (if any)
    3. Extract intent (LLM call, QCO injected as context)
    4. Merge extracted intent with previous QCO
    5. Normalize + Validate intent
    6. Build Cube query (mechanical translation)
    7. Execute Cube query (HTTP call)
    8. Generate visualization
    9. Resolve QCO and save for next query
    10. Return structured response
    
    Args:
        query: Natural language query string (passed as-is, no cleanup)
        session_id: Optional session identifier for conversational context
        
    Returns:
        OrchestratorResponse with all intermediate outputs and any error
    """
    with tracer.start_as_current_span("pipeline") as root_span:
        root_span.set_attribute("input.query", query[:500])
        root_span.set_attribute("input.session_id", session_id or "")
        root_span.set_attribute("input.value", json.dumps({"query": query, "session_id": session_id}))
        root_span.set_attribute("input.query_length", len(query))

        start_time = time.monotonic()
        
        # Initialize response with input
        response = OrchestratorResponse(
            query=query,
            session_id=session_id,
            success=False,
            stage=PipelineStage.RECEIVED,
        )
        response.original_query = query  # Store the original query
        
        logger.info(f"Pipeline started: '{query[:100]}...' (session={session_id})")
        
        # -------------------------------------------------------------------------
        # STEP 1: Load previous QCO (non-fatal if missing)
        # -------------------------------------------------------------------------
        previous_qco = None
        if session_id:
            with tracer.start_as_current_span("qco.load") as qco_span:
                qco_span.set_attribute("input.session_id", session_id)
                qco_span.set_attribute("input.value", json.dumps({"session_id": session_id}))
                try:
                    previous_qco = load_qco(session_id)
                    if previous_qco:
                        response.previous_qco = previous_qco
                        response.stage = PipelineStage.QCO_LOADED
                        qco_span.set_attribute("output.found", True)
                        qco_span.set_attribute("output.metric", previous_qco.metric or "")
                        qco_span.set_attribute("output.sales_scope", previous_qco.sales_scope or "")
                        qco_span.set_attribute("output.value", str(previous_qco) if previous_qco else "")
                        logger.info(f"Loaded previous QCO for session {session_id}: "
                                    f"metric={previous_qco.metric}, scope={previous_qco.sales_scope}")
                    else:
                        qco_span.set_attribute("output.found", False)
                        logger.info(f"No previous QCO for session {session_id} (first query)")
                except Exception as e:
                    qco_span.set_status(Status(StatusCode.ERROR, str(e)))
                    qco_span.record_exception(e)
                    logger.warning(f"Failed to load QCO for session {session_id}: {e}")
        
        # -------------------------------------------------------------------------
        # STEP 1.5: Resolve RLHF prompt version via A/B routing
        # -------------------------------------------------------------------------
        try:
            from app.rlhf.prompt_manager import get_ab_version
            prompt_version, ab_group = get_ab_version(session_id or response.request_id)
            response.prompt_version = prompt_version
            response.ab_group = ab_group
            logger.info(f"RLHF: prompt_version={prompt_version}, ab_group={ab_group}")
        except Exception as e:
            logger.warning(f"RLHF version resolution failed (non-fatal): {e}")
            response.prompt_version = "v1"
        
        # -------------------------------------------------------------------------
        # STEP 2: Extract intent (LLM call, with QCO context)
        # -------------------------------------------------------------------------
        response = _extract_intent(response, start_time, previous_qco=previous_qco, skip_reset_overrides=_skip_reset_overrides)
        if response.error:
            root_span.set_status(Status(StatusCode.ERROR, response.error.message))
            root_span.set_attribute("error.type", response.error.error_type)
            root_span.set_attribute("error.stage", response.error.stage)
            root_span.set_attribute("error.message", response.error.message)
            return response
        # DSPy pipeline may raise clarification at extraction stage (before validation)
        if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
            root_span.set_attribute("output.clarification_requested", True)
            root_span.set_attribute("output.missing_fields", str(response.missing_fields or []))
            root_span.set_attribute("output.clarification_message", response.clarification_message or "")
            state = PipelineState(
                request_id=response.request_id,
                original_query=query,
                intent=response.raw_intent or {},
                missing_fields=response.missing_fields or [],
                session_id=session_id,
                resolved_clarifications=_resolved_clarifications or {}
            )
            save_state(state)
            logger.info(f"DSPy clarification requested at extraction stage, saved state {response.request_id}")
            return response
        
        # -------------------------------------------------------------------------
        # STEP 2.5: Detect and apply drill-down mutation (before generic merge)
        # -------------------------------------------------------------------------
        drill_result = None
        if previous_qco and response.raw_intent:
            with tracer.start_as_current_span("drill_detection") as drill_span:
                drill_span.set_attribute("input.value", json.dumps({"raw_intent": response.raw_intent, "previous_qco": str(previous_qco)}, default=str))
                drill_result = detect_drill(response.raw_intent, previous_qco)
                drill_span.set_attribute("output.case", drill_result.case)
                if drill_result.case != "none":
                    response.raw_intent = apply_drill_mutation(
                        response.raw_intent, previous_qco, drill_result
                    )
                    drill_span.set_attribute("output.prev_dimension", drill_result.prev_dimension or "")
                    drill_span.set_attribute("output.next_dimension", drill_result.next_dimension or "")
                    drill_span.set_attribute("output.value", str(drill_result))
                    logger.info(f"Drill [{drill_result.case}]: "
                                f"{drill_result.prev_dimension} → {drill_result.next_dimension}")
        
        # -------------------------------------------------------------------------
        # STEP 3: Merge intent with previous QCO
        # -------------------------------------------------------------------------
        with tracer.start_as_current_span("intent.merge") as merge_span:
            if previous_qco and response.raw_intent:
                merge_span.set_attribute("input.raw_intent", str(response.raw_intent)[:1000])
                merge_span.set_attribute("input.qco_metric", previous_qco.metric or "")
                merge_span.set_attribute("input.value", json.dumps({"raw_intent": response.raw_intent, "previous_qco": str(previous_qco)}, default=str))
                response.merged_intent = merge_intent(response.raw_intent, previous_qco)
                response.stage = PipelineStage.INTENT_MERGED
                merge_span.set_attribute("output.merged_with_qco", True)
                merge_span.set_attribute("output.merged_intent", str(response.merged_intent)[:1000])
                merge_span.set_attribute("output.value", json.dumps(response.merged_intent, default=str))
                logger.info(f"Intent merged with previous QCO")
            else:
                response.merged_intent = response.raw_intent
                merge_span.set_attribute("output.merged_with_qco", False)
                merge_span.set_attribute("output.value", json.dumps(response.merged_intent, default=str))
        
        # -------------------------------------------------------------------------
        # STEP 4: Validate intent (uses merged intent)
        # -------------------------------------------------------------------------
        response = _validate_intent(response, start_time)
        if response.error:
            root_span.set_status(Status(StatusCode.ERROR, response.error.message))
            root_span.set_attribute("error.type", response.error.error_type)
            root_span.set_attribute("error.stage", response.error.stage)
            root_span.set_attribute("error.message", response.error.message)
            return response
        if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
            root_span.set_attribute("output.clarification_requested", True)
            root_span.set_attribute("output.missing_fields", str(response.missing_fields or []))
            root_span.set_attribute("output.clarification_message", response.clarification_message or "")
            # Save state for later resumption (including session_id)
            state = PipelineState(
                request_id=response.request_id,
                original_query=query,
                intent=response.merged_intent or response.raw_intent,
                missing_fields=response.missing_fields or [],
                session_id=session_id,
                resolved_clarifications=_resolved_clarifications or {}
            )
            save_state(state)
            logger.info(f"Clarification requested, saved state {response.request_id}")
            return response
        
        # -------------------------------------------------------------------------
        # STEP 5: Build Cube query
        # -------------------------------------------------------------------------
        response = _build_cube_query(response, start_time)
        if response.error:
            root_span.set_status(Status(StatusCode.ERROR, response.error.message))
            root_span.set_attribute("error.type", response.error.error_type)
            root_span.set_attribute("error.stage", response.error.stage)
            root_span.set_attribute("error.message", response.error.message)
            return response
        
        # -------------------------------------------------------------------------
        # STEP 6: Execute Cube query
        # -------------------------------------------------------------------------
        response = _execute_cube_query(response, start_time)
        if response.error:
            root_span.set_status(Status(StatusCode.ERROR, response.error.message))
            root_span.set_attribute("error.type", response.error.error_type)
            root_span.set_attribute("error.stage", response.error.stage)
            root_span.set_attribute("error.message", response.error.message)
            return response
        
        # -------------------------------------------------------------------------
        # STEP 7: Generate insights + visual spec
        # -------------------------------------------------------------------------
        response = _generate_insights_and_spec(response, start_time, previous_qco=previous_qco)
        if response.error:
            root_span.set_status(Status(StatusCode.ERROR, response.error.message))
            root_span.set_attribute("error.type", response.error.error_type)
            root_span.set_attribute("error.stage", response.error.stage)
            root_span.set_attribute("error.message", response.error.message)
            return response
        
        # -------------------------------------------------------------------------
        # STEP 8: Resolve QCO and save for next query
        # -------------------------------------------------------------------------
        if session_id and response.validated_intent:
            with tracer.start_as_current_span("qco.resolve") as resolve_span:
                resolve_span.set_attribute("input.session_id", session_id)
                resolve_span.set_attribute("input.value", json.dumps(getattr(response.validated_intent, "model_dump", lambda: str(response.validated_intent))(), default=str))
                try:
                    qco = resolve_qco(response.original_intent or response.validated_intent, query)
                    save_qco(session_id, qco)
                    response.stage = PipelineStage.QCO_RESOLVED
                    resolve_span.set_attribute("output.resolved", True)
                    resolve_span.set_attribute("output.qco_metric", qco.metric or "")
                    resolve_span.set_attribute("output.value", str(qco))
                    logger.info(f"QCO resolved and saved for session {session_id}")
                except Exception as e:
                    resolve_span.set_status(Status(StatusCode.ERROR, str(e)))
                    resolve_span.record_exception(e)
                    resolve_span.set_attribute("output.resolved", False)
                    logger.warning(f"Failed to resolve/save QCO: {e}")
        
        # -------------------------------------------------------------------------
        # STEP 9: Complete pipeline
        # -------------------------------------------------------------------------
        response = _complete_pipeline(response, start_time)
        
        # Final root span attributes
        root_span.set_attribute("output.success", response.success)
        root_span.set_attribute("output.stage", response.stage)
        root_span.set_attribute("output.duration_ms", response.duration_ms)
        root_span.set_attribute("output.row_count", len(response.data or []))
        if response.period_strategy:
            root_span.set_attribute("output.period_strategy", response.period_strategy)
        if response.visual_spec:
            root_span.set_attribute("output.chart_type", response.visual_spec.chart_type or "")
        if response.insights and response.insights.primary_insight:
            root_span.set_attribute("output.primary_insight", response.insights.primary_insight.label)
        
        root_span.set_attribute("output.value", json.dumps(response.to_dict(), default=str))
        
        return response


# =============================================================================
# PUBLIC API - SIMPLE DICT WRAPPER
# =============================================================================

def execute_query_dict(query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute a query and return a JSON-serializable dict.
    
    This is a convenience wrapper for execute_query() that returns a dict
    instead of an OrchestratorResponse object.
    
    Args:
        query: Natural language query string
        session_id: Optional session identifier for conversational context
        
    Returns:
        Dict with all pipeline outputs (JSON-serializable)
    """
    response = execute_query(query, session_id=session_id)
    return response.to_dict()
 

def resume_query(request_id: str, clarification_answers: dict, session_id: Optional[str] = None) -> dict:
    with tracer.start_as_current_span("pipeline.resume") as span:
        span.set_attribute("input.request_id", request_id)
        span.set_attribute("input.session_id", session_id or "")
        span.set_attribute("input.clarification_keys", str(list(clarification_answers.keys())))
        span.set_attribute("input.clarification_answers", str(clarification_answers)[:500])
        span.set_attribute("input.value", json.dumps(clarification_answers, default=str))
        result = _resume_query_inner(request_id, clarification_answers, session_id=session_id)
        # _resume_query_inner may return an OrchestratorResponse (when DSPy re-runs
        # execute_query) or a plain dict. Normalise to dict for span tracking.
        if hasattr(result, "to_dict"):
            result = result.to_dict()
        span.set_attribute("output.success", result.get("success", False))
        span.set_attribute("output.stage", result.get("stage", ""))
        span.set_attribute("output.row_count", len(result.get("data") or []))
        span.set_attribute("output.value", json.dumps(result, default=str))
        if not result.get("success") and result.get("error"):
            err = result["error"]
            span.set_status(Status(StatusCode.ERROR, err.get("message", "")))
            span.set_attribute("error.type", err.get("error_type", ""))
            span.set_attribute("error.message", err.get("message", ""))
        return result


def _resume_query_inner(request_id: str, clarification_answers: dict, session_id: Optional[str] = None) -> dict:
    start_time = time.monotonic()

    try:
        state = load_state(request_id)
    except PipelineStateNotFound:
        logger.warning(
            f"Pipeline state not found for request_id={request_id}. "
            f"State may have expired (TTL) or server was restarted. "
            f"Clarification answers received: {list(clarification_answers.keys())}"
        )
        return {
            "success": False,
            "stage": "invalid_request",
            "request_id": request_id,
            "session_id": session_id,
            "error": {
                "error_type": "PipelineStateNotFound",
                "message": "Invalid or expired request_id. Please start a new query.",
                "details": {
                    "request_id": request_id,
                    "hint": "Pipeline state expires after 1 hour or when server restarts"
                }
            }
        }

    # Recover session_id from state if not provided by caller
    resolved_session_id = session_id or state.session_id

    # Check if this is a DSPy clarification that needs special handling
    if (state.intent.get("dspy_clarification_request_id") and
        state.intent.get("clarification_type") in ["metric", "dimension", "time"]):

        logger.info(f"Handling DSPy clarification for request {state.intent.get('dspy_clarification_request_id')}")

        try:
            clarification_type = state.intent["clarification_type"]
            dspy_request_id = state.intent["dspy_clarification_request_id"]
            # Use the options stored in the saved intent — no dependency on the in-memory tool
            dspy_options = state.intent.get("dspy_clarification_options", [])

            # Build lookup maps from stored options
            label_to_value = {opt["label"]: opt["value"] for opt in dspy_options}
            id_to_value = {opt["id"]: opt["value"] for opt in dspy_options}
            # Also build case-insensitive maps for robustness
            label_lower_to_value = {k.lower(): v for k, v in label_to_value.items()}
            id_lower_to_value = {k.lower(): v for k, v in id_to_value.items()}
            value_set = {opt["value"] for opt in dspy_options}

            # Resolve what the user selected (support many answer formats)
            resolved_value = None
            for _field, answer in clarification_answers.items():
                candidates = answer if isinstance(answer, list) else [answer]
                for candidate in candidates:
                    candidate = str(candidate).strip()
                    cl = candidate.lower()

                    # 1. Exact label match  (e.g. "State")
                    if candidate in label_to_value:
                        resolved_value = label_to_value[candidate]
                    # 2. Exact id match  (e.g. "state")
                    elif candidate in id_to_value:
                        resolved_value = id_to_value[candidate]
                    # 3. Direct value match  (e.g. "state" is itself the catalog value)
                    elif candidate in value_set:
                        resolved_value = candidate
                    # 4. Case-insensitive label match  (e.g. "STATE")
                    elif cl in label_lower_to_value:
                        resolved_value = label_lower_to_value[cl]
                    # 5. Case-insensitive id match
                    elif cl in id_lower_to_value:
                        resolved_value = id_lower_to_value[cl]
                    else:
                        # 6. "Label: description" format — UI sends this when user picks a chip
                        #    e.g. "State: State dimension"  →  label = "State"
                        if ":" in candidate:
                            label_part = candidate.split(":", 1)[0].strip()
                            resolved_value = (
                                label_to_value.get(label_part)
                                or label_lower_to_value.get(label_part.lower())
                            )
                        # 7. Partial / substring label match as last resort
                        if not resolved_value:
                            for label, value in label_to_value.items():
                                if cl in label.lower() or label.lower() in cl:
                                    resolved_value = value
                                    break

                    if resolved_value:
                        break
                if resolved_value:
                    break

            if resolved_value:
                logger.info(f"DSPy clarification resolved to value: '{resolved_value}' (type={clarification_type})")

                # Also mark as resolved in the clarification tool if request is still pending
                try:
                    from app.dspy_pipeline.clarification_tool import clarification_tool as _dspy_tool
                    pending_req = _dspy_tool.get_clarification_request(dspy_request_id)
                    if pending_req:
                        matched_ids = [opt.id for opt in pending_req.options if opt.value == resolved_value]
                        if matched_ids:
                            _dspy_tool.provide_clarification(request_id=dspy_request_id,
                                                             selected_option_ids=matched_ids)
                except Exception as _ce:
                    logger.debug(f"Could not mark DSPy clarification as completed (non-fatal): {_ce}")

                # Build a clean patched intent (strip DSPy metadata keys)
                _dspy_meta_keys = {"clarification_type", "dspy_clarification_request_id",
                                   "dspy_clarification_options"}
                base_intent = {k: v for k, v in state.intent.items() if k not in _dspy_meta_keys}

                # Ensure base_intent has required fields with defaults if missing
                if "sales_scope" not in base_intent:
                    base_intent["sales_scope"] = "SECONDARY"
                if "metrics" not in base_intent:
                    base_intent["metrics"] = [{"name": "net_value", "aggregation": "sum"}]

                # Inject the resolved value into the right field
                if clarification_type == "dimension":
                    base_intent["group_by"] = [resolved_value]
                elif clarification_type == "metric":
                    base_intent["metrics"] = [{"name": resolved_value, "aggregation": "sum"}]
                elif clarification_type == "time":
                    # Handle time clarification - the resolved_value should be a time window
                    base_intent["time"] = {
                        "dimension": "invoice_date",
                        "window": resolved_value,
                        "start_date": None,
                        "end_date": None,
                        "granularity": None
                    }

                logger.info(
                    f"DSPy clarification resolved for '{resolved_value}' — re-running full pipeline "
                    f"to discover any remaining ambiguities (multi-clarification support)"
                )

                # Store the resolved clarification to prevent infinite loops
                resolved_clarifications = getattr(state, 'resolved_clarifications', {}) or {}
                
                # Map DSPy clarification type back to the field name agents check for
                field_name_map = {
                    "dimension": "group_by",
                    "metric": "metrics", 
                    "time": "time"
                }
                mapped_field = field_name_map.get(clarification_type, clarification_type)
                resolved_clarifications[mapped_field] = resolved_value

                # Seed the per-request field override so DimensionsAgent /
                # MetricsAgent / TimeAgent can skip re-asking for this already-answered term
                # without scanning global completed_responses (which leaks across requests).
                # IMPORTANT: reset first, then set — so any stale overrides from a
                # prior request are cleared before seeding the new answer.
                try:
                    from app.dspy_pipeline.clarification_tool import clarification_tool as _dspy_ct
                    _dspy_ct.reset_for_new_request()  # clear any prior session's values

                    # Restore all previously resolved clarifications
                    for prev_type, prev_value in resolved_clarifications.items():
                        # Backward compatibility for states saved before the mapping fix
                        field_name_map = {
                            "dimension": "group_by",
                            "metric": "metrics", 
                            "time": "time"
                        }
                        actual_type = field_name_map.get(prev_type, prev_type)
                        _dspy_ct.set_field_override(actual_type, prev_value)
                        logger.info(f"Restored clarification override: {actual_type} = {prev_value}")

                except Exception as e:
                    logger.warning(f"Failed to set clarification overrides: {e}")
                    pass
                # Delete the old state — a fresh state will be created if needed on the next run
                try:
                    delete_state(state.request_id)
                except Exception:
                    pass
                # Re-run the full pipeline: the DimensionsAgent will see the resolved
                # clarification in field_resolved_overrides and skip re-asking for it.
                # Any NEW ambiguity found will trigger another clarification round.
                return execute_query(
                    query=state.original_query,
                    session_id=resolved_session_id,
                    _skip_reset_overrides=True,  # Preserve field overrides for multi-clarification
                    _resolved_clarifications=resolved_clarifications
                )
            else:
                logger.warning("Could not resolve DSPy clarification answer to a known option — falling through")

        except Exception as e:
            logger.error(f"Error handling DSPy clarification: {e}")
            # Fall through to standard clarification handling


    # Standard clarification handling for non-DSPy clarifications
    # BUG-02 FIX: Load previous QCO so merge_intent can apply inheritance rules
    previous_qco = None
    if resolved_session_id:
        try:
            previous_qco = load_qco(resolved_session_id)
        except Exception as e:
            logger.warning(f"Could not load QCO on resume for session {resolved_session_id}: {e}")

    # Patch the saved intent with the user's clarification answers
    patched_intent = {
        **state.intent,
        **{k: v for k, v in clarification_answers.items() if k in state.missing_fields}
    }

    # Run through full merge pipeline so QCO context (filters, group_by, etc.) is inherited
    merged_intent = merge_intent(patched_intent, previous_qco) if previous_qco else patched_intent
    logger.info(f"Resume merged intent: {merged_intent}")

    # Resolve RLHF prompt version for consistency
    try:
        from app.rlhf.prompt_manager import get_ab_version
        prompt_version, ab_group = get_ab_version(resolved_session_id or request_id)
    except Exception as e:
        logger.warning(f"RLHF version resolution failed (non-fatal): {e}")
        prompt_version = "v1"
        ab_group = None

    # BUG-01 FIX: do NOT delete state here — delete only after full pipeline success
    response = OrchestratorResponse(
        query=state.original_query,  # Keep as original query for now
        success=False,
        stage=PipelineStage.INTENT_EXTRACTED,
        raw_intent=patched_intent,
        merged_intent=merged_intent,
        request_id=request_id,
        session_id=resolved_session_id,
        prompt_version=prompt_version,
        ab_group=ab_group,
    )
    response.original_query = state.original_query  # Preserve original query through clarification
    response.clarification_answers = clarification_answers  # Store clarification answers

    try:
        # Re-enter pipeline at validation (same as fresh run)
        response = _validate_intent(response, start_time)
        if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
            save_state(PipelineState(
                request_id=request_id,
                original_query=state.original_query,
                intent=merged_intent,
                missing_fields=response.missing_fields or [],
                session_id=resolved_session_id,
                resolved_clarifications=getattr(state, 'resolved_clarifications', {}) or {}
            ))
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response.to_dict()

        response = _build_cube_query(response, start_time)
        if response.error:
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response.to_dict()

        response = _execute_cube_query(response, start_time)
        if response.error:
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response.to_dict()


        # BUG-09 FIX: forward previous_qco so the insight engine has delta/comparison context
        response = _generate_insights_and_spec(response, start_time, previous_qco=previous_qco)
        if response.error:
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response.to_dict()

        # Save QCO on successful completion
        if resolved_session_id and response.validated_intent:
            try:
                qco = resolve_qco(response.validated_intent, state.original_query)
                save_qco(resolved_session_id, qco)
                logger.info(f"QCO resolved and saved for session {resolved_session_id} (via clarification)")
            except Exception as e:
                logger.warning(f"Failed to resolve/save QCO after clarification: {e}")

        response = _complete_pipeline(response, start_time)

        # Cleanup only after full success
        delete_state(request_id)

        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response.to_dict()

    except IntentValidationError as e:
        delete_state(request_id)
        response.error = OrchestratorError(
            stage=response.stage,
            error_type=e.__class__.__name__,
            message=str(e),
            details=e.to_dict() if hasattr(e, "to_dict") else None
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response.to_dict()

    except Exception as e:
        delete_state(request_id)
        response.error = OrchestratorError(
            stage=response.stage,
            error_type=e.__class__.__name__,
            message=str(e),
            details=e.to_dict() if hasattr(e, "to_dict") else None
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response.to_dict()


def _extract_intent(response: OrchestratorResponse, start_time: float, previous_qco: Optional[QueryContextObject] = None, skip_reset_overrides: bool = False) -> OrchestratorResponse:
    with tracer.start_as_current_span("intent.extract") as span:
        span.set_attribute("input.query", response.query[:500])
        span.set_attribute("input.has_previous_qco", previous_qco is not None)
        span.set_attribute("input.value", json.dumps({"query": response.query, "previous_qco": str(previous_qco) if previous_qco else None}, default=str))
        if previous_qco:
            span.set_attribute("input.previous_qco_metric", previous_qco.metric or "")
            span.set_attribute("input.previous_qco_scope", previous_qco.sales_scope or "")
        try:
            logger.info("Step 2: Extracting intent...")
            raw_intent = extract_intent(
                response.query,
                previous_qco=previous_qco,
                prompt_version=response.prompt_version,
                skip_reset_overrides=skip_reset_overrides
            )
            response.raw_intent = raw_intent
            response.stage = PipelineStage.INTENT_EXTRACTED
            span.set_attribute("output.intent_type", str(raw_intent.get("intent_type", "")))
            span.set_attribute("output.metric", str(raw_intent.get("metric", "")))
            span.set_attribute("output.dimensions", str(raw_intent.get("dimensions", [])))
            span.set_attribute("output.time_range", str(raw_intent.get("time", "")))
            span.set_attribute("output.raw_intent", str(raw_intent)[:1000])
            span.set_attribute("output.value", json.dumps(raw_intent, default=str))
            logger.info(f"Intent extracted: {raw_intent}")

        except IntentIncompleteError as e:
            # DSPy pipeline requested clarification during intent extraction
            logger.warning(f"DSPy clarification needed during extraction: {e}")
            span.set_attribute("output.clarification_requested", True)
            span.set_attribute("output.missing_fields", str(e.missing_fields))
            span.set_attribute("output.clarification_message", e.clarification_message or "")
            response.clarification = True
            response.missing_fields = e.missing_fields
            response.clarification_message = e.clarification_message
            response.allowed_values = e.allowed_values
            # Store DSPy clarification metadata into raw_intent so resume_query can use it
            raw_intent = e.partial_intent or {}
            response.raw_intent = raw_intent
            response.stage = PipelineStage.CLARIFICATION_REQUESTED
            response.error = None
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        except JSONParseError as e:
            logger.error(f"JSON parse error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "JSONParseError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.RECEIVED,
                error_type="JSONParseError",
                message=str(e),
                details={"raw_response": str(getattr(e, '__cause__', None))}
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        except LLMTimeoutError as e:
            logger.error(f"LLM timeout: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "LLMTimeoutError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.RECEIVED,
                error_type="LLMTimeoutError",
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        except LLMCallError as e:
            logger.error(f"LLM call error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "LLMCallError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.RECEIVED,
                error_type="LLMCallError",
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        except ExtractionError as e:
            logger.error(f"Extraction error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "ExtractionError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.RECEIVED,
                error_type="ExtractionError",
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        return response

    
def _validate_intent(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    with tracer.start_as_current_span("intent.validate") as span:
        intent_source = "merged" if response.merged_intent else "raw"
        intent_to_log = response.merged_intent or response.raw_intent or {}
        span.set_attribute("input.intent_source", intent_source)
        span.set_attribute("input.intent", str(intent_to_log)[:1000])
        span.set_attribute("input.value", json.dumps(intent_to_log, default=str))
        try:
            catalog = _get_catalog()
            logger.info("Step 4: Validating intent...")
            intent_to_validate = response.merged_intent or response.raw_intent
            normalized_intent = normalize_intent(intent_to_validate)
            normalized_intent = patch_trend_intent(normalized_intent, response.query)
            validated_intent = validate_intent(normalized_intent, catalog, original_query=response.query)
            response.validated_intent = validated_intent
            response.stage = PipelineStage.INTENT_VALIDATED
            intent_type = getattr(validated_intent, "intent_type", None)
            metrics = getattr(validated_intent, "metrics", None)
            dimensions = getattr(validated_intent, "group_by", None)
            if intent_type:
                span.set_attribute("output.intent_type", str(intent_type))
            if metrics:
                span.set_attribute("output.metrics", str(metrics)[:500])
            if dimensions:
                span.set_attribute("output.dimensions", str(dimensions)[:500])
            span.set_attribute("output.value", json.dumps(getattr(validated_intent, "model_dump", lambda: str(validated_intent))(), default=str))
            logger.info(f"Intent validated: {validated_intent}")

        except IntentIncompleteError as e:
            logger.warning(f"Incomplete intent: {e}")
            span.set_attribute("output.clarification_requested", True)
            span.set_attribute("output.missing_fields", str(e.missing_fields))
            span.set_attribute("output.clarification_message", e.clarification_message or "")
            response.clarification = True
            response.missing_fields = e.missing_fields
            response.clarification_message = e.clarification_message
            response.allowed_values = e.allowed_values
            response.stage = PipelineStage.CLARIFICATION_REQUESTED
            response.error = None
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        except IntentValidationError as e:
            logger.error(f"Intent validation failed: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "IntentValidationError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.INTENT_EXTRACTED,
                error_type="IntentValidationError",
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        return response


def _build_cube_query(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    with tracer.start_as_current_span("cube.build_query") as span:
        try:
            logger.info("Step 5: Building Cube query...")

            try:
                strategy = determine_strategy(response.validated_intent)
                response.period_strategy = strategy.value
                span.set_attribute("output.strategy", strategy.value)
                logger.info(f"Strategy determined: {strategy.value}")
            except Exception as e:
                logger.warning(f"Period strategy determination failed (non-fatal): {e}")
                strategy = QueryStrategy.SINGLE_QUERY
                response.period_strategy = strategy.value
                span.set_attribute("output.strategy", strategy.value)

            response.original_intent = response.validated_intent
            transformed_intent = transform_intent_for_strategy(response.validated_intent, strategy)
            response.validated_intent = transformed_intent
            span.set_attribute("input.value", json.dumps(getattr(transformed_intent, "model_dump", lambda: str(transformed_intent))(), default=str))

            cube_query = build_cube_query(transformed_intent)
            response.cube_query = cube_query
            response.stage = PipelineStage.CUBE_QUERY_BUILT
            span.set_attribute("output.measures", str(cube_query.get("measures", [])))
            span.set_attribute("output.dimensions", str(cube_query.get("dimensions", [])))
            span.set_attribute("output.filters", str(cube_query.get("filters", []))[:500])
            span.set_attribute("output.time_dimensions", str(cube_query.get("timeDimensions", []))[:500])
            span.set_attribute("output.limit", str(cube_query.get("limit", "")))
            span.set_attribute("output.value", json.dumps(cube_query, default=str))
            logger.info(f"Cube query built: {cube_query}")

        except CubeQueryBuildError as e:
            logger.error(f"Cube query build error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "CubeQueryBuildError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.INTENT_VALIDATED,
                error_type="CubeQueryBuildError",
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        return response


def _execute_cube_query(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    """
    Execute Cube HTTP call(s) and store raw results.
    """
    with tracer.start_as_current_span("cube.execute") as span:
        strategy = response.period_strategy or QueryStrategy.SINGLE_QUERY.value
        intent   = response.validated_intent
        span.set_attribute("input.strategy", strategy)
        span.set_attribute("input.cube_query", str(response.cube_query)[:1000])
        span.set_attribute("input.value", json.dumps({"cube_query": response.cube_query, "strategy": strategy}, default=str))

        try:
            cube_client = CubeClient()

            logger.info(f"Step 4: Executing Cube query (strategy={strategy})...")
            with tracer.start_as_current_span("cube.primary_query") as primary_span:
                cube_response_a = _cube_load(cube_client, response.cube_query, response, start_time)
                if cube_response_a is None:
                    primary_span.set_status(Status(StatusCode.ERROR, "Primary cube query returned None"))
                    span.set_status(Status(StatusCode.ERROR, "Primary cube query failed"))
                    return response
                response.data = cube_response_a.data
                primary_span.set_attribute("output.row_count", len(response.data))
                if response.data:
                    primary_span.set_attribute("output.sample_row", str(response.data[0])[:500])
                primary_span.set_attribute("output.value", json.dumps(response.data[:100] if response.data else [], default=str))
                logger.info(f"Primary query executed: {len(response.data)} rows")
            span.set_attribute("output.primary_row_count", len(response.data))
            span.set_attribute("output.value", json.dumps(response.data[:100] if response.data else [], default=str))

            if strategy == QueryStrategy.DUAL_QUERY.value:
                with tracer.start_as_current_span("cube.comparison_query") as cmp_span:
                    try:
                        comparison_query = build_comparison_query(intent)
                        cmp_span.set_attribute("input.cube_query", str(comparison_query)[:1000])
                        cube_response_b = _cube_load(cube_client, comparison_query, response, start_time)
                        if cube_response_b is None:
                            return response
                        response.comparison_data = cube_response_b.data
                        cmp_span.set_attribute("output.row_count", len(response.comparison_data))
                        logger.info(f"Comparison query executed: {len(response.comparison_data)} rows")
                    except Exception as e:
                        cmp_span.set_status(Status(StatusCode.ERROR, str(e)))
                        cmp_span.record_exception(e)
                        logger.warning(f"Comparison query failed, proceeding without it: {e}")

            elif strategy == QueryStrategy.CONTRIBUTION.value:
                with tracer.start_as_current_span("cube.total_query") as total_span:
                    try:
                        total_query = build_total_query(intent)
                        total_span.set_attribute("input.cube_query", str(total_query)[:1000])
                        cube_response_total = _cube_load(cube_client, total_query, response, start_time)
                        if cube_response_total is None:
                            return response
                        response.comparison_data = cube_response_total.data
                        total_span.set_attribute("output.row_count", len(response.comparison_data))
                        logger.info(f"Total query executed: {len(response.comparison_data)} rows")
                    except Exception as e:
                        total_span.set_status(Status(StatusCode.ERROR, str(e)))
                        total_span.record_exception(e)
                        logger.warning(f"Total query failed, proceeding without it: {e}")

            response.stage = PipelineStage.CUBE_EXECUTED

        except CubeQueryExecutionError as e:
            logger.error(f"Cube query execution error: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "CubeQueryExecutionError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.CUBE_QUERY_BUILT,
                error_type="CubeQueryExecutionError",
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        return response


def _cube_load(
    client: CubeClient,
    query: Dict[str, Any],
    response: OrchestratorResponse,
    start_time: float,
) -> Optional["CubeResponse"]:
    """
    Execute a single Cube load call. On HTTP error, sets response.error and returns None.
    """
    try:
        # Fetch and log the compiled SQL query before executing
        client.get_sql(query)
        
        result = client.load(query)
        return result
    except CubeHTTPError as e:
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_QUERY_BUILT,
            error_type="CubeHTTPError",
            message="Cube query failed",
            details=e.to_dict() if hasattr(e, "to_dict") else None,
        )
        response.success = False
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return None


def _generate_insights_and_spec(
    response: OrchestratorResponse, 
    start_time: float,
    previous_qco: Optional[QueryContextObject] = None,
) -> OrchestratorResponse:
    """
    Three-step intelligence + presentation pipeline:
    1. Insight Engine: analyze data → machine-readable insights (deterministic)
    2. Insight Refiner: insights → refined insights (LLM-enhanced)
    3. Visual Spec Generator: refined insights + data → declarative visual spec
    """
    with tracer.start_as_current_span("insights") as outer_span:
        outer_span.set_attribute("input.data_row_count", len(response.data or []))
        outer_span.set_attribute("input.has_comparison_data", response.comparison_data is not None)
        outer_span.set_attribute("input.strategy", response.period_strategy or "")
        if response.data:
            outer_span.set_attribute("input.sample_row", str(response.data[0])[:500])
        outer_span.set_attribute("input.value", json.dumps({"data": response.data[:100] if response.data else [], "strategy": response.period_strategy, "comparison_data": response.comparison_data[:100] if response.comparison_data else []}, default=str))
        try:
            intent = response.validated_intent

            with tracer.start_as_current_span("insights.engine") as engine_span:
                logger.info("Step 7a: Generating insights...")
                insight_result = generate_insights(
                    data=response.data or [],
                    intent=intent,
                    previous_qco=previous_qco,
                    strategy=response.period_strategy,
                    comparison_data=response.comparison_data,
                )
                response.insights = insight_result
                response.stage = PipelineStage.INSIGHTS_GENERATED
                try:
                    engine_span.set_attribute("output.insight_count", len(insight_result.insights))
                    engine_span.set_attribute("output.total_value", str(insight_result.total_value or ""))
                    engine_span.set_attribute("output.total_formatted", insight_result.total_formatted or "")
                    engine_span.set_attribute("output.intent_type", insight_result.intent_type or "")
                    if insight_result.primary_insight:
                        engine_span.set_attribute("output.primary_insight_label", insight_result.primary_insight.label)
                        engine_span.set_attribute("output.primary_insight_headline", insight_result.primary_insight.headline)
                    all_labels = [i.label for i in insight_result.insights]
                    engine_span.set_attribute("output.insight_labels", str(all_labels)[:500])
                    engine_span.set_attribute("output.value", json.dumps(getattr(insight_result, "model_dump", lambda: str(insight_result))(), default=str))
                except Exception as _log_err:
                    logger.debug(f"Non-fatal span logging error in insights.engine: {_log_err}")
                logger.info(f"Insights generated: {len(insight_result.insights)} insights")

            with tracer.start_as_current_span("insights.refine") as refine_span:
                refine_span.set_attribute("input.insight_count", len(insight_result.insights))
                refine_span.set_attribute("input.query", response.query[:500])
                refine_span.set_attribute("input.value", json.dumps({"query": response.query, "insights": getattr(insight_result, "model_dump", lambda: str(insight_result))()}, default=str))
                logger.info("Step 7b: Refining insights with LLM...")
                try:
                    refined_insight_result = refine_insights(
                        insight_result=insight_result,
                        data=response.data or [],
                        query=response.query,
                        previous_qco=previous_qco,
                    )
                    response.refined_insights = refined_insight_result
                    response.stage = PipelineStage.INSIGHTS_REFINED
                    try:
                        refine_span.set_attribute("output.refined_count", len(refined_insight_result.insights))
                        refine_span.set_attribute("output.executive_summary", refined_insight_result.executive_summary or "")
                        refine_span.set_attribute("output.key_risks", str(refined_insight_result.key_risks)[:500])
                        refine_span.set_attribute("output.recommendations", str(refined_insight_result.recommendations)[:500])
                        refine_span.set_attribute("output.value", json.dumps(getattr(refined_insight_result, "model_dump", lambda: str(refined_insight_result))(), default=str))
                    except Exception as _log_err:
                        logger.debug(f"Non-fatal span logging error in insights.refine: {_log_err}")
                    logger.info(f"Insights refined: {len(refined_insight_result.insights)} insights")
                except Exception as e:
                    refine_span.set_status(Status(StatusCode.ERROR, str(e)))
                    refine_span.record_exception(e)
                    refine_span.set_attribute("error.message", str(e))
                    logger.warning(f"Insight refinement failed (non-fatal): {e}, using original insights")
                    response.refined_insights = None

            with tracer.start_as_current_span("visual_spec") as spec_span:
                logger.info("Step 7c: Generating visual spec...")
                insights_for_spec = response.refined_insights or insight_result
                visual_spec = generate_visual_spec(
                    data=response.data or [],
                    insights=insights_for_spec,
                    chart_type_hint=None,
                    query=response.query,
                    comparison_data=response.comparison_data,
                    strategy=response.period_strategy,
                    intent=response.validated_intent,
                )
                response.visual_spec = visual_spec
                response.stage = PipelineStage.VISUAL_SPEC_GENERATED
                spec_span.set_attribute("output.chart_type", visual_spec.chart_type or "")
                spec_span.set_attribute("output.annotations_count", len(visual_spec.annotations))
                spec_span.set_attribute("output.markers_count", len(visual_spec.markers))
                spec_span.set_attribute("output.title", getattr(visual_spec, "title", "") or "")
                spec_span.set_attribute("output.value", json.dumps(getattr(visual_spec, "model_dump", lambda: str(visual_spec))(), default=str))
                logger.info(f"Visual spec generated: chart_type={visual_spec.chart_type}")

        except InsightEngineError as e:
            logger.error(f"Insight/Spec generation error: {e}")
            outer_span.set_status(Status(StatusCode.ERROR, str(e)))
            outer_span.record_exception(e)
            outer_span.set_attribute("error.type", e.__class__.__name__)
            outer_span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=PipelineStage.CUBE_EXECUTED,
                error_type=e.__class__.__name__,
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)

        except Exception as e:
            outer_span.set_status(Status(StatusCode.ERROR, str(e)))
            outer_span.record_exception(e)
            outer_span.set_attribute("error.message", str(e))
            logger.warning(f"Insight/Spec generation failed (non-fatal): {e}")

        outer_span.set_attribute("output.value", json.dumps({
            "insights": getattr(response.refined_insights or response.insights, "model_dump", lambda: str(response.refined_insights or response.insights))() if hasattr(response, "insights") else None,
            "visual_spec": getattr(response.visual_spec, "model_dump", lambda: str(response.visual_spec))() if hasattr(response, "visual_spec") and response.visual_spec else None
        }, default=str))

        return response


def _complete_pipeline(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    try:
        logger.info("Step 6: Completing pipeline...")
        response.success = True
        response.stage = PipelineStage.COMPLETED
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(f"Pipeline completed in {response.duration_ms}ms")
        
    except Exception as e:
        # Pipeline completion error - STOP
        logger.error(f"Pipeline completion error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.VISUALIZATION_GENERATED,
            error_type="PipelineCompletionError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response

    return response


def execute_retry_query(
    original_request_id: str,
    modified_query: str,
    session_id: str,
    original_query: str
) -> OrchestratorResponse:
    """
    Execute a retry query with full pipeline processing while maintaining session context.

    This function:
    1. Logs the retry attempt for RLHF analysis
    2. Loads existing session context (QCO) for conversational continuity
    3. Executes the modified query through the complete pipeline
    4. Maintains session state for future follow-ups

    Args:
        original_request_id: The request ID of the original query being retried
        modified_query: The user's modified query text
        session_id: Session ID for context continuity
        original_query: Original query for comparison and logging

    Returns:
        OrchestratorResponse with complete pipeline results
    """
    start_time = time.monotonic()
    request_id = f"retry_{uuid.uuid4().hex[:12]}"

    logger.info(f"Starting retry pipeline: retry_id={request_id}, original_id={original_request_id}, session={session_id}")

    with tracer.start_as_current_span("pipeline.retry") as span:
        span.set_attribute("pipeline.type", "retry")
        span.set_attribute("input.original_request_id", original_request_id)
        span.set_attribute("input.retry_request_id", request_id)
        span.set_attribute("input.modified_query", modified_query[:500])
        span.set_attribute("input.session_id", session_id)
        span.set_attribute("input.original_query", original_query[:500])

        # Initialize response
        response = OrchestratorResponse(
            query=modified_query,
            session_id=session_id,
            success=False,
            stage=PipelineStage.RECEIVED
        )
        response.request_id = request_id
        response.original_query = original_query  # Store the original query for frontend

        try:
            # Log the retry attempt for RLHF analysis
            from app.rlhf.feedback_service import log_retry
            retry_log_id = log_retry(
                original_request_id=original_request_id,
                retry_request_id=request_id,
                original_query=original_query,
                modified_query=modified_query,
                session_id=session_id
            )
            span.set_attribute("retry.log_id", retry_log_id)
            logger.info(f"Retry logged with ID: {retry_log_id}")

            # Load existing QCO for context continuity
            previous_qco = None
            try:
                previous_qco = load_qco(session_id)
                response.stage = PipelineStage.QCO_LOADED
                span.set_attribute("context.has_previous_qco", True)
                if previous_qco:
                    span.set_attribute("context.previous_metric", previous_qco.metric or "")
                    span.set_attribute("context.previous_scope", previous_qco.sales_scope or "")
                logger.info(f"Loaded previous QCO for session: {session_id}")
            except Exception as e:
                logger.info(f"No previous QCO found for session {session_id}: {e}")
                span.set_attribute("context.has_previous_qco", False)

            # Extract intent with context
            response = _extract_intent(response, start_time, previous_qco=previous_qco, skip_reset_overrides=False)
            if response.error:
                response.duration_ms = int((time.monotonic() - start_time) * 1000)
                return response

            # Merge intent with previous context if available
            if previous_qco and response.raw_intent:
                with tracer.start_as_current_span("intent.merge") as merge_span:
                    merge_span.set_attribute("input.raw_intent", str(response.raw_intent)[:1000])
                    merge_span.set_attribute("input.qco_metric", previous_qco.metric or "")
                    merge_span.set_attribute("input.value", json.dumps({"raw_intent": response.raw_intent, "previous_qco": str(previous_qco)}, default=str))
                    response.merged_intent = merge_intent(response.raw_intent, previous_qco)
                    response.stage = PipelineStage.INTENT_MERGED
                    merge_span.set_attribute("output.merged_with_qco", True)
                    merge_span.set_attribute("output.merged_intent", str(response.merged_intent)[:1000])
                    merge_span.set_attribute("output.value", json.dumps(response.merged_intent, default=str))
                    logger.info(f"Intent merged with previous QCO for retry")
            else:
                response.merged_intent = response.raw_intent
                if response.raw_intent:
                    response.stage = PipelineStage.INTENT_MERGED

            # Validate intent
            response = _validate_intent(response, start_time)
            if response.error:
                response.duration_ms = int((time.monotonic() - start_time) * 1000)
                return response

            # Build Cube query
            response = _build_cube_query(response, start_time)
            if response.error:
                response.duration_ms = int((time.monotonic() - start_time) * 1000)
                return response

            # Execute Cube query
            response = _execute_cube_query(response, start_time)
            if response.error:
                response.duration_ms = int((time.monotonic() - start_time) * 1000)
                return response

            # Generate insights and visual spec
            response = _generate_insights_and_spec(response, start_time, previous_qco=previous_qco)
            if response.error:
                response.duration_ms = int((time.monotonic() - start_time) * 1000)
                return response

            # Save updated QCO for future queries in this session
            if response.validated_intent:
                try:
                    qco = resolve_qco(response.validated_intent, modified_query)
                    save_qco(session_id, qco)
                    response.stage = PipelineStage.QCO_RESOLVED
                    span.set_attribute("context.qco_saved", True)
                    logger.info(f"Updated QCO saved for session: {session_id}")
                except Exception as e:
                    logger.warning(f"Failed to save updated QCO: {e}")
                    span.set_attribute("context.qco_saved", False)

            # Complete pipeline
            response = _complete_pipeline(response, start_time)

            span.set_attribute("output.success", True)
            span.set_attribute("output.duration_ms", response.duration_ms)
            span.set_attribute("output.row_count", len(response.data or []))
            if response.visual_spec:
                span.set_attribute("output.chart_type", response.visual_spec.chart_type or "")

            logger.info(f"Retry pipeline completed successfully in {response.duration_ms}ms")
            return response

        except IntentValidationError as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", "IntentValidationError")
            span.set_attribute("error.message", str(e))
            response.error = OrchestratorError(
                stage=response.stage,
                error_type=e.__class__.__name__,
                message=str(e),
                details=e.to_dict() if hasattr(e, "to_dict") else None
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.set_attribute("error.type", e.__class__.__name__)
            span.set_attribute("error.message", str(e))
            logger.error(f"Retry pipeline error: {e}")
            response.error = OrchestratorError(
                stage=response.stage,
                error_type=e.__class__.__name__,
                message=str(e),
            )
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response