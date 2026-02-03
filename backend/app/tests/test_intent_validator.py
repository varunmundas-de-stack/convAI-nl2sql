import pytest
from pathlib import Path

from app.services.catalog_manager import CatalogManager
from app.services.intent_validator import validate_intent
from app.services.intent_errors import (
    UnknownMetricError,
    UnknownDimensionError,
    UnknownTimeDimensionError,
    InvalidTimeWindowError,
    InvalidGranularityError,
    MalformedIntentError,
)

CATALOG_PATH = Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"


@pytest.fixture(scope="session")
def catalog():
    return CatalogManager(str(CATALOG_PATH))


# ------------------------------------------------------------------
# SNAPSHOT
# ------------------------------------------------------------------

def test_valid_snapshot_intent(catalog):
    """Test a valid snapshot intent with the new schema."""
    raw = {
        "intent_type": "snapshot",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "time_range": {"window": "last_7_days"},
    }

    intent = validate_intent(raw, catalog)
    assert intent.metric == "fact_secondary_sales.billed_qty"


def test_unknown_metric_raises(catalog):
    """Test that non-catalog metrics are rejected."""
    raw = {
        "intent_type": "snapshot",
        "sales_scope": "SECONDARY",
        "metric": "total_quantity",
    }

    with pytest.raises(UnknownMetricError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# GROUP BY
# ------------------------------------------------------------------

def test_valid_group_by(catalog):
    """Test valid group_by with new schema dimensions."""
    raw = {
        "intent_type": "ranking",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "group_by": ["fact_secondary_sales.zone"],
    }

    intent = validate_intent(raw, catalog)
    assert intent.group_by == ["fact_secondary_sales.zone"]


def test_unknown_group_by_dimension(catalog):
    """Test that non-catalog dimensions are rejected."""
    raw = {
        "intent_type": "ranking",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "group_by": ["region"],
    }

    with pytest.raises(UnknownDimensionError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# TREND
# ------------------------------------------------------------------

def test_valid_trend_intent(catalog):
    """Test a valid trend intent with new schema."""
    raw = {
        "intent_type": "trend",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.net_value",
        "time_dimension": {
            "dimension": "fact_secondary_sales.invoice_date",
            "granularity": "month",
        },
        "time_range": {"window": "last_30_days"},
    }

    intent = validate_intent(raw, catalog)
    assert intent.time_dimension.granularity == "month"


def test_trend_missing_time_dimension(catalog):
    """Test that trend intent requires time_dimension."""
    raw = {
        "intent_type": "trend",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
    }

    with pytest.raises(MalformedIntentError):
        validate_intent(raw, catalog)


def test_invalid_time_dimension(catalog):
    """Test that non-normalized time dimensions are rejected."""
    raw = {
        "intent_type": "trend",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "time_dimension": {
            "dimension": "invoice_date",  # Not normalized
            "granularity": "month",
        },
        "time_range": {"window": "last_30_days"},
    }

    with pytest.raises(UnknownTimeDimensionError):
        validate_intent(raw, catalog)


def test_invalid_granularity(catalog):
    """Test that invalid granularities are rejected."""
    raw = {
        "intent_type": "trend",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "time_dimension": {
            "dimension": "fact_secondary_sales.invoice_date",
            "granularity": "hour",  # Not a valid granularity
        },
        "time_range": {"window": "last_30_days"},
    }

    with pytest.raises(MalformedIntentError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# FILTERS
# ------------------------------------------------------------------

def test_valid_filter(catalog):
    """Test valid filter with new schema dimensions."""
    raw = {
        "intent_type": "snapshot",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "filters": [
            {
                "dimension": "fact_secondary_sales.zone",
                "operator": "equals",
                "value": "South-1",
            }
        ],
    }

    intent = validate_intent(raw, catalog)
    assert len(intent.filters) == 1


def test_invalid_filter_dimension(catalog):
    """Test that non-catalog filter dimensions are rejected."""
    raw = {
        "intent_type": "snapshot",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "filters": [
            {
                "dimension": "region",  # Not in catalog
                "operator": "equals",
                "value": "South",
            }
        ],
    }

    with pytest.raises(Exception):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# TIME WINDOW
# ------------------------------------------------------------------

def test_invalid_time_window(catalog):
    """Test that non-catalog time windows are rejected."""
    raw = {
        "intent_type": "snapshot",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "time_range": {"window": "MTD"},  # Should be "month_to_date"
    }

    with pytest.raises(InvalidTimeWindowError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# RANKING WITH LIMIT
# ------------------------------------------------------------------

def test_ranking_with_limit(catalog):
    """Test ranking intent with limit field (top N)."""
    raw = {
        "intent_type": "ranking",
        "sales_scope": "SECONDARY",
        "metric": "fact_secondary_sales.billed_qty",
        "group_by": ["fact_secondary_sales.zone"],
        "limit": 5,
    }

    intent = validate_intent(raw, catalog)
    assert intent.limit == 5
