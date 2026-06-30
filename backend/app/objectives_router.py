import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security.auth import get_current_user
from app.security.context import UserContext
from app.security.metadata_store import (
    get_objective_template,
    list_objective_templates,
    save_objective_session,
)

router = APIRouter(prefix="/api/objectives", tags=["Objectives"])


@router.get("/templates")
async def get_templates(user: Annotated[UserContext, Depends(get_current_user)]):
    return {"templates": list_objective_templates(user.role)}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str, user: Annotated[UserContext, Depends(get_current_user)]
):
    template = get_objective_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


class SaveObjectiveRequest(BaseModel):
    template_id: str
    answers: dict[str, Any]
    title: str | None = None
    session_id: str | None = None


@router.post("")
async def save_objective(
    payload: SaveObjectiveRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
):
    template = get_objective_template(payload.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    session_id = payload.session_id or str(uuid.uuid4())
    save_objective_session(
        session_id=session_id,
        user=user,
        template_id=payload.template_id,
        answers=payload.answers,
        title=payload.title or template["title"],
    )
    return {"session_id": session_id, "template_id": payload.template_id}
###################
