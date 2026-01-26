"""Pytest tests for CatalogManager with new catalog structure."""

import pytest
from pathlib import Path
from backend.app.services.catalog_manager import CatalogManager, CatalogError, AmbiguousResolutionError

CATALOG_PATH = str(Path(__file__).parent.parent.parent / "catalog" / "catalog.yaml")


@pytest.fixture
def catalog():
    """Fixture to load the catalog manager."""
    return CatalogManager(CATALOG_PATH)


class TestCatalogLoading:
    def test_catalog_loads_successfully(self, catalog):
        assert catalog is not None
        assert catalog.raw_catalog() is not None

    def test_required_sections_exist(self, catalog):
        raw = catalog.raw_catalog()
        assert "metrics" in raw
        assert "dimensions" in raw
        assert "time_dimensions" in raw


class TestMetrics:
    def test_list_metrics(self, catalog):
        metrics = catalog.list_metrics()
        assert len(metrics) > 0
        assert isinstance(metrics[0], dict)

    def test_list_metric_names(self, catalog):
        names = catalog.list_metric_names()
        assert "total_quantity" in names
        assert "transaction_count" in names

    def test_resolve_metric_by_name(self, catalog):
        metric = catalog.resolve_metric("total_quantity")
        assert metric["display_name"] == "Total Quantity Sold"
        assert metric["id"] == "sales_fact.quantity"

    def test_resolve_metric_by_alias(self, catalog):
        metric = catalog.resolve_metric("units sold")
        assert metric["name"] == "total_quantity"

    def test_get_metric_cube_field(self, catalog):
        field = catalog.get_metric_cube_field("transaction_count")
        assert field == "sales_fact.count"

    def test_invalid_metric_raises_error(self, catalog):
        with pytest.raises(CatalogError):
            catalog.resolve_metric("nonexistent_metric")


class TestDimensions:
    def test_list_dimensions(self, catalog):
        dims = catalog.list_dimensions()
        assert len(dims) > 0

    def test_resolve_dimension_by_name(self, catalog):
        dim = catalog.resolve_dimension("brand")
        assert dim["display_name"] == "Brand"
        assert dim["id"] == "skus.brand"

    def test_resolve_dimension_by_alias(self, catalog):
        dim = catalog.resolve_dimension("channel")  # alias for outlet_type
        assert dim["name"] == "outlet_type"

    def test_get_dimension_cube_field(self, catalog):
        field = catalog.get_dimension_cube_field("region")
        assert field == "territories.region"

    def test_invalid_dimension_raises_error(self, catalog):
        with pytest.raises(CatalogError):
            catalog.resolve_dimension("nonexistent_dim")


class TestTimeDimensions:
    def test_list_time_dimensions(self, catalog):
        tds = catalog.list_time_dimensions()
        assert len(tds) > 0

    def test_resolve_time_dimension(self, catalog):
        td = catalog.resolve_time_dimension("invoice_date")
        assert td["display_name"] == "Invoice Date"

    def test_get_time_dimension_granularities(self, catalog):
        granularities = catalog.get_time_dimension_granularities("invoice_date")
        names = [g["name"] for g in granularities]
        assert "day" in names
        assert "month" in names
        assert "year" in names


class TestTimeWindows:
    def test_list_time_windows(self, catalog):
        tws = catalog.list_time_windows()
        assert len(tws) > 0

    def test_resolve_time_window_by_name(self, catalog):
        tw = catalog.resolve_time_window("last_7_days")
        assert tw["display_name"] == "Last 7 Days"

    def test_resolve_time_window_by_alias(self, catalog):
        tw = catalog.resolve_time_window("MTD")
        assert tw["name"] == "month_to_date"


class TestValidation:
    def test_is_valid_metric(self, catalog):
        assert catalog.is_valid_metric("total_quantity") is True
        assert catalog.is_valid_metric("units sold") is True
        assert catalog.is_valid_metric("fake_metric") is False

    def test_is_valid_dimension(self, catalog):
        assert catalog.is_valid_dimension("brand") is True
        assert catalog.is_valid_dimension("channel") is True
        assert catalog.is_valid_dimension("fake_dim") is False


class TestSearch:
    def test_search_metrics(self, catalog):
        results = catalog.search_metrics("quantity")
        assert len(results) >= 1

    def test_search_dimensions(self, catalog):
        results = catalog.search_dimensions("store")
        assert len(results) >= 1


class TestPriorityFiltering:
    def test_high_priority_metrics(self, catalog):
        high = catalog.get_high_priority_metrics()
        assert all(m["priority"] == "high" for m in high)

    def test_filterable_dimensions(self, catalog):
        filterable = catalog.get_filterable_dimensions()
        assert all(d.get("filterable", False) for d in filterable)


class TestNewSections:
    def test_intent_types(self, catalog):
        intents = catalog.list_intent_types()
        assert len(intents) > 0
        names = [i["name"] for i in intents]
        assert "snapshot" in names
        assert "trend" in names

    def test_comparison_types(self, catalog):
        comps = catalog.list_comparison_types()
        assert len(comps) > 0

    def test_visualization_types(self, catalog):
        viz = catalog.list_visualization_types()
        assert len(viz) > 0

    def test_business_rules(self, catalog):
        rules = catalog.get_business_rules()
        assert len(rules) > 0

    def test_query_patterns(self, catalog):
        patterns = catalog.get_query_patterns()
        assert len(patterns) > 0


