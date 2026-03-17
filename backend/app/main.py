"""
NL2SQL FastAPI Application - Natural Language to SQL Query Interface.

This is the main entry point for the NL2SQL API.
It delegates query execution to the QueryOrchestrator.

DESIGN PRINCIPLE:
- main.py is a THIN HTTP LAYER
- All business logic lives in query_orchestrator
- main.py only handles: HTTP concerns, request validation, response formatting
"""

import logging
import colorlog
import os
import uuid
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from opentelemetry.trace import Status, StatusCode

from app.services.query_orchestrator import execute_query as run_pipeline, resume_query, execute_retry_query, PipelineStage
from app.services.catalog_manager import CatalogManager
from app.utils.tracer import get_tracer

# Module-level tracer (provider is set up by llm_service on first import)
tracer = get_tracer(__name__)

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

CATALOG_PATH = Path(__file__).parent.parent / "catalog" / "catalog.yaml"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Configure logging

def setup_global_color_logging():
    # Configure root logger
    logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper()))
    root_logger = logging.getLogger()

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(name)s: %(message)s",
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red',
        }
    ))
    root_logger.addHandler(handler)

setup_global_color_logging()
logger = logging.getLogger(__name__)


# =============================================================================
# APPLICATION STATE
# =============================================================================

class AppState:
    """Application state container for dependencies."""
    catalog: CatalogManager


app_state = AppState()


# =============================================================================
# LIFESPAN (Startup/Shutdown)
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    # Startup
    logger.info("Starting NL2SQL API...")
    
    # Load catalog (for catalog endpoints)
    logger.info(f"Loading catalog from: {CATALOG_PATH}")
    app_state.catalog = CatalogManager(str(CATALOG_PATH))
    
    # Initialize RLHF database and register v1
    try:
        from app.rlhf.db import init_db
        from app.rlhf.prompt_manager import ensure_v1_registered
        init_db()
        ensure_v1_registered()
        logger.info("RLHF subsystem initialized")
    except Exception as e:
        logger.warning(f"RLHF initialization failed (non-fatal): {e}")
    
    logger.info("NL2SQL API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down NL2SQL API...")


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="NL2SQL API",
    description="Natural Language to SQL Query Interface for FMCG Sales Analytics",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount RLHF router
try:
    from app.rlhf.router import router as rlhf_router
    app.include_router(rlhf_router, prefix="/rlhf")
