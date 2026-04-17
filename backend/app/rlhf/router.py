"""
RLHF FastAPI Router.

Endpoints for feedback collection, prompt version management,
A/B testing, and prompt refinement.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.rlhf import feedback_service
from app.rlhf import ab_router as ab
from app.rlhf import prompt_manager
from app.rlhf.refiner import run_refinement, apply_refinement, promote_version, rollback_version
from app.rlhf.scheduler import run_refinement_cycle

logger = logging.getLogger(__name__)

router = APIRouter(tags=["RLHF"])


# =============================================================================
# REQUEST MODELS
# =============================================================================

class FeedbackRequest(BaseModel):
    request_id: str
    query: str
    response_summary: str = Field(max_length=500)
    prompt_version: str
    rating: int = Field(ge=1, le=5)
    ab_group: Optional[str] = None
    correction: Optional[str] = None
    full_response: Optional[str] = None
    sql_query: Optional[str] = None


class ABTestRequest(BaseModel):
    version_a: str
    version_b: str
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0)


# =============================================================================
# FEEDBACK
# =============================================================================

@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Submit a rating (1–5) with optional correction for a response."""
    entry_id = feedback_service.log_feedback(
        request_id=req.request_id,
        query=req.query,
        response_summary=req.response_summary,
        prompt_version=req.prompt_version,
        rating=req.rating,
        ab_group=req.ab_group,
        correction=req.correction,
        full_response=req.full_response,
        sql_query=req.sql_query,
    )
    return {"status": "ok", "feedback_id": entry_id}


# =============================================================================
# PROMPT VERSIONS
# =============================================================================

@router.get("/prompt-versions")
async def list_prompt_versions():
    """List all prompt versions with average rating and feedback count."""
    versions = prompt_manager.list_versions()
    # Enrich with stats
    for v in versions:
        stats = feedback_service.get_version_stats(v["version_tag"])
        v["avg_rating"] = stats["avg_rating"]
        v["feedback_count"] = stats["count"]
        v["distribution"] = stats["distribution"]
    return {"versions": versions}


# =============================================================================
# PREFERENCE PAIRS
# =============================================================================

@router.get("/preference-pairs")
async def get_preference_pairs(
    version: str = Query(..., description="Prompt version tag"),
    min_gap: int = Query(2, ge=1, le=4),
):
    """Fetch (chosen, rejected) preference pairs for a prompt version."""
    pairs = feedback_service.get_preference_pairs(version, min_gap=min_gap)
    return {"version": version, "pairs": pairs, "count": len(pairs)}


# =============================================================================
# REFINEMENT
# =============================================================================

@router.post("/refine")
async def refine_prompt(
    version: str = Query(..., description="Base version to refine"),
):
    """Trigger Claude meta-prompt refinement and create a new version."""
    result = run_refinement(version)
    if result.get("status") != "success":
        return result

    new_tag = apply_refinement(result, version)
    return {
        "status": "success",
        "new_version": new_tag,
        "analysis": result.get("analysis", ""),
        "edits": result.get("edits", []),
    }


@router.post("/promote")
async def promote(
    version: str = Query(..., description="Version to promote"),
):
    """Promote a prompt version to active."""
    try:
        promote_version(version)
        return {"status": "ok", "promoted": version}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/rollback")
async def rollback(
    version: str = Query(..., description="Version to rollback from"),
):
    """Rollback to the parent version of the given version."""
    try:
        parent = rollback_version(version)
        return {"status": "ok", "rolled_back_from": version, "active_version": parent}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# A/B TESTING
# =============================================================================

@router.get("/ab-status")
async def ab_status():
    """Get current A/B test status and per-group stats."""
    config = ab.get_ab_status()
    if not config:
        return {"active": False, "message": "No A/B test is currently running"}

    stats_a = feedback_service.get_version_stats(config["version_a"])
    stats_b = feedback_service.get_version_stats(config["version_b"])

    return {
        "active": True,
        "config": config,
        "stats": {
            "version_a": stats_a,
            "version_b": stats_b,
        },
    }


@router.post("/ab-test")
async def create_ab_test(req: ABTestRequest):
    """Create a new A/B test between two prompt versions."""
    result = ab.create_ab_test(req.version_a, req.version_b, req.traffic_split)
    return {"status": "ok", "test": result}


@router.post("/ab-stop")
async def stop_ab_test():
    """Stop the currently active A/B test."""
    stopped = ab.stop_ab_test()
    return {"status": "ok", "was_active": stopped}


# =============================================================================
# FULL CYCLE
# =============================================================================

@router.post("/run-cycle")
async def trigger_refinement_cycle(
    version: str = Query(..., description="Baseline version for refinement"),
    min_ratings: int = Query(50, ge=1),
    min_improvement: float = Query(0.3, ge=0.0),
):
    """Trigger a full refinement cycle with guardrails."""
    result = run_refinement_cycle(version, min_ratings=min_ratings, min_improvement=min_improvement)
    return result


# =============================================================================
# VERSION COMPARISON
# =============================================================================

@router.get("/compare")
async def compare_versions(
    version_a: str = Query(...),
    version_b: str = Query(...),
):
    """Compare stats between two prompt versions."""
    return feedback_service.compare_versions(version_a, version_b)


# =============================================================================
# RETRY ANALYTICS
# =============================================================================

@router.get("/retry-statistics")
async def get_retry_statistics(
    version: Optional[str] = Query(None, description="Optional prompt version to filter by"),
):
    """Get statistics about retry patterns for analysis."""
    stats = feedback_service.get_retry_statistics(version)
    return {
        "status": "ok",
        "version": version or "all",
        "statistics": stats,
    }
