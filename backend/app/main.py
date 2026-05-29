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
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from opentelemetry.trace import Status, StatusCode

from app.services.query_orchestrator import execute_query as run_pipeline, resume_query, execute_retry_query, Stage
from app.services.helpers.catalog_manager import CatalogManager
from app.utils.tracer import get_tracer
from app.security.auth import create_cube_token, get_current_user
from app.security.context import UserContext, current_cube_token, current_user
from app.security.metadata_store import log_audit, save_chat_message

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

    # Initialize user memory SQLite DB
    try:
        from app.services.memory_manager import init_memory_db
        init_memory_db()
        logger.info("User memory DB initialized")
    except Exception as e:
        logger.warning(f"Memory DB initialization failed (non-fatal): {e}")

    # Warm up Tier-1 golden cache (FAISS index built from golden_qa.json)
    try:
        from app.services.cache_manager import golden_cache
        golden_cache.load()
        logger.info("Tier-1 golden cache loaded")
    except Exception as e:
        logger.warning(f"Golden cache initialization failed (non-fatal): {e}")

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
    app.include_router(rlhf_router, prefix="/rlhf", dependencies=[Depends(get_current_user)])
except Exception as e:
    logger.warning(f"RLHF router mount failed (non-fatal): {e}")

try:
    from app.security.router import router as auth_router
    app.include_router(auth_router)
except Exception as e:
    logger.warning(f"Auth router mount failed: {e}")

try:
    from app.chat_router import router as chat_router
    app.include_router(chat_router)
except Exception as e:
    logger.warning(f"Chat router mount failed: {e}")

try:
    from app.insights_router import router as insights_router
    app.include_router(insights_router)
except Exception as e:
    logger.warning(f"Insights router mount failed: {e}")

try:
    from app.questions_router import router as questions_router
    app.include_router(questions_router)
except Exception as e:
    logger.warning(f"Questions router mount failed (non-fatal): {e}")

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
    clarification_answers: dict[str, Any] | None = Field(
        default=None,
        description="Answers to clarification questions from a previous response.",
        json_schema_extra={"example": {"time_period": "last 30 days", "region": "North"}}
    )

class ClarificationRequest(BaseModel):
    request_id: str | None = None
    answers: dict[str, Any] | None = None
    session_id: str | None = None
    compound_state: dict[str, Any] | None = None
    clarification_answer: str | None = None

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

def _set_user_context(user: UserContext):
    user_token = current_user.set(user)
    cube_token = current_cube_token.set(create_cube_token(user))
    return user_token, cube_token


def _reset_user_context(tokens):
    user_token, cube_token = tokens
    current_cube_token.reset(cube_token)
    current_user.reset(user_token)


