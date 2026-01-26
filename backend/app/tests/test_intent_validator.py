import pytest
from pathlib import Path

from backend.app.services.catalog_manager import CatalogManager
from backend.app.services.intent_validator import validate_intent
from backend.app.services.intent_errors import (
    UnknownMetricError,
    UnknownDimensionError,
    MalformedIntentError,
    InvalidTimeWindowError,
)

# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

@pytest.fixture(scope="session")
def catalog():
    catalog_path = (
        Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"
    )
    return CatalogManager(str(catalog_path))


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

def test_valid_snapshot_intent(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "time_range": {"window": "last_7_days"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "snapshot"
    assert intent.metric == "total_quantity"


def test_valid_trend_intent(catalog):
    raw = {
        "intent_type": "trend",
        "metric": "total_quantity",
        "group_by": ["region"],
        "time_dimension": {
            "dimension": "invoice_date",
            "granularity": "day",
        },
        "time_range": {"window": "last_30_days"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "trend"
    assert intent.time_dimension.granularity == "day"


def test_unknown_metric_raises_error(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "fake_metric_xyz",
    }

    with pytest.raises(UnknownMetricError) as exc:
        validate_intent(raw, catalog)

    error = exc.value
    assert error.ERROR_CODE == "UNKNOWN_METRIC"
    assert error.suggestions is not None


def test_unknown_dimension_raises_error(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "group_by": ["fake_dimension"],
    }

    with pytest.raises(UnknownDimensionError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "UNKNOWN_DIMENSION"


def test_missing_metric_raises_malformed_intent(catalog):
    raw = {
        "intent_type": "snapshot"
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


def test_invalid_time_window_raises_error(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "time_range": {"window": "invalid_window"},
    }

    with pytest.raises(InvalidTimeWindowError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "INVALID_TIME_WINDOW"


def test_trend_without_time_dimension_raises_error(catalog):
    raw = {
        "intent_type": "trend",
        "metric": "total_quantity",
        "time_range": {"window": "last_7_days"},
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


def test_valid_intent_with_filters(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "filters": [
            {
                "dimension": "region",
                "operator": "equals",
                "value": "North",
            }
        ],
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "snapshot"
    assert len(intent.filters) == 1
    assert intent.filters[0].dimension == "region"


def test_error_to_dict_serialization(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "fake_metric",
    }

    with pytest.raises(UnknownMetricError) as exc:
        validate_intent(raw, catalog)

    error_dict = exc.value.to_dict()

    assert error_dict["error_code"] == "UNKNOWN_METRIC"
    assert error_dict["error_type"] == "UnknownMetricError"
    assert error_dict["field"] == "metric"
    assert error_dict["value"] == "fake_metric"