class TestCaseInsensitivity:
    """Test that lookups are case-insensitive."""

    def test_metric_lookup_case_insensitive(self, catalog):
        """Metrics should be found regardless of case."""
        # Lowercase
        m1 = catalog.resolve_metric("total_quantity")
        # Uppercase
        m2 = catalog.resolve_metric("TOTAL_QUANTITY")
        # Mixed case
        m3 = catalog.resolve_metric("Total_Quantity")
        
        assert m1["id"] == m2["id"] == m3["id"]

    def test_dimension_lookup_case_insensitive(self, catalog):
        """Dimensions should be found regardless of case."""
        d1 = catalog.resolve_dimension("brand")
        d2 = catalog.resolve_dimension("BRAND")
        d3 = catalog.resolve_dimension("Brand")
        
        assert d1["id"] == d2["id"] == d3["id"]

    def test_alias_lookup_case_insensitive(self, catalog):
        """Aliases should be found regardless of case."""
        d1 = catalog.resolve_dimension("channel")
        d2 = catalog.resolve_dimension("CHANNEL")
        d3 = catalog.resolve_dimension("Channel")
        
        assert d1["name"] == d2["name"] == d3["name"]

    def test_time_window_alias_case_insensitive(self, catalog):
        """Time window aliases should be case-insensitive."""
        tw1 = catalog.resolve_time_window("mtd")
        tw2 = catalog.resolve_time_window("MTD")
        tw3 = catalog.resolve_time_window("Mtd")
        
        assert tw1["name"] == tw2["name"] == tw3["name"]

    def test_is_valid_case_insensitive(self, catalog):
        """Validation methods should be case-insensitive."""
        assert catalog.is_valid_metric("TOTAL_QUANTITY") is True
        assert catalog.is_valid_dimension("BRAND") is True
        assert catalog.is_valid_time_window("MTD") is True


class TestAliasCollisions:
    """Test that alias collisions are properly detected and don't silently pick one."""

    def test_unique_aliases_resolve_unambiguously(self, catalog):
        """Unique aliases should resolve to exactly one item."""
        # "units sold" is unique to total_quantity metric
        result = catalog.resolve_metric_safe("units sold")
        assert result.is_ambiguous is False
        assert result.item is not None
        assert result.item["name"] == "total_quantity"

    def test_find_returns_all_matches(self, catalog):
        """find_* methods should return all matches for a term."""
        # Check that find_metrics returns a list
        matches = catalog.find_metrics("transaction_count")
        assert isinstance(matches, list)
        assert len(matches) >= 1

    def test_safe_resolve_returns_resolution_result(self, catalog):
        """Safe resolve methods should return ResolutionResult objects."""
        result = catalog.resolve_metric_safe("total_quantity")
        
        assert hasattr(result, 'is_ambiguous')
        assert hasattr(result, 'is_found')
        assert hasattr(result, 'all_matches')
        assert hasattr(result, 'item_type')

    def test_invalid_term_returns_empty_matches(self, catalog):
        """Invalid terms should return empty matches, not error."""
        matches = catalog.find_metrics("completely_fake_metric_xyz")
        assert matches == []
        
        result = catalog.resolve_metric_safe("completely_fake_metric_xyz")
        assert result.is_found is False
        assert result.is_ambiguous is False

    def test_cross_type_collision_detection(self, catalog):
        """Should detect when a term exists in multiple catalog types."""
        # Check the method exists and works
        # (Actual collisions depend on catalog data)
        has_collision = catalog.has_cross_type_collision("nonexistent_term")
        assert has_collision is False  # Non-existent term has no collision
        
        # get_cross_type_matches should return dict
        matches = catalog.get_cross_type_matches("brand")
        assert isinstance(matches, dict)
        # "brand" should be in dimensions
        assert "dimension" in matches

    def test_unambiguous_check_methods(self, catalog):
        """is_unambiguous_* methods should correctly identify unique resolutions."""
        # Known unique metric
        assert catalog.is_unambiguous_metric("total_quantity") is True
        # Invalid metric
        assert catalog.is_unambiguous_metric("fake_metric") is False
        
        # Known unique dimension
        assert catalog.is_unambiguous_dimension("brand") is True


class TestAmbiguityHandling:
    """Test the ambiguity handling mechanisms."""

    def test_resolve_safe_does_not_raise(self, catalog):
        """resolve_*_safe methods should never raise, even for ambiguous terms."""
        # These should not raise
        catalog.resolve_metric_safe("anything")
        catalog.resolve_dimension_safe("anything")
        catalog.resolve_time_dimension_safe("anything")
        catalog.resolve_time_window_safe("anything")

    def test_resolution_result_properties(self, catalog):
        """ResolutionResult should have correct properties."""
        result = catalog.resolve_metric_safe("total_quantity")
        
        assert result.is_found is True
        assert result.is_ambiguous is False
        assert result.item is not None
        assert result.item_type == "metric"
        assert len(result.all_matches) == 1

    def test_not_found_resolution_result(self, catalog):
        """Not found terms should return proper ResolutionResult."""
        result = catalog.resolve_metric_safe("xyz_not_found_123")
        
        assert result.is_found is False
        assert result.is_ambiguous is False
        assert result.item is None
        assert result.all_matches == []
