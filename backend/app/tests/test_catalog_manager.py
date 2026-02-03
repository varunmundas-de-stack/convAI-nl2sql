import pytest
from pathlib import Path
from app.services.catalog_manager import CatalogManager

CATALOG_PATH = Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml"


@pytest.fixture(scope="session")
def catalog():
    return CatalogManager(str(CATALOG_PATH))


def test_catalog_loads(catalog):
    assert catalog is not None


def test_valid_metric_id(catalog):
    """Test valid metrics from the new flat schema."""
    assert catalog.is_valid_metric("fact_secondary_sales.billed_qty")
    assert catalog.is_valid_metric("fact_secondary_sales.net_value")
    assert catalog.is_valid_metric("fact_primary_sales.gross_value")
    assert catalog.is_valid_metric("fact_secondary_sales.count")


def test_invalid_metric_id(catalog):
    """Test that old/non-existent metrics are rejected."""
    assert not catalog.is_valid_metric("total_quantity")
    assert not catalog.is_valid_metric("sales_fact.quantity")
    assert not catalog.is_valid_metric("fake.metric")


def test_valid_dimension_id(catalog):
    """Test valid dimensions from the new flat schema."""
    assert catalog.is_valid_dimension("fact_secondary_sales.zone")
    assert catalog.is_valid_dimension("fact_secondary_sales.brand")
    assert catalog.is_valid_dimension("fact_secondary_sales.distributor_name")
    assert catalog.is_valid_dimension("fact_primary_sales.state")


def test_invalid_dimension_id(catalog):
    """Test that old/non-existent dimensions are rejected."""
    assert not catalog.is_valid_dimension("region")
    assert not catalog.is_valid_dimension("territories.region")
    assert not catalog.is_valid_dimension("fake.dimension")


def test_valid_time_dimension(catalog):
    """Test valid time dimensions from the new schema."""
    assert catalog.is_valid_time_dimension("fact_secondary_sales.invoice_date")
    assert catalog.is_valid_time_dimension("fact_primary_sales.invoice_date")


def test_time_dimension_granularities(catalog):
    """Test that time dimensions have correct granularities."""
    granularities = catalog.get_time_granularities("fact_secondary_sales.invoice_date")
    assert "day" in granularities
    assert "month" in granularities
    assert "year" in granularities


def test_valid_time_window(catalog):
    """Test valid time windows."""
    assert catalog.is_valid_time_window("last_7_days")
    assert catalog.is_valid_time_window("month_to_date")
    assert catalog.is_valid_time_window("last_30_days")


def test_invalid_time_window(catalog):
    """Test that invalid time windows are rejected."""
    assert not catalog.is_valid_time_window("MTD")
    assert not catalog.is_valid_time_window("fake_window")
