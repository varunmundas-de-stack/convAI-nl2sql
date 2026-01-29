"""
Query Orchestrator - Traffic control for the NL2SQL pipeline.

This module is the COORDINATOR between components.
It is NOT intelligent - it is TRAFFIC CONTROL.

RESPONSIBILITIES:
1. Receive query (no preprocessing, no cleanup)
2. Call Intent Extractor (stop if LLM fails or JSON malformed)
3. Validate Intent (stop if validation fails)
4. Build Cube Query (stop if mapping fails)
5. Execute Cube Query (stop if Cube errors)
6. Return structured response (everything for debugging)

DESIGN PRINCIPLES:
- Zero analytics
- Zero guessing  
- Zero fixing
- Stop the pipeline if ANYTHING is wrong
- Return EVERYTHING transparently (debuggable, auditable, demo-friendly)

This module does NOT:
- Preprocess or clean queries
- Retry with modified prompts
- Auto-fix validation errors
- Infer missing fields
- Mask internal errors

Every failure is VISIBLE and EXPLICIT.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

from app.services.intent_extractor import (
    extract_intent,
    ExtractionError,
    LLMCallError,
    LLMTimeoutError,
    JSONParseError,
)
from app.services.intent_validator import validate_intent
from app.services.intent_errors import IntentValidationError
from app.services.cube_query_builder import build_cube_query
from app.services.cube_client import (
    CubeClient,
    CubeClientError,
    CubeResponse,
)
from app.services.catalog_manager import CatalogManager
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
    INTENT_VALIDATED = "intent_validated"
    CUBE_QUERY_BUILT = "cube_query_built"
    CUBE_EXECUTED = "cube_executed"
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
    validated_intent: Optional[Dict[str, Any]] = None
    cube_query: Optional[Dict[str, Any]] = None
    data: Optional[List[Dict[str, Any]]] = None
    
    # Error (None if success)
    error: Optional[OrchestratorError] = None
    
    # Metadata
    request_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "query": self.query,
            "success": self.success,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "raw_intent": self.raw_intent,
            "validated_intent": self.validated_intent,
            "cube_query": self.cube_query,
            "data": self.data,
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
    
    Any failure STOPS the pipeline immediately.
    No retries. No fixes. Just fail and report.
    
    Args:
        query: Natural language query string (passed as-is, no cleanup)
        
    Returns:
        OrchestratorResponse with all intermediate outputs and any error
        
    Example:
        >>> response = execute_query("What is the total sales this month?")
        >>> if response.success:
        ...     print(response.data)
        ... else:
        ...     print(response.error.message)
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
    # STEP 1: Receive the query
    # -------------------------------------------------------------------------
    # No preprocessing. No cleanup. No spell correction.
    # The query is used exactly as received.
    
    # -------------------------------------------------------------------------
    # STEP 2: Extract intent (LLM call)
    # -------------------------------------------------------------------------
    try:
        logger.info("Step 2: Extracting intent...")
        raw_intent = extract_intent(query)
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
            details={"raw_response": getattr(e, '__cause__', None)}
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
    
    # -------------------------------------------------------------------------
    # STEP 3: Validate intent
    # -------------------------------------------------------------------------
    try:
        logger.info("Step 3: Validating intent...")
        catalog = _get_catalog()
        validated_intent = validate_intent(raw_intent, catalog)
        response.validated_intent = validated_intent.model_dump()
        response.stage = PipelineStage.INTENT_VALIDATED
        logger.info(f"Intent validated: {validated_intent.intent_type}")
        
    except IntentValidationError as e:
        # Validation failed - STOP
        logger.error(f"Validation error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.INTENT_EXTRACTED,
            error_type=e.__class__.__name__,
            error_code=e.ERROR_CODE.value if e.ERROR_CODE else None,
            message=str(e),
            details=e.to_dict()
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
        
    except Exception as e:
        # Unexpected validation error - STOP
        logger.error(f"Unexpected validation error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.INTENT_EXTRACTED,
            error_type=type(e).__name__,
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    # -------------------------------------------------------------------------
    # STEP 4: Build Cube query
    # -------------------------------------------------------------------------
    try:
        logger.info("Step 4: Building Cube query...")
        cube_query = build_cube_query(validated_intent)
        response.cube_query = cube_query
        response.stage = PipelineStage.CUBE_QUERY_BUILT
        logger.info(f"Cube query built: {cube_query}")
        
    except KeyError as e:
        # Missing mapping - STOP
        logger.error(f"Cube query mapping error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.INTENT_VALIDATED,
            error_type="CubeQueryMappingError",
            message=f"Failed to map intent to Cube query: missing mapping for {e}",
            details={"missing_key": str(e)}
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
        
    except Exception as e:
        # Unexpected build error - STOP
        logger.error(f"Cube query build error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.INTENT_VALIDATED,
            error_type="CubeQueryBuildError",
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    # -------------------------------------------------------------------------
    # STEP 5: Execute Cube query
    # -------------------------------------------------------------------------
    try:
        logger.info("Step 5: Executing Cube query...")
        cube_client = CubeClient()
        cube_response = cube_client.load(cube_query)
        response.data = cube_response.data
        response.request_id = cube_response.request_id
        response.stage = PipelineStage.CUBE_EXECUTED
        logger.info(f"Cube query executed: {len(cube_response.data)} rows returned")
        
    except CubeClientError as e:
        # Cube execution error - STOP
        logger.error(f"Cube error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_QUERY_BUILT,
            error_type=e.__class__.__name__,
            message=str(e),
            details={
                "status_code": getattr(e, 'status_code', None),
                "response_body": getattr(e, 'response_body', None),
            }
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
        
    except Exception as e:
        # Unexpected Cube error - STOP
        logger.error(f"Unexpected Cube error: {e}")
        response.error = OrchestratorError(
            stage=PipelineStage.CUBE_QUERY_BUILT,
            error_type=type(e).__name__,
            message=str(e),
        )
        response.duration_ms = int((time.monotonic() - start_time) * 1000)
        return response
    
    # -------------------------------------------------------------------------
    # STEP 6: Success - return everything
    # -------------------------------------------------------------------------
    response.success = True
    response.stage = PipelineStage.COMPLETED
    response.duration_ms = int((time.monotonic() - start_time) * 1000)
    
    logger.info(
        f"Pipeline completed successfully in {response.duration_ms}ms: "
        f"{len(response.data)} rows"
    )
    
    return response


# =============================================================================
# CONVENIENCE FUNCTION FOR API
# =============================================================================

def execute_query_dict(query: str) -> Dict[str, Any]:
    """
    Execute a query and return a dict (for API responses).
    
    Same as execute_query but returns a dict instead of dataclass.
    
    Args:
        query: Natural language query string
        
    Returns:
        Dict with all pipeline outputs (JSON-serializable)
    """
    response = execute_query(query)
    return response.to_dict()