except Exception as e:
    logger.warning(f"RLHF router mount failed (non-fatal): {e}")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class QueryRequest(BaseModel):
    """Request model for natural language query."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language query",
        json_schema_extra={"example": "Show me total sales by region for last 30 days"}
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session ID for conversational context. Enables follow-up queries.",
        json_schema_extra={"example": "sess_abc123"}
    )

class ClarificationRequest(BaseModel):
    request_id: str
    answers: dict[str, Any]
    session_id: str | None = None

class RetryRequest(BaseModel):
    """Request model for retrying a query with modifications."""
    original_request_id: str = Field(
        ...,
        description="Request ID of the original query being retried",
        json_schema_extra={"example": "req_abc123"}
    )
    modified_query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Modified query to retry with",
        json_schema_extra={"example": "Show me total sales by region for last 60 days"}
    )
    session_id: str = Field(
        ...,
        description="Session ID to maintain conversational context",
        json_schema_extra={"example": "sess_abc123"}
    )
    original_query: str = Field(
        ...,
        description="Original query for comparison and logging",
        json_schema_extra={"example": "Show me total sales by region for last 30 days"}
    )

# =============================================================================
# HELPER: MAP PIPELINE STAGE TO HTTP STATUS
# =============================================================================

def _get_http_status_for_stage(stage: str, error_type: str) -> int:
    """
    Map pipeline failure stage to appropriate HTTP status code.
    
    - Extraction/Validation failures -> 400 (client error, bad query)
    - Cube connection issues -> 502 (bad gateway)
    - Cube timeout -> 504 (gateway timeout)
    - Cube unavailable -> 503 (service unavailable)
    """
    # Cube-related errors
    if "Timeout" in error_type:
        return status.HTTP_504_GATEWAY_TIMEOUT
    if "ServiceUnavailable" in error_type:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if "Connection" in error_type or stage == PipelineStage.CUBE_QUERY_BUILT:
        return status.HTTP_502_BAD_GATEWAY
    
    # Intent/Validation errors are client errors
    return status.HTTP_400_BAD_REQUEST


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "nl2sql-api"}


@app.post(
    "/query",
    tags=["Query"],
    summary="Execute natural language query",
    description="Process a natural language query and return analytics results from Cube.js",
)
async def execute_query(request: QueryRequest):
    """
    Execute a natural language query against the analytics system.
    
    Delegates all processing to the QueryOrchestrator.
    Returns the complete pipeline response (success or failure).
    """
    query = request.query.strip()
    # Auto-generate session_id if not provided (enables context for follow-ups)
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    logger.info(f"Received query: {query} (session={session_id}, new={request.session_id is None})")

    with tracer.start_as_current_span("http.query") as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/query")
        span.set_attribute("input.query", query[:500])
        span.set_attribute("input.value", json.dumps({"query": query, "session_id": session_id}))
        span.set_attribute("input.session_id", session_id)
        span.set_attribute("input.session_is_new", request.session_id is None)

        # Delegate to orchestrator (does ALL the work)
        response = run_pipeline(query, session_id=session_id)

        # Convert to dict for JSON response
        response_dict = response.to_dict()

        # Check for clarification request - this is NOT an error, return 200
        if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
            logger.info(f"Clarification requested: {response.missing_fields}")
            span.set_attribute("output.clarification_requested", True)
            span.set_attribute("output.missing_fields", str(response.missing_fields or []))
            span.set_attribute("output.clarification_message", response.clarification_message or "")
            span.set_attribute("output.value", json.dumps(response_dict, default=str))
            return JSONResponse(content=response_dict, status_code=status.HTTP_200_OK)

        if not response.success:
            # Pipeline failed - return error with appropriate HTTP status
            error_type = response.error.error_type if response.error else "UnknownError"
            stage = response.stage  # Use the actual stage from response, not from error
            http_status = _get_http_status_for_stage(stage, error_type)

            logger.warning(f"Pipeline failed at stage '{stage}': {error_type}")
            span.set_status(Status(StatusCode.ERROR, error_type))
            span.set_attribute("error.type", error_type)
            span.set_attribute("error.stage", stage)
            span.set_attribute("http.status_code", http_status)
            span.set_attribute("output.value", json.dumps(response_dict, default=str))

            # Convert the error object to a string or dict
            if "error" in response_dict and isinstance(response_dict["error"], Exception):
                response_dict["error"] = str(response_dict["error"]) 

            raise HTTPException(status_code=http_status, detail=response_dict)

        if response.error:
            span.set_status(Status(StatusCode.ERROR, "LLM temporarily unavailable"))
            span.set_attribute("http.status_code", 503)
            raise HTTPException(
                status_code=503,
                detail="LLM temporarily unavailable"
            )

        logger.info(f"Query executed successfully in {response.duration_ms}ms, {len(response.data or [])} rows")
        span.set_attribute("output.success", True)
        span.set_attribute("output.duration_ms", response.duration_ms)
        span.set_attribute("output.row_count", len(response.data or []))
        if response.visual_spec:
            span.set_attribute("output.chart_type", response.visual_spec.chart_type or "")
        span.set_attribute("http.status_code", 200)
        span.set_attribute("output.value", json.dumps(response_dict, default=str))

        # Success - return full response
        return JSONResponse(content=response_dict)


@app.get("/catalog/metrics", tags=["Catalog"])
async def list_metrics():
    """List all available metrics."""
    metrics = app_state.catalog.list_metrics()
    return {
        "metrics": [
            {
                "name": m.get("name"),
                "display_name": m.get("display_name"),
                "description": m.get("description"),
            }
            for m in metrics
        ]
    }


@app.get("/catalog/dimensions", tags=["Catalog"])
async def list_dimensions():
    """List all available dimensions."""
    dimensions = app_state.catalog.list_dimensions()
    return {
        "dimensions": [
            {
                "name": d.get("name"),
                "display_name": d.get("display_name"),
                "description": d.get("description"),
                "groupable": d.get("groupable", True),
                "filterable": d.get("filterable", True),
            }
            for d in dimensions
        ]
    }


@app.get("/catalog/time-windows", tags=["Catalog"])
async def list_time_windows():
    """List all available time windows."""
    windows = app_state.catalog.list_time_windows()
    return {
        "time_windows": [
            {
                "name": w.get("name"),
                "display_name": w.get("display_name"),
                "description": w.get("description"),
            }
            for w in windows
        ]
    }

@app.post("/clarify", tags=["Query"], summary="Submit clarification answers")
async def clarify_endpoint(req: ClarificationRequest):
    """
    Resume a paused pipeline by supplying answers to a clarification request.

    Returns the same response shape as /query.
    """
    with tracer.start_as_current_span("http.clarify") as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/clarify")
        span.set_attribute("input.request_id", req.request_id)
        span.set_attribute("input.session_id", req.session_id or "")
        span.set_attribute("input.answer_keys", str(list(req.answers.keys())))
        span.set_attribute("input.answers", str(req.answers)[:500])
        span.set_attribute("input.value", json.dumps(req.answers, default=str))

        response_dict = resume_query(req.request_id, req.answers, session_id=req.session_id)

        # Clarification requested again — not an error, return 200
        if response_dict.get("stage") == PipelineStage.CLARIFICATION_REQUESTED:
            span.set_attribute("output.clarification_requested_again", True)
            span.set_attribute("output.value", json.dumps(response_dict, default=str))
            return JSONResponse(content=response_dict, status_code=status.HTTP_200_OK)

        # State not found — treat as a client error (bad/expired request_id)
        if (
            not response_dict.get("success")
            and response_dict.get("error", {}).get("error_type") == "PipelineStateNotFound"
        ):
            span.set_status(Status(StatusCode.ERROR, "PipelineStateNotFound"))
            span.set_attribute("http.status_code", 404)
            span.set_attribute("output.value", json.dumps(response_dict, default=str))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=response_dict,
            )

        if not response_dict.get("success"):
            error_type = response_dict.get("error", {}).get("error_type", "UnknownError")
            stage = response_dict.get("stage", "")
            http_status = _get_http_status_for_stage(stage, error_type)
            logger.warning(f"Clarify pipeline failed at stage '{stage}': {error_type}")
            span.set_status(Status(StatusCode.ERROR, error_type))
            span.set_attribute("error.type", error_type)
            span.set_attribute("error.stage", stage)
            span.set_attribute("http.status_code", http_status)
            span.set_attribute("output.value", json.dumps(response_dict, default=str))
            raise HTTPException(status_code=http_status, detail=response_dict)

        span.set_attribute("output.success", True)
        span.set_attribute("output.row_count", len(response_dict.get("data") or []))
        span.set_attribute("http.status_code", 200)
        span.set_attribute("output.value", json.dumps(response_dict, default=str))
        return JSONResponse(content=response_dict, status_code=status.HTTP_200_OK)


@app.post(
    "/retry",
    tags=["Query"],
    summary="Retry query with modifications",
    description="Retry a previous query with modifications while maintaining session context",
)
async def retry_query_endpoint(request: RetryRequest):
    """
    Retry a previous query with modifications while maintaining conversational context.

    This endpoint allows users to refine their queries based on previous responses.
    The retry is logged for RLHF analysis and the full pipeline is executed with the modified query.
    """
    logger.info(f"Received retry: {request.modified_query} (session={request.session_id}, original_id={request.original_request_id})")

    with tracer.start_as_current_span("http.retry") as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/retry")
        span.set_attribute("input.original_request_id", request.original_request_id)
        span.set_attribute("input.modified_query", request.modified_query[:500])
        span.set_attribute("input.session_id", request.session_id)
        span.set_attribute("input.original_query", request.original_query[:500])
        span.set_attribute("input.value", json.dumps({
            "original_request_id": request.original_request_id,
            "modified_query": request.modified_query,
            "session_id": request.session_id,
            "original_query": request.original_query
        }))

        # Delegate to orchestrator (handles all retry logic)
        response = execute_retry_query(
            original_request_id=request.original_request_id,
            modified_query=request.modified_query,
            session_id=request.session_id,
            original_query=request.original_query
        )

        # Convert to dict for JSON response
        response_dict = response.to_dict()

        # Check for clarification request - this is NOT an error, return 200
        if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
            logger.info(f"Retry clarification requested: {response.missing_fields}")
            span.set_attribute("output.clarification_requested", True)
            span.set_attribute("output.missing_fields", str(response.missing_fields or []))
            span.set_attribute("output.clarification_message", response.clarification_message or "")
            span.set_attribute("output.value", json.dumps(response_dict, default=str))
            return JSONResponse(content=response_dict, status_code=status.HTTP_200_OK)

        if not response.success:
            # Pipeline failed - return error with appropriate HTTP status
            error_type = response.error.error_type if response.error else "UnknownError"
            stage = response.stage
            http_status = _get_http_status_for_stage(stage, error_type)

            logger.warning(f"Retry pipeline failed at stage '{stage}': {error_type}")
            span.set_status(Status(StatusCode.ERROR, error_type))
            span.set_attribute("error.type", error_type)
            span.set_attribute("error.stage", stage)
            span.set_attribute("http.status_code", http_status)
            span.set_attribute("output.value", json.dumps(response_dict, default=str))

            # Convert the error object to a string or dict
            if "error" in response_dict and isinstance(response_dict["error"], Exception):
                response_dict["error"] = str(response_dict["error"])

            raise HTTPException(status_code=http_status, detail=response_dict)

        if response.error:
            span.set_status(Status(StatusCode.ERROR, "LLM temporarily unavailable"))
            span.set_attribute("http.status_code", 503)
            raise HTTPException(
                status_code=503,
                detail="LLM temporarily unavailable"
            )

        logger.info(f"Retry executed successfully in {response.duration_ms}ms, {len(response.data or [])} rows")
        span.set_attribute("output.success", True)
        span.set_attribute("output.duration_ms", response.duration_ms)
        span.set_attribute("output.row_count", len(response.data or []))
        if response.visual_spec:
            span.set_attribute("output.chart_type", response.visual_spec.chart_type or "")
        span.set_attribute("http.status_code", 200)
        span.set_attribute("output.value", json.dumps(response_dict, default=str))

        # Success - return full response
        return JSONResponse(content=response_dict)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    uvicorn.run(app, host=host, port=port)
