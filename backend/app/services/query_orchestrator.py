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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path
import uuid
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
    
    
    # Error (None if success)
    error: Optional[OrchestratorError] = None
    
    # Metadata
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    missing_fields: Optional[List[str]] = None
    clarification_message: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "query": self.query,
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

def execute_query(query: str, session_id: Optional[str] = None) -> OrchestratorResponse:
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
    start_time = time.monotonic()
    
    # Initialize response with input
    response = OrchestratorResponse(
        query=query,
        session_id=session_id,
        success=False,
        stage=PipelineStage.RECEIVED,
    )
    
    logger.info(f"Pipeline started: '{query[:100]}...' (session={session_id})")
    
    # -------------------------------------------------------------------------
    # STEP 1: Load previous QCO (non-fatal if missing)
    # -------------------------------------------------------------------------
    previous_qco = None
    if session_id:
        try:
            previous_qco = load_qco(session_id)
            if previous_qco:
                response.previous_qco = previous_qco
                response.stage = PipelineStage.QCO_LOADED
                logger.info(f"Loaded previous QCO for session {session_id}: "
                            f"metric={previous_qco.metric}, scope={previous_qco.sales_scope}")
            else:
                logger.info(f"No previous QCO for session {session_id} (first query)")
        except Exception as e:
            logger.warning(f"Failed to load QCO for session {session_id}: {e}")
    
    # -------------------------------------------------------------------------
    # STEP 2: Extract intent (LLM call, with QCO context)
    # -------------------------------------------------------------------------
    response = _extract_intent(response, start_time, previous_qco=previous_qco)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 2.5: Detect and apply drill-down mutation (before generic merge)
    # -------------------------------------------------------------------------
    drill_result = None
    if previous_qco and response.raw_intent:
        drill_result = detect_drill(response.raw_intent, previous_qco)
        if drill_result.case != "none":
            response.raw_intent = apply_drill_mutation(
                response.raw_intent, previous_qco, drill_result
            )
            logger.info(f"Drill [{drill_result.case}]: "
                        f"{drill_result.prev_dimension} → {drill_result.next_dimension}")
    
    # -------------------------------------------------------------------------
    # STEP 3: Merge intent with previous QCO
    # -------------------------------------------------------------------------
    if previous_qco and response.raw_intent:
        response.merged_intent = merge_intent(response.raw_intent, previous_qco)
        response.stage = PipelineStage.INTENT_MERGED
        logger.info(f"Intent merged with previous QCO")
    else:
        response.merged_intent = response.raw_intent
    
    # -------------------------------------------------------------------------
    # STEP 4: Validate intent (uses merged intent)
    # -------------------------------------------------------------------------
    response = _validate_intent(response, start_time)
    if response.error:
        return response
    if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
        # Save state for later resumption (including session_id)
        state = PipelineState(
            request_id=response.request_id,
            original_query=query,
            intent=response.merged_intent or response.raw_intent,
            missing_fields=response.missing_fields or [],
            session_id=session_id,
        )
        save_state(state)
        logger.info(f"Clarification requested, saved state {response.request_id}")
        return response
    
    # -------------------------------------------------------------------------
    # STEP 5: Build Cube query
    # -------------------------------------------------------------------------
    response = _build_cube_query(response, start_time)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 6: Execute Cube query
    # -------------------------------------------------------------------------
    response = _execute_cube_query(response, start_time)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 7: Generate insights + visual spec
    # -------------------------------------------------------------------------
    response = _generate_insights_and_spec(response, start_time, previous_qco=previous_qco)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 8: Resolve QCO and save for next query
    # -------------------------------------------------------------------------
    if session_id and response.validated_intent:
        try:
            qco = resolve_qco(response.original_intent or response.validated_intent, query)
            save_qco(session_id, qco)
            response.stage = PipelineStage.QCO_RESOLVED
            logger.info(f"QCO resolved and saved for session {session_id}")
        except Exception as e:
            # QCO resolution failure is non-fatal
            logger.warning(f"Failed to resolve/save QCO: {e}")
    
    # -------------------------------------------------------------------------
    # STEP 9: Complete pipeline
    # -------------------------------------------------------------------------
    response = _complete_pipeline(response, start_time)
    
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

    # BUG-01 FIX: do NOT delete state here — delete only after full pipeline success
    response = OrchestratorResponse(
        query=state.original_query,
        success=False,
        stage=PipelineStage.INTENT_EXTRACTED,
        raw_intent=patched_intent,
        merged_intent=merged_intent,
        request_id=request_id,
        session_id=resolved_session_id,
    )

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


