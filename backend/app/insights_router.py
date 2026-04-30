from typing import Annotated

from fastapi import APIRouter, Depends

from app.security.auth import get_current_user, require_admin
from app.security.context import UserContext
from app.security.metadata_store import list_insights, mark_insight_read


router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("")
async def insights(user: Annotated[UserContext, Depends(get_current_user)], limit: int = 20):
    return {"insights": list_insights(user, limit=limit)}


@router.post("/{insight_id}/read")
async def read_insight(insight_id: str, user: Annotated[UserContext, Depends(get_current_user)]):
    mark_insight_read(user, insight_id)
    return {"success": True}


from pydantic import BaseModel
from typing import Optional

class FeedbackRequest(BaseModel):
    action: str
    session_id: Optional[str] = None

@router.post("/{insight_id}/feedback")
async def insight_feedback(
    insight_id: str,
    req: FeedbackRequest,
    user: Annotated[UserContext, Depends(get_current_user)]
):
    from app.security.metadata_store import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_meta.intel_insight_feedback (insight_id, user_id, action, session_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (insight_id, user_id, action) DO NOTHING
            """, [insight_id, user.user_id, req.action, req.session_id])
    return {"success": True}


@router.post("/intel/run")
async def trigger_intel_run(_: Annotated[UserContext, Depends(get_current_user)]):
    from app.intel.scheduler import run_intel_scheduler
    import asyncio
    
    # We run this as a background task so the HTTP request doesn't timeout
    async def background_run():
        try:
            await run_intel_scheduler("manual")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Manual intel run failed: {e}")
            
    asyncio.create_task(background_run())
    return {
        "success": True, 
        "message": "Intelligence pipeline triggered in background."
    }