def _persist_query_side_effects(
    user: UserContext,
    query: str,
    session_id: str,
    response_dict: dict[str, Any],
):
    try:
        success = bool(response_dict.get("success"))
        err = response_dict.get("error") or {}
        error_message = err.get("message") if isinstance(err, dict) else str(err) if err else None
        # Cache metadata surfaced from cache_tool stages via to_dict()
        cache_hit = bool(response_dict.get("cache_hit", False))
        cache_tier = response_dict.get("cache_tier")
        log_audit(
            user=user,
            question=query,
            cube_query=response_dict.get("cube_query"),
            success=success,
            error_message=error_message,
            duration_ms=response_dict.get("duration_ms"),
            cache_hit=cache_hit,
            cache_tier=cache_tier,
        )
        save_chat_message(session_id, user, "user", query)

        # Cache turn in Redis for fast retrieval by intent_router
        try:
            from app.services.redis_session import append_session_turn
            append_session_turn(user.user_id, session_id, "user", query)
        except Exception:
            pass

        # Build assistant content: success messages show actual data, failures show static message
        if response_dict.get("refined_insights"):
            assistant_content = response_dict.get("refined_insights")
        elif response_dict.get("clarification_message"):
            assistant_content = response_dict.get("clarification_message")
        elif success:
            assistant_content = "Query completed."
        else:
            # Pipeline failed: save static message to DB instead of actual error details
            assistant_content = "Unable to process your request"
        
        if not isinstance(assistant_content, str):
            assistant_content = json.dumps(assistant_content, default=str)
            
        # Do not save detailed error messages to the DB
        db_raw_data = response_dict.copy()
        if not success and "error" in db_raw_data:
            # Replace the detailed error with a generic one or remove it completely
            db_raw_data["error"] = "Unable to process your request"
            
        save_chat_message(
            session_id,
            user,
            "assistant",
            assistant_content,
            raw_data=db_raw_data,
            metadata={
                "request_id": response_dict.get("request_id"),
                "stage": response_dict.get("stage"),
                "success": success,
            },
        )
        # Cache assistant turn in Redis
        try:
            from app.services.redis_session import append_session_turn
            append_session_turn(user.user_id, session_id, "assistant", assistant_content)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Persistence side effects failed (non-fatal): {e}")

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
    if "Connection" in error_type or stage == Stage.CUBE_QUERY_BUILT:
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
async def execute_query(
    request: QueryRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
):
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

        tokens = _set_user_context(user)
        try:
            # Delegate to orchestrator (does ALL the work)
            response = run_pipeline(query, session_id=session_id, _resolved_clarifications=request.clarification_answers or None)
        finally:
            _reset_user_context(tokens)

        # Convert to dict for JSON response
        response_dict = response.to_dict()
        _persist_query_side_effects(user, query, session_id, response_dict)

        # Check for clarification request - this is NOT an error, return 200
        if response.stage == Stage.CLARIFICATION_REQUESTED:
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
            if isinstance(response.visual_spec, dict):
                span.set_attribute("output.chart_type", response.visual_spec.get("chart_type", ""))
            else:
                span.set_attribute("output.chart_type", getattr(response.visual_spec, "chart_type", ""))
        span.set_attribute("http.status_code", 200)
        span.set_attribute("output.value", json.dumps(response_dict, default=str))

        # Success - return full response
        return JSONResponse(content=response_dict)


@app.get("/catalog/metrics", tags=["Catalog"])
async def list_metrics(_: Annotated[UserContext, Depends(get_current_user)]):
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
async def list_dimensions(_: Annotated[UserContext, Depends(get_current_user)]):
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
async def list_time_windows(_: Annotated[UserContext, Depends(get_current_user)]):
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
async def clarify_endpoint(
    req: ClarificationRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
):
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

        tokens = _set_user_context(user)
        try:
            response_dict = resume_query(req.request_id, req.answers, session_id=req.session_id)
        finally:
            _reset_user_context(tokens)

        if response_dict.get("session_id"):
            answers_str = ", ".join(str(v).replace("_", " ") for v in req.answers.values()) if getattr(req, "answers", None) else getattr(req, "clarification_answer", getattr(req, "request_id", "Clarification"))
            _persist_query_side_effects(
                user,
                answers_str,
                response_dict["session_id"],
                response_dict,
            )

        # Clarification requested again — not an error, return 200
        if response_dict.get("stage") == Stage.CLARIFICATION_REQUESTED:
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
async def retry_query_endpoint(
    request: RetryRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
):
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

        tokens = _set_user_context(user)
        try:
            # Delegate to orchestrator (handles all retry logic)
            response = execute_retry_query(
                original_request_id=request.original_request_id,
                modified_query=request.modified_query,
                session_id=request.session_id,
                original_query=request.original_query
            )
        finally:
            _reset_user_context(tokens)

        # Convert to dict for JSON response
        response_dict = response.to_dict() if hasattr(response, "to_dict") else vars(response)
        _persist_query_side_effects(user, request.modified_query, request.session_id, response_dict)

        # Check for clarification request - this is NOT an error, return 200
        if getattr(response, "stage", None) == Stage.CLARIFICATION_REQUESTED:
            logger.info(f"Retry clarification requested: {getattr(response, 'missing_fields', [])}")
            span.set_attribute("output.clarification_requested", True)
            span.set_attribute("output.missing_fields", str(getattr(response, 'missing_fields', [])))
            span.set_attribute("output.clarification_message", getattr(response, "clarification_message", "") or "")
            span.set_attribute("output.value", json.dumps(response_dict, default=str))
            return JSONResponse(content=response_dict, status_code=status.HTTP_200_OK)

        success = getattr(response, "success", False)
        if not success:
            # Pipeline failed - return error with appropriate HTTP status
            error_obj = getattr(response, "error", None)
            error_type = error_obj.error_type if error_obj and hasattr(error_obj, "error_type") else "UnknownError"
            stage = getattr(response, "stage", "Unknown")
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

        error_obj = getattr(response, "error", None)
        if error_obj:
            span.set_status(Status(StatusCode.ERROR, "LLM temporarily unavailable"))
            span.set_attribute("http.status_code", 503)
            raise HTTPException(
                status_code=503,
                detail="LLM temporarily unavailable"
            )

        logger.info(f"Retry executed successfully in {getattr(response, 'duration_ms', 0)}ms, {len(getattr(response, 'data', []) or [])} rows")
        span.set_attribute("output.success", True)
        span.set_attribute("output.duration_ms", getattr(response, "duration_ms", 0))
        span.set_attribute("output.row_count", len(getattr(response, "data", []) or []))
        if getattr(response, "visual_spec", None):
            if isinstance(response.visual_spec, dict):
                span.set_attribute("output.chart_type", response.visual_spec.get("chart_type", ""))
            else:
                span.set_attribute("output.chart_type", getattr(response.visual_spec, "chart_type", ""))
        span.set_attribute("http.status_code", 200)
        span.set_attribute("output.value", json.dumps(response_dict, default=str))

        # Success - return full response
        return JSONResponse(content=response_dict)


