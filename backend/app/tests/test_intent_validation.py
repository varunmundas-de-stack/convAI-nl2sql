import pytest
from app.services.intent.intent_validator import validate_intent
from app.services.intent.intent_errors import (
    UnknownMetricError,
    UnknownDimensionError,
    InvalidTimeWindowError,
    MalformedIntentError,
    IntentIncompleteError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_intent(**overrides):
    """Minimal valid raw intent dict (current schema)."""
    base = {
        "sales_scope": "PRIMARY",
        "metrics": [{"name": "fact_primary_sales.count", "aggregation": "sum"}],
        "time": {
            "dimension": "fact_primary_sales.invoice_date",
            "window": "last_30_days",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_valid_snapshot_intent(catalog_manager):
    raw = _base_intent()
    intent = validate_intent(raw, catalog_manager)
    assert intent.metrics[0].name == "fact_primary_sales.count"
    assert intent.time.window == "last_30_days"


def test_unknown_metric(catalog_manager):
    raw = _base_intent(
        metrics=[{"name": "invalid_metric", "aggregation": "sum"}]
    )
    with pytest.raises(UnknownMetricError) as exc:
        validate_intent(raw, catalog_manager)
    assert exc.value.value == "invalid_metric"


def test_unknown_dimension(catalog_manager):
    raw = _base_intent(
        group_by=["fact_primary_sales.brand", "invalid_dimension"]
    )
    with pytest.raises(UnknownDimensionError) as exc:
        validate_intent(raw, catalog_manager)
    assert exc.value.value == "invalid_dimension"


def test_missing_required_fields_raises_incomplete(catalog_manager):
    """Missing time block → IntentIncompleteError with 'time' in missing_fields."""
    raw = {
        "sales_scope": "PRIMARY",
        "metrics": [{"name": "fact_primary_sales.count", "aggregation": "sum"}],
        # No "time" key at all
    }
    with pytest.raises(IntentIncompleteError) as exc:
        validate_intent(raw, catalog_manager)
    assert "time" in exc.value.missing_fields


def test_malformed_intent_structure(catalog_manager):
    """Extra unknown field on Intent → Pydantic rejects it → MalformedIntentError."""
    raw = _base_intent(intent_type="invalid_type")  # intent_type is not a valid Intent field (extra="forbid")
    with pytest.raises(MalformedIntentError):
        validate_intent(raw, catalog_manager)


def test_valid_trend_intent(catalog_manager):
    raw = _base_intent(
        time={
            "dimension": "fact_primary_sales.invoice_date",
            "window": "last_year",
            "granularity": "month",
        }
    )
    intent = validate_intent(raw, catalog_manager)
    assert intent.time.dimension == "fact_primary_sales.invoice_date"
    assert intent.time.granularity == "month"


def test_trend_requires_time_window(catalog_manager):
    """A trend intent with no window or date range → IntentIncompleteError."""
    raw = {
        "sales_scope": "PRIMARY",
        "metrics": [{"name": "fact_primary_sales.count", "aggregation": "sum"}],
        "time": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month",
            # no window, no start_date/end_date
        },
    }
    with pytest.raises(IntentIncompleteError) as exc:
        validate_intent(raw, catalog_manager)
    assert "time" in " ".join(exc.value.missing_fields)


def test_invalid_time_window(catalog_manager):
    raw = _base_intent(
        time={
            "dimension": "fact_primary_sales.invoice_date",
            "window": "invalid_window",
        }
    )
    with pytest.raises(InvalidTimeWindowError):
        validate_intent(raw, catalog_manager)
