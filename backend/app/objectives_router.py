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
api_router = APIRouter(prefix="/api/objectives", tags=["Objectives"])

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


# ── Legacy /api/objectives/* endpoints (used by ObjectiveModal component) ──────

class LegacySaveRequest(BaseModel):
    template_id: str
    answers: dict[str, str]
    title: str | None = None


def _to_template(o: dict, role: str, include_questions: bool = False) -> dict:
    out: dict = {
        "template_id": o["id"],
        "role": role,
        "title": o["title"],
        "description": o.get("description", ""),
        "order_no": 0,
    }
    if include_questions:
        out["questions"] = [
            {
                "question_id": q["id"],
                "question_text": q["text"],
                "input_type": "select",
                "order_no": i,
                "is_required": True,
                "options": [
                    {"label": opt["label"], "value": opt["value"], "order_no": j}
                    for j, opt in enumerate(q.get("options", []))
                ],
            }
            for i, q in enumerate(o.get("questions", []))
        ]
    return out


@api_router.get("/templates")
def legacy_list_templates(user: Annotated[UserContext, Depends(get_current_user)]):
    role = (user.role or "asm").lower()
    objectives = _load_objectives(role)
    return {"templates": [_to_template(o, role) for o in objectives]}


@api_router.get("/templates/{template_id}")
def legacy_get_template(template_id: str, user: Annotated[UserContext, Depends(get_current_user)]):
    role = (user.role or "asm").lower()
    objectives = _load_objectives(role)
    obj = next((o for o in objectives if o["id"] == template_id), None)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_template(obj, role, include_questions=True)


@api_router.post("")
def legacy_save_objective(body: LegacySaveRequest, user: Annotated[UserContext, Depends(get_current_user)]):
    role = (user.role or "asm").lower()
    objectives = _load_objectives(role)
    obj = next((o for o in objectives if o["id"] == body.template_id), None)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")
    answer_lines = []
    for q in obj.get("questions", []):
        answer = body.answers.get(q["id"])
        if answer:
            label = next((opt["label"] for opt in q.get("options", []) if opt["value"] == answer), answer)
            answer_lines.append(f"  - {q['text']}: {label}")
    context_text = f"User Objective: {obj['title']}\n" + "\n".join(answer_lines)
    prefs = {
        "active_objective_id": body.template_id,
        "active_objective_title": obj["title"],
        "active_objective_context": context_text,
    }
    save_preferences(user.user_id, prefs)
    return {"session_id": str(uuid.uuid4()), "template_id": body.template_id}
