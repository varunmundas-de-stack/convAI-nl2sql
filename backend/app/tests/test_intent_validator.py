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
    raw = {
        "intent_type": "snapshot",
        "metric": "sales_fact.quantity",
        "time_range": {"window": "last_7_days"},
    }

    intent = validate_intent(raw, catalog)
    assert intent.metric == "sales_fact.quantity"


def test_unknown_metric_raises(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "total_quantity",
    }

    with pytest.raises(UnknownMetricError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# GROUP BY
# ------------------------------------------------------------------

def test_valid_group_by(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "sales_fact.quantity",
        "group_by": ["territories.region"],
    }

    intent = validate_intent(raw, catalog)
    assert intent.group_by == ["territories.region"]


def test_unknown_group_by_dimension(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "sales_fact.quantity",
        "group_by": ["region"],
    }

    with pytest.raises(UnknownDimensionError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# TREND
# ------------------------------------------------------------------

def test_valid_trend_intent(catalog):
    raw = {
        "intent_type": "trend",
        "metric": "sales_fact.quantity",
        "time_dimension": {
            "dimension": "sales_fact.invoice_date",
            "granularity": "month",
        },
        "time_range": {"window": "last_30_days"},
    }

    intent = validate_intent(raw, catalog)
    assert intent.time_dimension.granularity == "month"


def test_trend_missing_time_dimension(catalog):
    raw = {
        "intent_type": "trend",
        "metric": "sales_fact.quantity",
    }

    with pytest.raises(MalformedIntentError):
        validate_intent(raw, catalog)


def test_invalid_time_dimension(catalog):
    raw = {
        "intent_type": "trend",
        "metric": "sales_fact.quantity",
        "time_dimension": {
            "dimension": "invoice_date",
            "granularity": "month",
        },
        "time_range": {"window": "last_30_days"},
    }

    with pytest.raises(UnknownTimeDimensionError):
        validate_intent(raw, catalog)


def test_invalid_granularity(catalog):
    raw = {
        "intent_type": "trend",
        "metric": "sales_fact.quantity",
        "time_dimension": {
            "dimension": "sales_fact.invoice_date",
            "granularity": "hour",
        },
        "time_range": {"window": "last_30_days"},
    }

    with pytest.raises(MalformedIntentError):
        validate_intent(raw, catalog)


# ------------------------------------------------------------------
# FILTERS
# ------------------------------------------------------------------

def test_valid_filter(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "sales_fact.quantity",
        "filters": [
            {
                "dimension": "territories.region",
                "operator": "equals",
                "value": "South",
            }
        ],
    }

    intent = validate_intent(raw, catalog)
    assert len(intent.filters) == 1


def test_invalid_filter_dimension(catalog):
    raw = {
        "intent_type": "snapshot",
        "metric": "sales_fact.quantity",
        "filters": [
            {
                "dimension": "region",
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
    raw = {
        "intent_type": "snapshot",
        "metric": "sales_fact.quantity",
        "time_range": {"window": "MTD"},
    }

    with pytest.raises(InvalidTimeWindowError):
        validate_intent(raw, catalog)
