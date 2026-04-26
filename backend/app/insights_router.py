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


@router.post("/generate")
async def generate_insights(_: Annotated[UserContext, Depends(require_admin)]):
    # The initial integration seeds and serves insights. A richer generator can be
    # scheduled here once hierarchy-code columns are normalized across datasets.
    return {"success": True, "generated": 0, "message": "Insight seed data is active; generator is not scheduled."}
