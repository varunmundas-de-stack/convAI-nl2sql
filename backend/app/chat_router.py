from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.security.auth import get_current_user
from app.security.context import UserContext
from app.security.metadata_store import list_messages, list_sessions, update_session


router = APIRouter(prefix="/chat", tags=["Chat"])


class SessionPatch(BaseModel):
    title: str | None = None
    is_active: bool | None = None


@router.get("/sessions")
async def sessions(user: Annotated[UserContext, Depends(get_current_user)]):
    return {"sessions": list_sessions(user)}


@router.get("/sessions/{session_id}/messages")
async def messages(session_id: str, user: Annotated[UserContext, Depends(get_current_user)]):
    return {"messages": list_messages(user, session_id)}


@router.patch("/sessions/{session_id}")
async def patch_session(
    session_id: str,
    payload: SessionPatch,
    user: Annotated[UserContext, Depends(get_current_user)],
):
    update_session(user, session_id, payload.title, payload.is_active)
    return {"success": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: Annotated[UserContext, Depends(get_current_user)]):
    update_session(user, session_id, None, False)
    return {"success": True}