def _extract_intent(response: OrchestratorResponse, start_time: float, previous_qco: Optional[QueryContextObject] = None) -> OrchestratorResponse:
    try:
        logger.info("Step 2: Extracting intent...")
        raw_intent = extract_intent(response.query, previous_qco=previous_qco)
        response.raw_intent = raw_intent
        response.stage = PipelineStage.INTENT_EXTRACTED
        logger.info(f"Intent extracted: {raw_intent}")
        
    except JSONParseError as e:
        # LLM returned malformed JSON - STOP
        logger.error(f"JSON parse error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.RECEIVED,
            error_type="JSONParseError",
            message=str(e),
            details={"raw_response": str(getattr(e, '__cause__', None))}
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
        
    except LLMTimeoutError as e:
        # LLM timed out - STOP
        logger.error(f"LLM timeout: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.RECEIVED,
            error_type="LLMTimeoutError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
        
    except LLMCallError as e:
        # LLM API error - STOP
        logger.error(f"LLM call error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.RECEIVED,
            error_type="LLMCallError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response

    except ExtractionError as e:
        # Generic extraction error - STOP
        logger.error(f"Extraction error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.RECEIVED,
            error_type="ExtractionError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    return response

    
def _validate_intent(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    try:
        catalog = _get_catalog()
        logger.info("Step 4: Validating intent...")
        # Use merged_intent if available, otherwise fall back to raw_intent
        intent_to_validate = response.merged_intent or response.raw_intent
        normalized_intent = normalize_intent(intent_to_validate)
        # Fix 2: Keyword-driven trend patcher — runs before validation so the
        # validator sees a correct TREND intent even if the LLM missed granularity.
        normalized_intent = patch_trend_intent(normalized_intent, response.query)
        validated_intent = validate_intent(normalized_intent, catalog, original_query=response.query)
        response.validated_intent = validated_intent
        response.stage = PipelineStage.INTENT_VALIDATED
        logger.info(f"Intent validated: {validated_intent}")
        
    except IntentIncompleteError as e:
        # Incomplete intent - ask for clarification
        logger.warning(f"Incomplete intent: {e}")
        response.clarification = True
        response.missing_fields = e.missing_fields
        response.clarification_message = e.clarification_message
        response.allowed_values = e.allowed_values
        response.stage = PipelineStage.CLARIFICATION_REQUESTED
        response.error = None
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
        
    except IntentValidationError as e:
        # Invalid intent - STOP
        logger.error(f"Intent validation failed: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.INTENT_EXTRACTED,
            error_type="IntentValidationError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    return response


def _build_cube_query(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    try:
        logger.info("Step 5: Building Cube query...")

        # --- Stage 1: determine_strategy ---
        try:
            strategy = determine_strategy(response.validated_intent)
            response.period_strategy = strategy.value
            logger.info(f"Strategy determined: {strategy.value}")
        except Exception as e:
            logger.warning(f"Period strategy determination failed (non-fatal): {e}")
            strategy = QueryStrategy.SINGLE_QUERY
            response.period_strategy = strategy.value

        # --- Stage 2: transform_intent_for_strategy ---
        response.original_intent = response.validated_intent
        transformed_intent = transform_intent_for_strategy(response.validated_intent, strategy)
        # Store back so _execute_cube_query uses the transformed version
        response.validated_intent = transformed_intent

        # --- Stage 3: build_cube_query ---
        cube_query = build_cube_query(transformed_intent)
        response.cube_query = cube_query
        response.stage = PipelineStage.CUBE_QUERY_BUILT
        logger.info(f"Cube query built: {cube_query}")

    except CubeQueryBuildError as e:
        logger.error(f"Cube query build error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.INTENT_VALIDATED,
            error_type="CubeQueryBuildError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response

    return response


def _execute_cube_query(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    """
    Execute Cube HTTP call(s) and store raw results.
    Post-processing math is deferred to generate_insights() in the insight engine.

    Pipeline stages covered here:
        → build_cube_query()  (done in _build_cube_query)
        → execute             (fire 1 or 2 Cube HTTP calls based on strategy)
        → generate_insights() handles post_process_by_strategy internally
    """
    strategy = response.period_strategy or QueryStrategy.SINGLE_QUERY.value
    intent   = response.validated_intent

    try:
        cube_client = CubeClient()

        # Primary query — always
        logger.info(f"Step 4: Executing Cube query (strategy={strategy})...")
        cube_response_a = _cube_load(cube_client, response.cube_query, response, start_time)
        if cube_response_a is None:
            return response
        response.data = cube_response_a.data
        logger.info(f"Primary query executed: {len(response.data)} rows")

        # Secondary query — DUAL_QUERY and CONTRIBUTION strategies
        if strategy == QueryStrategy.DUAL_QUERY.value:
            try:
                comparison_query = build_comparison_query(intent)
                cube_response_b = _cube_load(cube_client, comparison_query, response, start_time)
                if cube_response_b is None:
                    return response
                response.comparison_data = cube_response_b.data
                logger.info(f"Comparison query executed: {len(response.comparison_data)} rows")
            except Exception as e:
                logger.warning(f"Comparison query failed, proceeding without it: {e}")

        elif strategy == QueryStrategy.CONTRIBUTION.value:
            try:
                total_query = build_total_query(intent)
                cube_response_total = _cube_load(cube_client, total_query, response, start_time)
                if cube_response_total is None:
                    return response
                response.comparison_data = cube_response_total.data
                logger.info(f"Total query executed: {len(response.comparison_data)} rows")
            except Exception as e:
                logger.warning(f"Total query failed, proceeding without it: {e}")

        response.stage = PipelineStage.CUBE_EXECUTED

    except CubeQueryExecutionError as e:
        logger.error(f"Cube query execution error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_QUERY_BUILT,
            error_type="CubeQueryExecutionError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response

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
    try:
        logger.info("Step 7a: Generating insights...")
        
        intent = response.validated_intent
        
        pass
        
        # Step 7a: Insight Engine (post-processing + pure math analysis, no LLM)
        insight_result = generate_insights(
            data=response.data or [],
            intent=intent,
            previous_qco=previous_qco,
            strategy=response.period_strategy,
            comparison_data=response.comparison_data,
        )
        response.insights = insight_result
        response.stage = PipelineStage.INSIGHTS_GENERATED
        logger.info(f"Insights generated: {len(insight_result.insights)} insights, "
                     f"primary={insight_result.primary_insight.label if insight_result.primary_insight else 'none'}")
        
        # Step 7b: Insight Refiner (LLM-enhanced interpretation)
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
            logger.info(f"Insights refined: {len(refined_insight_result.insights)} insights, "
                         f"executive_summary={'present' if refined_insight_result.executive_summary else 'none'}")
        except Exception as e:
            # Refinement failure is non-fatal, fall back to original insights
            logger.warning(f"Insight refinement failed (non-fatal): {e}, using original insights")
            response.refined_insights = None
        
        # Step 7c: Visual Spec Generator (declarative spec, no rendering)
        logger.info("Step 7c: Generating visual spec...")
        # Use refined insights if available, otherwise fall back to original
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
        logger.info(f"Visual spec generated: chart_type={visual_spec.chart_type}, "
                     f"{len(visual_spec.annotations)} annotations, {len(visual_spec.markers)} markers")
        
    except InsightEngineError as e:
        logger.error(f"Insight/Spec generation error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_EXECUTED,
            error_type=e.__class__.__name__,
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    except Exception as e:
        # Non-fatal: log but don't kill the pipeline
        logger.warning(f"Insight/Spec generation failed (non-fatal): {e}")
        # Pipeline continues without insights/spec
    
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