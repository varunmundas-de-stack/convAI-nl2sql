import pytest
from pathlib import Path

from app.services.catalog_manager import CatalogManager
from app.services.intent_validator import validate_intent
from app.services.intent_errors import (
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
# Tests - Snapshot Intent
# -------------------------------------------------------------------

def test_valid_snapshot_intent(catalog):
    """Test basic snapshot intent validation."""
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "time_range": {"window": "last_7_days"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "snapshot"
    assert intent.metric == "total_quantity"


def test_valid_snapshot_with_group_by(catalog):
    """Test snapshot intent with dimensions."""
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "group_by": ["region", "brand"],
        "time_range": {"window": "month_to_date"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "snapshot"
    assert intent.group_by == ["region", "brand"]


# -------------------------------------------------------------------
# Tests - Trend Intent
# -------------------------------------------------------------------

def test_valid_trend_intent(catalog):
    """Test trend intent with time dimension and range."""
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


def test_trend_without_time_dimension_raises_error(catalog):
    """Test that trend intent requires time_dimension."""
    raw = {
        "intent_type": "trend",
        "metric": "total_quantity",
        "time_range": {"window": "last_7_days"},
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


# -------------------------------------------------------------------
# Tests - Comparison Intent
# -------------------------------------------------------------------

def test_valid_comparison_intent(catalog):
    """Test comparison intent (e.g., Primary vs Secondary sales)."""
    raw = {
        "intent_type": "comparison",
        "metric": "total_quantity",
        "group_by": ["sales_type"],
        "time_range": {"window": "last_30_days"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "comparison"
    assert intent.metric == "total_quantity"


def test_comparison_intent_with_filters(catalog):
    """Test comparison intent with filters."""
    raw = {
        "intent_type": "comparison",
        "metric": "transaction_count",
        "group_by": ["zone"],
        "filters": [
            {"dimension": "product_category", "operator": "equals", "value": "Beverages"}
        ],
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "comparison"
    assert len(intent.filters) == 1


# -------------------------------------------------------------------
# Tests - Ranking Intent
# -------------------------------------------------------------------

def test_valid_ranking_intent(catalog):
    """Test ranking intent (e.g., Top 5 products)."""
    raw = {
        "intent_type": "ranking",
        "metric": "total_quantity",
        "group_by": ["product_name"],
        "time_range": {"window": "last_30_days"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "ranking"
    assert "product_name" in intent.group_by


def test_ranking_without_group_by_raises_error(catalog):
    """Test that ranking intent requires group_by."""
    raw = {
        "intent_type": "ranking",
        "metric": "total_quantity",
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


def test_ranking_intent_with_filters(catalog):
    """Test ranking intent with region filter."""
    raw = {
        "intent_type": "ranking",
        "metric": "total_quantity",
        "group_by": ["territory_name"],
        "filters": [
            {"dimension": "region", "operator": "equals", "value": "South"},
            {"dimension": "sales_type", "operator": "equals", "value": "SECONDARY"},
        ],
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "ranking"
    assert len(intent.filters) == 2


# -------------------------------------------------------------------
# Tests - Distribution Intent
# -------------------------------------------------------------------

def test_valid_distribution_intent(catalog):
    """Test distribution intent (e.g., Sales by region)."""
    raw = {
        "intent_type": "distribution",
        "metric": "total_quantity",
        "group_by": ["region"],
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "distribution"
    assert intent.group_by == ["region"]


def test_distribution_without_group_by_raises_error(catalog):
    """Test that distribution intent requires group_by."""
    raw = {
        "intent_type": "distribution",
        "metric": "total_quantity",
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


def test_distribution_with_multiple_dimensions(catalog):
    """Test distribution intent with multiple dimensions."""
    raw = {
        "intent_type": "distribution",
        "metric": "transaction_count",
        "group_by": ["region", "outlet_type"],
        "time_range": {"window": "quarter_to_date"},
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "distribution"
    assert len(intent.group_by) == 2


# -------------------------------------------------------------------
# Tests - Drill Down Intent
# -------------------------------------------------------------------

def test_valid_drill_down_intent(catalog):
    """Test drill_down intent (hierarchical exploration)."""
    raw = {
        "intent_type": "drill_down",
        "metric": "total_quantity",
        "group_by": ["region", "state", "territory_name"],
    }

    intent = validate_intent(raw, catalog)

    assert intent.intent_type == "drill_down"
    assert len(intent.group_by) == 3


def test_drill_down_without_group_by_raises_error(catalog):
    """Test that drill_down intent requires group_by."""
    raw = {
        "intent_type": "drill_down",
        "metric": "total_quantity",
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


# -------------------------------------------------------------------
# Tests - Error Cases (Common)
# -------------------------------------------------------------------

def test_unknown_metric_raises_error(catalog):
    """Test that unknown metric raises UnknownMetricError."""
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
    """Test that unknown dimension raises UnknownDimensionError."""
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "group_by": ["fake_dimension"],
    }

    with pytest.raises(UnknownDimensionError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "UNKNOWN_DIMENSION"


def test_missing_metric_raises_malformed_intent(catalog):
    """Test that missing metric raises MalformedIntentError."""
    raw = {
        "intent_type": "snapshot"
    }

    with pytest.raises(MalformedIntentError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "MALFORMED_INTENT"


def test_invalid_time_window_raises_error(catalog):
    """Test that invalid time window raises InvalidTimeWindowError."""
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "time_range": {"window": "invalid_window"},
    }

    with pytest.raises(InvalidTimeWindowError) as exc:
        validate_intent(raw, catalog)

    assert exc.value.ERROR_CODE == "INVALID_TIME_WINDOW"


# -------------------------------------------------------------------
# Tests - Filters
# -------------------------------------------------------------------

def test_valid_intent_with_filters(catalog):
    """Test intent with valid filter."""
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


def test_intent_with_multiple_filters(catalog):
    """Test intent with multiple filters."""
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "filters": [
            {"dimension": "region", "operator": "equals", "value": "South"},
            {"dimension": "sales_type", "operator": "equals", "value": "PRIMARY"},
            {"dimension": "outlet_type", "operator": "equals", "value": "Kirana"},
        ],
    }

    intent = validate_intent(raw, catalog)

    assert len(intent.filters) == 3


def test_intent_with_in_operator_filter(catalog):
    """Test intent with 'in' operator filter."""
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
        "filters": [
            {"dimension": "region", "operator": "in", "value": ["North", "South"]},
        ],
    }

    intent = validate_intent(raw, catalog)

    assert intent.filters[0].operator == "in"
    assert intent.filters[0].value == ["North", "South"]


# -------------------------------------------------------------------
# Tests - Serialization
# -------------------------------------------------------------------

def test_error_to_dict_serialization(catalog):
    """Test that errors can be serialized to dict."""
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


# -------------------------------------------------------------------
# Tests - All Intent Types Validation
# -------------------------------------------------------------------

@pytest.mark.parametrize("intent_type", [
    "snapshot",
    "trend", 
    "comparison",
    "ranking",
    "distribution",
    "drill_down",
])
def test_all_intent_types_are_valid(catalog, intent_type):
    """Test that all catalog intent types are accepted."""
    # Build minimal valid intent for each type
    raw = {
        "intent_type": intent_type,
        "metric": "total_quantity",
    }
    
    # Add required fields based on intent type
    if intent_type == "trend":
        raw["time_dimension"] = {"dimension": "invoice_date", "granularity": "month"}
        raw["time_range"] = {"window": "last_30_days"}
    elif intent_type in ("ranking", "distribution", "drill_down"):
        raw["group_by"] = ["region"]
    
    intent = validate_intent(raw, catalog)
    
    assert intent.intent_type == intent_type

