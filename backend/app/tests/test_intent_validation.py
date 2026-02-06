import pytest
from app.services.intent_validator import validate_intent
from app.services.intent_errors import (
    UnknownMetricError,
    UnknownDimensionError,
    UnknownTimeDimensionError,
    InvalidTimeWindowError,
    MalformedIntentError,
    IntentIncompleteError,
)

def test_valid_snapshot_intent(catalog_manager):
    raw_intent = {
        "intent_type": "snapshot",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "time_range": {"window": "last_30_days"},
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        }
    }
    intent = validate_intent(raw_intent, catalog_manager)
    assert intent.metric == "fact_primary_sales.count"
    assert intent.time_range.window == "last_30_days"

def test_unknown_metric(catalog_manager):
    raw_intent = {
        "intent_type": "snapshot",
        "metric": "invalid_metric",
        "sales_scope": "PRIMARY",
        "time_range": {"window": "last_30_days"},
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        }
    }
    with pytest.raises(UnknownMetricError) as excinfo:
        validate_intent(raw_intent, catalog_manager)
    assert excinfo.value.value == "invalid_metric"

def test_unknown_dimension(catalog_manager):
    raw_intent = {
        "intent_type": "distribution",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "group_by": ["fact_primary_sales.brand", "invalid_dimension"],
        "time_range": {"window": "last_30_days"},
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        }
    }
    with pytest.raises(UnknownDimensionError) as excinfo:
        validate_intent(raw_intent, catalog_manager)
    assert excinfo.value.value == "invalid_dimension"

def test_missing_required_fields_raises_incomplete(catalog_manager):
    # Missing time_range
    raw_intent = {
        "intent_type": "snapshot",
        "sales_scope": "PRIMARY",
        "metric": "fact_primary_sales.count"
    }
    with pytest.raises(IntentIncompleteError) as excinfo:
        validate_intent(raw_intent, catalog_manager)
    assert "time_range" in excinfo.value.missing_fields

def test_malformed_intent_structure(catalog_manager):
    # Invalid intent_type
    raw_intent = {
        "intent_type": "invalid_type",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "time_range": {"window": "last_30_days"},
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        }
    }
    with pytest.raises(MalformedIntentError):
        validate_intent(raw_intent, catalog_manager)

def test_valid_trend_intent(catalog_manager):
    raw_intent = {
        "intent_type": "trend",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        },
        "time_range": {"window": "last_year"}
    }
    intent = validate_intent(raw_intent, catalog_manager)
    assert intent.intent_type == "trend"
    assert intent.time_dimension.dimension == "fact_primary_sales.invoice_date"

def test_trend_requires_time_dimension(catalog_manager):
    raw_intent = {
        "intent_type": "trend",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "time_range": {"window": "last_year"}
        # Missing time_dimension
    }
    with pytest.raises(MalformedIntentError) as excinfo:
        validate_intent(raw_intent, catalog_manager)
    assert "TREND intent requires 'time_dimension'" in str(excinfo.value)

def test_invalid_time_window(catalog_manager):
    raw_intent = {
        "intent_type": "snapshot",
        "metric": "fact_primary_sales.count",
        "sales_scope": "PRIMARY",
        "time_range": {"window": "invalid_window"},
        "time_dimension": {
            "dimension": "fact_primary_sales.invoice_date",
            "granularity": "month"
        }
    }
    with pytest.raises(InvalidTimeWindowError):
        validate_intent(raw_intent, catalog_manager)
