"""
Objectives API — Spec New_Feature-1a/1b
  GET  /objectives/me              -> list objectives for user's role
  GET  /objectives/me/{obj_id}     -> get full objective with questions
  POST /objectives/me/respond      -> save answers + inject context
  GET  /objectives/me/active       -> get current active objective
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security.auth import get_current_user
from app.security.context import UserContext
from app.services.persona.preference_store import save_preferences, load_preferences

router = APIRouter(prefix="/objectives", tags=["Objectives"])

_OBJECTIVES_DIR = Path(__file__).parent.parent / "catalog" / "objectives"


def _load_objectives(role: str) -> list[dict]:
    path = _OBJECTIVES_DIR / f"{role.lower()}.objectives.yaml"
    if not path.exists():
        path = _OBJECTIVES_DIR / "asm.objectives.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("objectives", [])


class ObjectiveResponseRequest(BaseModel):
    objective_id: str
    answers: dict[str, str]


@router.get("/me")
def list_objectives(user: Annotated[UserContext, Depends(get_current_user)]):
    role = (user.role or "asm").lower()
    objectives = _load_objectives(role)
    return {
        "role": role,
        "objectives": [
            {
                "id": o["id"],
                "title": o["title"],
                "description": o["description"],
                "question_count": len(o.get("questions", [])),
            }
            for o in objectives
        ],
    }


@router.get("/me/active")
def get_active_objective(user: Annotated[UserContext, Depends(get_current_user)]):
    prefs = load_preferences(user.user_id)
    obj_id = prefs.get("active_objective_id")
    if not obj_id:
        return {"active": None}
    return {
        "active": {
            "objective_id": obj_id,
            "title": prefs.get("active_objective_title", obj_id),
            "context_text": prefs.get("active_objective_context", ""),
        }
    }


@router.get("/me/{objective_id}")
def get_objective(
    objective_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
):
    role = (user.role or "asm").lower()
    objectives = _load_objectives(role)
    obj = next((o for o in objectives if o["id"] == objective_id), None)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Objective '{objective_id}' not found")
    return obj


@router.post("/me/respond")
def save_objective_response(
    body: ObjectiveResponseRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
):
    role = (user.role or "asm").lower()
    objectives = _load_objectives(role)
    obj = next((o for o in objectives if o["id"] == body.objective_id), None)
    if not obj:
        raise HTTPException(status_code=404, detail="Objective not found")

    # Build human-readable context from answers
    answer_lines = []
    for q in obj.get("questions", []):
        answer = body.answers.get(q["id"])
        if answer:
            label = next((opt["label"] for opt in q.get("options", []) if opt["value"] == answer), answer)
            answer_lines.append(f"  - {q['text']}: {label}")

    context_text = (
        f"User Objective: {obj['title']}\n"
        f"Description: {obj['description']}\n"
        f"Chosen Strategies:\n" + "\n".join(answer_lines)
    )

    prefs = {
        "active_objective_id": body.objective_id,
        "active_objective_title": obj["title"],
        "active_objective_context": context_text,
    }
    save_preferences(user.user_id, prefs)

    return {
        "status": "saved",
        "session_id": str(uuid.uuid4()),
        "objective_id": body.objective_id,
        "title": obj["title"],
        "context_text": context_text,
        "answers": body.answers,
    }