# =============================================================================
# CACHE + MEMORY ENDPOINTS
# =============================================================================

@app.get("/cache/stats", tags=["Cache"])
async def get_cache_stats(_: Annotated[UserContext, Depends(get_current_user)]):
    """Return cache hit statistics and token savings estimate."""
    from app.services.cache_manager import get_cache_stats
    return get_cache_stats()


@app.post("/cache/clear/{user_id}", tags=["Cache"])
async def clear_user_cache(
    user_id: str,
    current: Annotated[UserContext, Depends(get_current_user)],
):
    """Clear all Tier-2 Redis semantic cache entries for a user."""
    from app.services.cache_manager import semantic_cache
    deleted = semantic_cache.clear_user(user_id)
    return {"user_id": user_id, "deleted_entries": deleted}


@app.get("/user/{user_id}/memory", tags=["Memory"])
async def get_user_memory(
    user_id: str,
    n: int = 10,
    _: Annotated[UserContext, Depends(get_current_user)] = None,
):
    """Return the last N memory turns for a user."""
    from app.services.memory_manager import get_turns
    turns = get_turns(user_id, n=n)
    return {"user_id": user_id, "turns": turns, "count": len(turns)}


@app.post("/golden-qa/refresh", tags=["Cache"])
async def refresh_golden_qa(_: Annotated[UserContext, Depends(get_current_user)]):
    """Re-run all canonical SQL queries and update prebuilt answers."""
    from app.services.cache_manager import golden_cache
    result = await golden_cache.refresh_all()
    return result


@app.get("/golden-qa/list", tags=["Cache"])
async def list_golden_qa(_: Annotated[UserContext, Depends(get_current_user)]):
    """Return all golden Q&A entries with metadata and hit counts."""
    from app.services.cache_manager import golden_cache
    return {"entries": golden_cache.list_entries(), "total": len(golden_cache.list_entries())}



# =============================================================================
# DASHBOARD — Fast KPI endpoint (direct Cube.js, zero NL pipeline)
# =============================================================================

