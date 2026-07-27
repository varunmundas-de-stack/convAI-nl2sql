"""
Persona API — exposes spec-10/14 persona card data to the frontend.
  GET /persona/me/cold-start   → cold-start preference questions for the user's role
  GET /persona/me/kpis         → primary + secondary KPI list for the user's role
  GET /persona/me/home-layout  → Spec-14 section grammar for the user's home page
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.security.auth import get_current_user
from app.security.context import UserContext
from app.services.persona.card_loader import get_loader
from app.services.persona.preference_store import save_preferences, resolve_preferences

router = APIRouter(prefix="/persona", tags=["Persona"])

_CATALOG_ROOT = Path(__file__).parent.parent / "catalog"


class SavePreferencesRequest(BaseModel):
    preferences: dict[str, Any]
_PREF_CATALOG_PATH = _CATALOG_ROOT / "preference-catalog.yaml"
_METRIC_REGISTRY_PATH = _CATALOG_ROOT / "metric-registry.yaml"
_HOME_LAYOUTS_DIR = _CATALOG_ROOT / "home-layouts"


def _card_id_for_user(user: UserContext) -> str:
    role = (user.role or "").lower()
    loader = get_loader()
    return role if role in loader.list_cards() else "asm"


def _load_pref_catalog() -> dict:
    return {e["preference_id"]: e for e in yaml.safe_load(_PREF_CATALOG_PATH.read_text(encoding="utf-8"))}


def _load_metric_registry() -> dict:
    return {e["metric_id"]: e for e in yaml.safe_load(_METRIC_REGISTRY_PATH.read_text(encoding="utf-8"))}


@router.get("/me/cold-start")
def get_cold_start(user: Annotated[UserContext, Depends(get_current_user)]):
    loader = get_loader()
    card_id = _card_id_for_user(user)
    raw_questions = loader.get_cold_start_questions(card_id)
    catalog = _load_pref_catalog()

    questions = []
    for q in raw_questions:
        pref_id = q["preference"]
        entry = catalog.get(pref_id, {})
        questions.append({
            "preference_id": pref_id,
            "question_text": entry.get("question_text", pref_id),
            "options": [
                {"value": opt["value"], "label": opt["label"]}
                for opt in entry.get("options", [])
            ],
            "default": q.get("default"),
        })

    return {"card_id": card_id, "questions": questions}


@router.get("/me/kpis")
def get_persona_kpis(user: Annotated[UserContext, Depends(get_current_user)]):
    loader = get_loader()
    card_id = _card_id_for_user(user)
    card = loader.get_card(card_id)
    registry = _load_metric_registry()

    def enrich(metric_ids: list[str]) -> list[dict]:
        return [
            {
                "metric_id": m,
                "display_name": registry.get(m, {}).get("display_name", m),
                "format": registry.get(m, {}).get("format", "number"),
                "unit": registry.get(m, {}).get("unit", ""),
                "direction": registry.get(m, {}).get("direction", "higher_is_better"),
            }
            for m in metric_ids
        ]

    return {
        "card_id": card_id,
        "display_name": card.get("display_name", card_id.upper()),
        "primary": enrich(card["kpis"]["primary"]),
        "secondary": enrich(card["kpis"].get("secondary", [])),
    }


@router.get("/me/home-layout")
def get_home_layout(user: Annotated[UserContext, Depends(get_current_user)]):
    loader = get_loader()
    card_id = _card_id_for_user(user)
    card = loader.get_card(card_id)

    # Load layout YAML; fall back to asm if not found
    layout_path = _HOME_LAYOUTS_DIR / f"{card_id}.home.yaml"
    if not layout_path.exists():
        layout_path = _HOME_LAYOUTS_DIR / "asm.home.yaml"
    layout = yaml.safe_load(layout_path.read_text(encoding="utf-8"))

    # Resolve suggested_questions sections from the card's question bank
    resolved_sections = []
    for section in layout.get("sections", []):
        s = dict(section)
        if s.get("type") == "suggested_questions":
            questions = card.get("questions", [])
            max_items = s.get("max_items", 4)
            s["items"] = [
                {
                    "id": q["id"],
                    "label": q["text"].split("?")[0].strip().replace("this {{period}}", "this month").replace("{{period}}", "month")[:50],
                    "question": q["text"].replace("this {{period}}", "this month").replace("{{period}}", "month"),
                    "intent": q.get("intent", ""),
                }
                for q in questions[:max_items]
            ]
        elif s.get("type") == "action_list":
            actions = card.get("actions", [])
            max_items = s.get("max_items", 4)
            s["items"] = [
                {"id": a["id"], "label": a["label"], "from_insight": a.get("from_insight", "")}
                for a in actions[:max_items]
            ]
        resolved_sections.append(s)

    return {
        "card_id": card_id,
        "display_name": card.get("display_name", card_id.upper()),
        "sections": resolved_sections,
    }


def _card_preference_defaults(card: dict) -> dict:
    """Extract {preference_id: default} from card YAML preferences list."""
    return {
        pref["preference"]: pref["default"]
        for pref in card.get("preferences", [])
        if "preference" in pref and "default" in pref
    }


@router.post("/me/preferences")
def save_user_preferences(
    body: SavePreferencesRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
):
    loader = get_loader()
    card_id = _card_id_for_user(user)
    card = loader.get_card(card_id)
    card_defaults = _card_preference_defaults(card)

    save_preferences(user.user_id, body.preferences)
    resolved = resolve_preferences(user.user_id, card_defaults)

    return {
        "status": "saved",
        "card_id": card_id,
        "resolved": resolved,
    }


@router.get("/me/resolved-context")
def get_resolved_context(user: Annotated[UserContext, Depends(get_current_user)]):
    loader = get_loader()
    card_id = _card_id_for_user(user)
    card = loader.get_card(card_id)
    card_defaults = _card_preference_defaults(card)

    resolved = resolve_preferences(user.user_id, card_defaults)
    scope = card.get("scope", {})

    return {
        "card_id": card_id,
        "display_name": card.get("display_name", card_id.upper()),
        "resolved_preferences": resolved,
        "scope": scope,
    }
