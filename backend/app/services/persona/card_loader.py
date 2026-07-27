"""
Persona Card Loader — reads and validates spec-10 YAML cards against
the metric registry (12), insight rules (13), and preference catalog (11).

Usage:
    from app.services.persona.card_loader import PersonaCardLoader
    loader = PersonaCardLoader()
    card = loader.get_card("asm")
    kpis = loader.get_primary_kpis("asm")
    cold_start = loader.get_cold_start_questions("asm")
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CATALOG_ROOT = Path(__file__).parents[3] / "catalog"
_CARDS_DIR = _CATALOG_ROOT / "persona-cards"
_METRIC_REGISTRY_PATH = _CATALOG_ROOT / "metric-registry.yaml"
_INSIGHT_RULES_PATH = _CATALOG_ROOT / "insight-rules.yaml"
_PREFERENCE_CATALOG_PATH = _CATALOG_ROOT / "preference-catalog.yaml"


class PersonaCardLoader:
    def __init__(self) -> None:
        self._metric_ids: set[str] = self._load_metric_ids()
        self._rule_ids: set[str] = self._load_rule_ids()
        self._preference_ids: set[str] = self._load_preference_ids()
        self._cards: dict[str, dict[str, Any]] = self._load_all_cards()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_card(self, card_id: str) -> dict[str, Any]:
        if card_id not in self._cards:
            raise KeyError(f"Persona card not found: {card_id!r}")
        return self._cards[card_id]

    def list_cards(self) -> list[str]:
        return list(self._cards.keys())

    def get_primary_kpis(self, card_id: str) -> list[str]:
        return self.get_card(card_id)["kpis"]["primary"]

    def get_all_kpis(self, card_id: str) -> list[str]:
        card = self.get_card(card_id)
        return card["kpis"]["primary"] + card["kpis"].get("secondary", [])

    def get_insight_types(self, card_id: str) -> list[str]:
        return self.get_card(card_id).get("insight_types", [])

    def get_cold_start_questions(self, card_id: str) -> list[dict[str, Any]]:
        """
        Return cold-start preference entries for the card.
        Filters card preferences to only those in cold_start.ask_preferences,
        up to cold_start.max_questions.
        """
        card = self.get_card(card_id)
        cold = card.get("cold_start", {})
        ask_pref_ids: list[str] = cold.get("ask_preferences", [])
        max_q: int = cold.get("max_questions", 2)

        pref_map = {p["preference"]: p for p in card.get("preferences", [])}
        result = []
        for pref_id in ask_pref_ids[:max_q]:
            if pref_id in pref_map:
                result.append(pref_map[pref_id])
        return result

    def get_preference_defaults(self, card_id: str) -> dict[str, str]:
        card = self.get_card(card_id)
        return {p["preference"]: p["default"] for p in card.get("preferences", [])}

    def get_questions(self, card_id: str) -> list[dict[str, Any]]:
        return self.get_card(card_id).get("questions", [])

    def get_actions(self, card_id: str) -> list[dict[str, Any]]:
        return self.get_card(card_id).get("actions", [])

    def get_actions_for_insight(self, card_id: str, rule_id: str) -> list[dict[str, Any]]:
        return [
            a for a in self.get_actions(card_id)
            if a.get("from_insight") == rule_id
        ]

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_metric_ids(self) -> set[str]:
        data = yaml.safe_load(_METRIC_REGISTRY_PATH.read_text(encoding="utf-8"))
        return {entry["metric_id"] for entry in data}

    def _load_rule_ids(self) -> set[str]:
        data = yaml.safe_load(_INSIGHT_RULES_PATH.read_text(encoding="utf-8"))
        return {entry["rule_id"] for entry in data}

    def _load_preference_ids(self) -> set[str]:
        data = yaml.safe_load(_PREFERENCE_CATALOG_PATH.read_text(encoding="utf-8"))
        return {entry["preference_id"] for entry in data}

    def _load_all_cards(self) -> dict[str, dict[str, Any]]:
        cards: dict[str, dict[str, Any]] = {}
        for path in sorted(_CARDS_DIR.glob("*.card.yaml")):
            try:
                card = yaml.safe_load(path.read_text(encoding="utf-8"))
                errors = self._validate_card(card)
                if errors:
                    for e in errors:
                        logger.warning(f"[persona] {path.name}: {e}")
                cards[card["card_id"]] = card
                logger.info(f"[persona] Loaded card: {card['card_id']} v{card['version']}")
            except Exception as exc:
                logger.error(f"[persona] Failed to load {path.name}: {exc}")
        return cards

    # ------------------------------------------------------------------
    # Validation (mirrors CI checks from spec 10)
    # ------------------------------------------------------------------

    def _validate_card(self, card: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        card_id = card.get("card_id", "?")

        # KPI ids must exist in metric registry
        for kpi in card.get("kpis", {}).get("primary", []):
            if kpi not in self._metric_ids:
                errors.append(f"kpis.primary '{kpi}' not in metric registry")
        for kpi in card.get("kpis", {}).get("secondary", []):
            if kpi not in self._metric_ids:
                errors.append(f"kpis.secondary '{kpi}' not in metric registry")

        # insight_types must exist in rule registry
        for rule_id in card.get("insight_types", []):
            if rule_id not in self._rule_ids:
                errors.append(f"insight_types '{rule_id}' not in insight-rules registry")

        # preference ids must exist in catalog
        for p in card.get("preferences", []):
            pref_id = p.get("preference", "")
            if pref_id not in self._preference_ids:
                errors.append(f"preference '{pref_id}' not in preference catalog")

        # cold_start.ask_preferences must be in preferences with ask_priority=high
        cold = card.get("cold_start", {})
        ask_pref_ids = set(cold.get("ask_preferences", []))
        high_pref_ids = {
            p["preference"] for p in card.get("preferences", [])
            if p.get("ask_priority") == "high"
        }
        for pid in ask_pref_ids:
            if pid not in high_pref_ids:
                errors.append(
                    f"cold_start.ask_preferences '{pid}' must have ask_priority=high"
                )

        max_q = cold.get("max_questions", 3)
        if len(ask_pref_ids) > max_q:
            errors.append(
                f"cold_start.ask_preferences has {len(ask_pref_ids)} entries "
                f"but max_questions={max_q}"
            )

        return errors


# ---------------------------------------------------------------------------
# Module-level singleton (lazy, cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_loader() -> PersonaCardLoader:
    return PersonaCardLoader()
