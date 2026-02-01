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
    assert catalog.is_valid_metric("sales_fact.quantity")
    assert catalog.is_valid_metric("sales_fact.count")


def test_invalid_metric_id(catalog):
    assert not catalog.is_valid_metric("total_quantity")
    assert not catalog.is_valid_metric("fake.metric")


def test_valid_dimension_id(catalog):
    assert catalog.is_valid_dimension("territories.region")
    assert catalog.is_valid_dimension("skus.brand")


def test_invalid_dimension_id(catalog):
    assert not catalog.is_valid_dimension("region")
    assert not catalog.is_valid_dimension("fake.dimension")


def test_valid_time_dimension(catalog):
    assert catalog.is_valid_time_dimension("sales_fact.invoice_date")


def test_time_dimension_granularities(catalog):
    granularities = catalog.get_time_granularities("sales_fact.invoice_date")
    assert "day" in granularities
    assert "month" in granularities
    assert "year" in granularities


def test_valid_time_window(catalog):
    assert catalog.is_valid_time_window("last_7_days")
    assert catalog.is_valid_time_window("month_to_date")


def test_invalid_time_window(catalog):
    assert not catalog.is_valid_time_window("MTD")
    assert not catalog.is_valid_time_window("fake_window")
