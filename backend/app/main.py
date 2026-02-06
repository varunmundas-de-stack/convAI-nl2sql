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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.query_orchestrator import execute_query as run_pipeline, resume_query, PipelineStage
from app.services.catalog_manager import CatalogManager

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

class ClarificationRequest(BaseModel):
    request_id: str
    answers: dict[str, Any]

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
    logger.info(f"Received query: {query}")
    
    # Delegate to orchestrator (does ALL the work)
    response = run_pipeline(query)
    
    # Convert to dict for JSON response
    response_dict = response.to_dict()
    
    # Check for clarification request - this is NOT an error, return 200
    if response.stage == PipelineStage.CLARIFICATION_REQUESTED:
        logger.info(f"Clarification requested: {response.missing_fields}")
        return JSONResponse(content=response_dict, status_code=status.HTTP_200_OK)
    
    if not response.success:
        # Pipeline failed - return error with appropriate HTTP status
        error_type = response.error.error_type if response.error else "UnknownError"
        stage = response.stage  # Use the actual stage from response, not from error
        http_status = _get_http_status_for_stage(stage, error_type)
        
        logger.warning(f"Pipeline failed at stage '{stage}': {error_type}")
        
        # Convert the error object to a string or dict
        if "error" in response_dict and isinstance(response_dict["error"], Exception):
            response_dict["error"] = str(response_dict["error"]) 

        raise HTTPException(status_code=http_status, detail=response_dict)
    
    logger.info(f"Query executed successfully in {response.duration_ms}ms, {len(response.data or [])} rows")
     
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

@app.post("/clarify")
def clarify_endpoint(req: ClarificationRequest):
    return resume_query(req.request_id, req.answers)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    uvicorn.run(app, host=host, port=port)
