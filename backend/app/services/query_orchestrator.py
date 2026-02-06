"""
Query Orchestrator

RESPONSIBILITIES:
1. Receive query (no preprocessing, no cleanup)
2. Call Intent Extractor (stop if LLM fails or JSON malformed)
3. Validate Intent (stop if validation fails)
4. Build Cube Query (stop if mapping fails)
5. Execute Cube Query (stop if Cube errors)
6. Return structured response (everything for debugging)

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
from app.services.cube_query_builder import build_cube_query, CubeQueryBuildError
from app.services.cube_client import (
    CubeClient,
    CubeClientError,
    CubeResponse,
    CubeQueryExecutionError,
    CubeHTTPError,
)
from app.services.intent_normalizer import normalize_intent
from app.services.catalog_manager import CatalogManager
from app.services.data_visualizer import generate_visualization, VisualizationResult, VisualizationGenerationError
from app.pipeline.pipeline_state import PipelineState
from app.pipeline.state_store import save_state, load_state, delete_state, PipelineStateNotFound
from app.models.intent import Intent


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
    INTENT_EXTRACTED = "intent_extracted"
    CLARIFICATION_REQUESTED = "clarification_requested"
    INTENT_VALIDATED = "intent_validated"
    CUBE_QUERY_BUILT = "cube_query_built"
    CUBE_EXECUTED = "cube_executed"
    VISUALIZATION_GENERATED = "visualization_generated"
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
    duration_ms: int = 0               # Total pipeline time
    
    # Step outputs (None if step wasn't reached)
    raw_intent: Optional[Dict[str, Any]] = None
    clarification: Optional[Dict[str, Any]] = None
    validated_intent: Optional[Dict[str, Any]] = None
    cube_query: Optional[Dict[str, Any]] = None
    data: Optional[List[Dict[str, Any]]] = None
    visualization: Optional[Dict[str, Any]] = None
    
    
    # Error (None if success)
    error: Optional[OrchestratorError] = None
    
    # Metadata
    request_id: str = uuid.uuid4().hex
    missing_fields: Optional[List[str]] = None
    clarification_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "query": self.query,
            "success": self.success,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "raw_intent": self.raw_intent,
            "clarification": self.clarification,
            "missing_fields": self.missing_fields,
            "clarification_message": self.clarification_message,
            "validated_intent": (
                self.validated_intent.model_dump()
                if self.validated_intent is not None
                else None
            ),
            "cube_query": self.cube_query,
            "data": self.data,
            "visualization": (
            self.visualization.model_dump()
            if self.visualization else None
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

def execute_query(query: str) -> OrchestratorResponse:
    """
    Execute a natural language query through the complete pipeline.
    
    This is the ONLY public function in this module.
    
    Pipeline steps:
    1. Receive query (no preprocessing)
    2. Extract intent (LLM call)
    3. Validate intent (Pydantic + catalog)
    4. Build Cube query (mechanical translation)
    5. Execute Cube query (HTTP call)
    6. Return structured response
    
    Args:
        query: Natural language query string (passed as-is, no cleanup)
        
    Returns:
        OrchestratorResponse with all intermediate outputs and any error
    """
    start_time = time.monotonic()
    
    # Initialize response with input
    response = OrchestratorResponse(
        query=query,
        success=False,
        stage=PipelineStage.RECEIVED,
    )
    
    logger.info(f"Pipeline started: '{query[:100]}...'")
    
 
    # -------------------------------------------------------------------------
    # STEP 1: Extract intent (LLM call)
    # -------------------------------------------------------------------------
    response = _extract_intent(response, start_time)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 2: Validate intent
    # -------------------------------------------------------------------------
    response = _validate_intent(response, start_time)
    if response.error:
        return response
    if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
        # Save state for later resumption
        state = PipelineState(
            request_id=response.request_id,
            original_query=query,
            intent=response.raw_intent,
            missing_fields=response.missing_fields or [],
        )
        save_state(state)
        logger.info(f"Clarification requested, saved state {response.request_id}")
        return response
    
    # -------------------------------------------------------------------------
    # STEP 3: Build Cube query
    # -------------------------------------------------------------------------
    response = _build_cube_query(response, start_time)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 4: Execute Cube query
    # -------------------------------------------------------------------------
    response = _execute_cube_query(response, start_time)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 5: Generate visualization
    # -------------------------------------------------------------------------
    response = _generate_visualization(response, start_time)
    if response.error:
        return response
    
    # -------------------------------------------------------------------------
    # STEP 6: Complete pipeline
    # -------------------------------------------------------------------------
    response = _complete_pipeline(response, start_time)
    
    return response


# =============================================================================
# PUBLIC API - SIMPLE DICT WRAPPER
# =============================================================================

def execute_query_dict(query: str) -> Dict[str, Any]:
    """
    Execute a query and return a JSON-serializable dict.
    
    This is a convenience wrapper for execute_query() that returns a dict
    instead of an OrchestratorResponse object.
    
    Args:
        query: Natural language query string
        
    Returns:
        Dict with all pipeline outputs (JSON-serializable)
    """
    response = execute_query(query)
    return response.to_dict()


def resume_query(request_id: str, clarification_answers: dict) -> dict:
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
            "error": {
                "error_type": "PipelineStateNotFound",
                "message": "Invalid or expired request_id. Please start a new query.",
                "details": {
                    "request_id": request_id,
                    "hint": "Pipeline state expires after 1 hour or when server restarts"
                }
            }
        }

    # Merge user answers into existing intent
    merged_intent = {
        **state.intent,
        **{k: v for k, v in clarification_answers.items() if k in state.missing_fields}
    }
    logger.info(f"Merged intent: {merged_intent}")
    delete_state(request_id)
    response = OrchestratorResponse(
        query=state.original_query,
        success=False,
        stage=PipelineStage.INTENT_EXTRACTED,
        raw_intent=merged_intent,
        request_id=request_id,
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

        response = _generate_visualization(response, start_time)
        if response.error:
            response.duration_ms = int((time.monotonic() - start_time) * 1000)
            return response.to_dict()

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


def _extract_intent(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    try:
        logger.info("Step 1: Extracting intent...")
        raw_intent = extract_intent(response.query)
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
        logger.info("Step 2: Validating intent...")
        normalized_intent = normalize_intent(response.raw_intent)
        validated_intent = validate_intent(normalized_intent, catalog)
        response.validated_intent = validated_intent
        response.stage = PipelineStage.INTENT_VALIDATED
        logger.info(f"Intent validated: {validated_intent}")
        
    except IntentIncompleteError as e:
        # Incomplete intent - ask for clarification
        logger.warning(f"Incomplete intent: {e}")
        response.clarification = True
        response.missing_fields = e.missing_fields
        response.clarification_message = e.clarification_message
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
        logger.info("Step 3: Building Cube query...")
        cube_query = build_cube_query(response.validated_intent)
        response.cube_query = cube_query
        response.stage = PipelineStage.CUBE_QUERY_BUILT
        logger.info(f"Cube query built: {cube_query}")
        
    except CubeQueryBuildError as e:
        # Cube query build error - STOP
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
    try:
        logger.info("Step 4: Executing Cube query...")
        cube_client = CubeClient()
        try:
            cube_response = cube_client.load(response.cube_query)
            response.data = cube_response.data
        except CubeHTTPError as e:
            response.error = OrchestratorError(
                stage=PipelineStage.CUBE_QUERY_BUILT,
                error_type="CubeHTTPError",
                message="Cube query failed",
                details=e.to_dict() if hasattr(e, "to_dict") else None
            )
            response.success = False
            return response

        response.stage = PipelineStage.CUBE_EXECUTED
        logger.info(f"Cube query executed, rows: {len(cube_response.data)}")
        
    except CubeQueryExecutionError as e:
        # Cube query execution error - STOP
        logger.error(f"Cube query execution error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_QUERY_BUILT,
            error_type="CubeQueryExecutionError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    return response


def _generate_visualization(response: OrchestratorResponse, start_time: float) -> OrchestratorResponse:
    try:
        logger.info("Step 5: Generating visualization...")
        
        # Extract visualization parameters from intent
        # Handle both Pydantic models and dicts
        intent = response.validated_intent
        if intent is None:
            intent_dict = {}
        elif hasattr(intent, 'model_dump'):
            intent_dict = intent.model_dump()
        else:
            intent_dict = intent
        
        visualization_type = intent_dict.get("visualization_type", "table") or "table"
        metric = intent_dict.get("metric")
        dimensions = intent_dict.get("group_by", []) or []
        
        visualization = generate_visualization(
            visualization_type=visualization_type,
            data=response.data,
            metric=metric,
            dimensions=dimensions,
            query=response.query,
        )
        response.visualization = visualization
        response.stage = PipelineStage.VISUALIZATION_GENERATED
        logger.info(f"Visualization generated: {visualization_type}")
        
    except VisualizationGenerationError as e:
        # Visualization generation error - STOP
        logger.error(f"Visualization generation error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_EXECUTED,
            error_type="VisualizationGenerationError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
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