@app.get("/dashboard/kpis", tags=["Dashboard"])
async def get_dashboard_kpis(
    user: Annotated[UserContext, Depends(get_current_user)],
):
    """
    Fast dashboard KPIs — direct Postgres SQL, zero NL pipeline, zero Cube.
    Response time: <500ms.
    """
    import psycopg2, psycopg2.extras, os
    from datetime import date, timedelta

    schema = user.schema_name
    today  = date.today()
    d30    = (today - timedelta(days=30)).isoformat()
    d60    = (today - timedelta(days=60)).isoformat()
    d31    = (today - timedelta(days=31)).isoformat()
    tod    = today.isoformat()
    d7     = (today - timedelta(days=7)).isoformat()

    dsn = {
        "host":     os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "postgres")),
        "port":     int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
        "dbname":   os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "sales_analytics")),
        "user":     os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres")),
        "password": os.getenv("DB_PASS", os.getenv("POSTGRES_PASSWORD", "postgres")),
    }

    def fmt(n):
        n = float(n or 0)
        if n >= 1e7: return f"\u20b9{n/1e7:.1f}Cr"
        if n >= 1e5: return f"\u20b9{n/1e5:.1f}L"
        if n >= 1e3: return f"\u20b9{n/1e3:.1f}K"
        return f"\u20b9{n:.0f}"

    try:
        conn = psycopg2.connect(**dsn)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Net Sales current 30 days
        cur.execute(f"""
            SELECT COALESCE(SUM(net_value),0) AS net_sales
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
        """, (d30, tod))
        cur_val = float((cur.fetchone() or {}).get("net_sales", 0))

        # 2. Net Sales previous 30 days (days 31-60)
        cur.execute(f"""
            SELECT COALESCE(SUM(net_value),0) AS net_sales
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
        """, (d60, d31))
        prev_val = float((cur.fetchone() or {}).get("net_sales", 0))

        ns_trend = round(((cur_val - prev_val) / prev_val * 100), 1) if prev_val else 0.0

        # 3. Active SKUs
        cur.execute(f"""
            SELECT COUNT(DISTINCT sku_code) AS sku_count
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
        """, (d30, tod))
        sku_count = int((cur.fetchone() or {}).get("sku_count", 0))

        # 4. Zone coverage
        cur.execute(f"""
            SELECT COUNT(DISTINCT zone) AS zone_count
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
        """, (d30, tod))
        zone_count = int((cur.fetchone() or {}).get("zone_count", 0))

        # 5. Target vs actual proxy
        target_proxy = min(round((cur_val / (prev_val * 1.2)) * 100), 100) if prev_val else 0

        # 6. Trend 30D daily
        cur.execute(f"""
            SELECT invoice_date::date AS day, COALESCE(SUM(net_value),0) AS net_sales
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
            GROUP BY invoice_date::date ORDER BY day ASC
        """, (d30, tod))
        trend_7d = [{"label": str(r["day"]), "value": float(r["net_sales"])} for r in cur.fetchall()]

        # 7. Top 10 brands
        cur.execute(f"""
            SELECT brand, COALESCE(SUM(net_value),0) AS net_sales
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
            GROUP BY brand ORDER BY net_sales DESC LIMIT 10
        """, (d30, tod))
        top_brands = [{"Brand": r["brand"], "Net Sales": fmt(r["net_sales"])} for r in cur.fetchall()]

        # 8. Zone rows
        cur.execute(f"""
            SELECT zone, COALESCE(SUM(net_value),0) AS net_sales
            FROM {schema}.fact_secondary_sales
            WHERE invoice_date BETWEEN %s AND %s
            GROUP BY zone ORDER BY net_sales DESC
        """, (d30, tod))
        zone_rows = [{"zone": r["zone"], "net_value": float(r["net_sales"])} for r in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            "kpis": {
                "net_sales":        {"value": fmt(cur_val),  "raw": cur_val,  "trend": ns_trend,  "positive": ns_trend >= 0},
                "active_skus":      {"value": str(sku_count), "raw": sku_count, "trend": 0.0, "positive": True},
                "zone_coverage":    {"value": f"{zone_count} Zone{'s' if zone_count != 1 else ''}", "raw": zone_count, "trend": 0.0, "positive": True},
                "target_vs_actual": {"value": f"{target_proxy}%", "raw": target_proxy, "trend": 2.1 if ns_trend >= 0 else -2.1, "positive": ns_trend >= 0},
            },
            "trend_7d":  trend_7d,
            "top_brands": top_brands,
            "zone_rows":  zone_rows,
        }

    except Exception as e:
        logger.error(f"[Dashboard KPI] DB error: {e}")
        raise HTTPException(status_code=500, detail=f"Dashboard query failed: {e}")



# =============================================================================
# INSIGHTS — Role-aware, Postgres-direct, non-obvious intelligence
# =============================================================================

def _insights_fmt(n: float) -> str:
    n = float(n or 0)
    if n >= 1e7: return f"₹{n/1e7:.1f}Cr"
    if n >= 1e5: return f"₹{n/1e5:.1f}L"
    if n >= 1e3: return f"₹{n/1e3:.0f}K"
    return f"₹{n:.0f}"


from app.insight_generator import generate_insights as _generate_insights





# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    uvicorn.run(app, host=host, port=port)
