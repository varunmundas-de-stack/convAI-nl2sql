"""
Tests for persona card loader and YAML spec files.
Validates spec-10 contract rules:
  - KPI ids exist in metric registry
  - insight_types exist in insight-rules registry
  - preferences exist in preference catalog
  - cold_start ask_preferences are all ask_priority=high
  - len(cold_start.ask_preferences) <= max_questions
"""

import pytest
from app.services.persona.card_loader import PersonaCardLoader


@pytest.fixture(scope="module")
def loader() -> PersonaCardLoader:
    return PersonaCardLoader()


def test_cards_loaded(loader):
    cards = loader.list_cards()
    assert len(cards) >= 2, "Expected at least asm and nsm cards"
    assert "asm" in cards
    assert "nsm" in cards


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_card_has_required_fields(loader, card_id):
    card = loader.get_card(card_id)
    for field in ("card_id", "version", "display_name", "job_description",
                  "hierarchy", "scope", "kpis", "preferences", "insight_types",
                  "questions", "actions", "cold_start"):
        assert field in card, f"{card_id} missing field: {field}"


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_primary_kpis_in_registry(loader, card_id):
    errors = loader._validate_card(loader.get_card(card_id))
    kpi_errors = [e for e in errors if "kpis" in e]
    assert not kpi_errors, f"{card_id} KPI validation errors: {kpi_errors}"


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_insight_types_in_registry(loader, card_id):
    errors = loader._validate_card(loader.get_card(card_id))
    rule_errors = [e for e in errors if "insight_types" in e]
    assert not rule_errors, f"{card_id} insight_type errors: {rule_errors}"


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_preferences_in_catalog(loader, card_id):
    errors = loader._validate_card(loader.get_card(card_id))
    pref_errors = [e for e in errors if "preference" in e]
    assert not pref_errors, f"{card_id} preference errors: {pref_errors}"


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_cold_start_constraints(loader, card_id):
    questions = loader.get_cold_start_questions(card_id)
    card = loader.get_card(card_id)
    max_q = card["cold_start"]["max_questions"]
    assert len(questions) <= max_q


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_preference_defaults_present(loader, card_id):
    defaults = loader.get_preference_defaults(card_id)
    assert len(defaults) > 0
    assert "sales_type" in defaults
    assert "comparison_period" in defaults


@pytest.mark.parametrize("card_id", ["asm", "nsm"])
def test_actions_have_from_insight(loader, card_id):
    for insight_type in loader.get_insight_types(card_id):
        actions = loader.get_actions_for_insight(card_id, insight_type)
        assert len(actions) >= 1, (
            f"{card_id}: no action mapped to insight_type '{insight_type}'"
        )
