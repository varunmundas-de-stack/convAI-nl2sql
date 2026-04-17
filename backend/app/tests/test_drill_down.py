"""
Tests for Drill-Down Feature: Hierarchy, Detection, and Mutation.

Covers:
- Hierarchy helper functions (get_axis, get_level, get_next_level, is_deeper)
- Time granularity helpers
- Drill detection (4 cases + fresh query)
- Drill mutation (group_by + filter changes)
- Axis constraint enforcement
"""

import pytest

from app.models.hierarchy import (
    get_axis,
    get_level,
    get_next_level,
    is_deeper,
    get_axis_dimensions,
    is_finer_granularity,
    get_next_granularity,
    all_hierarchy_dimensions,
    MAX_NON_TIME_AXES,
)
from app.services.intent.drill_detector import (
    detect_drill,
    apply_drill_mutation,
    DrillResult,
    _enforce_axis_limits,
)
from app.models.qco import QueryContextObject, QCOFilter, QCOMetric


# =============================================================================
# HELPERS: Build QCO for test scenarios
# =============================================================================

def _make_qco(
    metric="net_value",
    group_by=None,
    filters=None,
    time_granularity=None,
    active_hierarchies=None,
    sales_scope="SECONDARY",
    original_query="test query",
    intent_type="distribution",
):
    return QueryContextObject(
        original_query=original_query,
        intent_type=intent_type,
        sales_scope=sales_scope,
        metrics=[QCOMetric(name=metric, aggregation="sum")],
        group_by=group_by,
        time_granularity=time_granularity,
        filters=filters,
        active_hierarchies=active_hierarchies,
    )


# =============================================================================
# 1. HIERARCHY HELPER TESTS
# =============================================================================

class TestHierarchyHelpers:

    def test_get_axis_geography(self):
        assert get_axis("zone") == "geography"
        assert get_axis("state") == "geography"
        assert get_axis("city") == "geography"

    def test_get_axis_product(self):
        assert get_axis("category") == "product"
        assert get_axis("sub_category") == "product"
        assert get_axis("brand") == "product"
        assert get_axis("sku_code") == "product"

    def test_get_axis_unknown(self):
        assert get_axis("distributor_name") is None
        assert get_axis("unknown_dim") is None

    def test_get_level(self):
        assert get_level("zone") == 0
        assert get_level("state") == 1
        assert get_level("city") == 2
        assert get_level("category") == 0
        assert get_level("sku_code") == 3
        assert get_level("unknown") is None

    def test_get_next_level(self):
        assert get_next_level("zone") == "state"
        assert get_next_level("state") == "city"
        assert get_next_level("city") is None  # deepest
        assert get_next_level("category") == "sub_category"
        assert get_next_level("brand") == "sku_code"
        assert get_next_level("sku_code") is None  # deepest
        assert get_next_level("unknown") is None

    def test_is_deeper(self):
        assert is_deeper("state", "zone") is True
        assert is_deeper("city", "zone") is True
        assert is_deeper("zone", "state") is False
        assert is_deeper("zone", "zone") is False
        # Different axes
        assert is_deeper("brand", "zone") is False
        # Unknown
        assert is_deeper("unknown", "zone") is False

    def test_get_axis_dimensions(self):
        assert get_axis_dimensions("geography") == ["zone", "state", "city"]
        assert get_axis_dimensions("product") == ["category", "sub_category", "brand", "sku_code"]
        assert get_axis_dimensions("nonexistent") == []

    def test_all_hierarchy_dimensions(self):
        dims = all_hierarchy_dimensions()
        assert "zone" in dims
        assert "brand" in dims
        assert "distributor_name" not in dims


# =============================================================================
# 2. TIME GRANULARITY TESTS
# =============================================================================

class TestTimeGranularity:

    def test_is_finer_granularity(self):
        assert is_finer_granularity("week", "month") is True
        assert is_finer_granularity("day", "year") is True
        assert is_finer_granularity("month", "week") is False
        assert is_finer_granularity("month", "month") is False

    def test_get_next_granularity(self):
        assert get_next_granularity("year") == "quarter"
        assert get_next_granularity("month") == "week"
        assert get_next_granularity("day") is None  # finest
        assert get_next_granularity("unknown") is None


# =============================================================================
# 3. DRILL DETECTION TESTS
# =============================================================================

class TestDrillDetection:

    def test_no_previous_qco(self):
        """No previous context → fresh query."""
        result = detect_drill(
            {"metrics": [{"name": "net_value", "aggregation": "sum"}], "group_by": ["zone"]},
            None,
        )
        assert result.case == "none"

    def test_case_a_dimension_drill(self):
        """Previous group_by=zone, new group_by=state → dimension drill."""
        qco = _make_qco(group_by=["zone"], active_hierarchies={"geography": "zone"})
        intent = {
            "metrics": [{"name": "net_value", "aggregation": "sum"}],
            "group_by": ["state"],
        }
        result = detect_drill(intent, qco)
        assert result.case == "dimension_drill"
        assert result.drill_axis == "geography"
        assert result.prev_dimension == "zone"
        assert result.next_dimension == "state"

    def test_case_b_value_drill(self):
        """Previous group_by=zone, filter zone=South, no new group_by → value drill."""
        qco = _make_qco(group_by=["zone"], active_hierarchies={"geography": "zone"})
        intent = {
            "metrics": [{"name": "net_value", "aggregation": "sum"}],
            "group_by": [],
            "filters": [{"dimension": "zone", "operator": "equals", "value": "South"}],
        }
        result = detect_drill(intent, qco)
        assert result.case == "value_drill"
        assert result.drill_axis == "geography"
        assert result.prev_dimension == "zone"
        assert result.next_dimension == "state"
        assert result.drill_value == "South"

    def test_case_c_cross_axis(self):
        """Previous group_by=zone, new group_by=brand → cross-axis."""
        qco = _make_qco(group_by=["zone"], active_hierarchies={"geography": "zone"})
        intent = {
            "metrics": [{"name": "net_value", "aggregation": "sum"}],
            "group_by": ["brand"],
        }
        result = detect_drill(intent, qco)
        assert result.case == "cross_axis"
        assert result.drill_axis == "product"
        assert result.next_dimension == "brand"

    def test_case_d_time_change(self):
        """Previous granularity=month, new=week → time change."""
        qco = _make_qco(
            group_by=["zone"],
            time_granularity="month",
            intent_type="trend",
        )
        intent = {
            "metrics": [{"name": "net_value", "aggregation": "sum"}],
            "time": {"granularity": "week"},
        }
        result = detect_drill(intent, qco)
        assert result.case == "time_change"
        assert result.new_granularity == "week"

    def test_fresh_query_new_metric(self):
        """Different metric → fresh query, not a drill."""
        qco = _make_qco(metric="net_value", group_by=["zone"])
        intent = {
            "metrics": [{"name": "billed_qty", "aggregation": "sum"}],
            "group_by": ["state"],
        }
        result = detect_drill(intent, qco)
        assert result.case == "none"

    def test_cross_axis_rejected_at_max(self):
        """Already at max 2 axes → cross-axis not detected."""
        qco = _make_qco(
            group_by=["zone", "brand"],
            active_hierarchies={"geography": "zone", "product": "brand"},
        )
        intent = {
            "metrics": [{"name": "net_value", "aggregation": "sum"}],
            # Trying to add a 3rd axis (there's no 3rd axis in current config,
            # but the limit check still runs)
            "group_by": ["distributor_name"],  # not in any hierarchy
        }
        result = detect_drill(intent, qco)
        assert result.case == "none"


# =============================================================================
# 4. DRILL MUTATION TESTS
# =============================================================================

class TestDrillMutation:

    def test_mutation_case_a_replaces_group_by(self):
        """Dimension drill: zone → state, preserves brand."""
        qco = _make_qco(group_by=["zone", "brand"])
        drill = DrillResult(
            case="dimension_drill",
            drill_axis="geography",
            prev_dimension="zone",
            next_dimension="state",
        )
        intent = {"group_by": ["state"]}
        result = apply_drill_mutation(intent, qco, drill)
        assert "state" in result["group_by"]
        assert "brand" in result["group_by"]
        assert "zone" not in result["group_by"]

    def test_mutation_case_b_adds_filter(self):
        """Value drill: adds filter zone=South, group_by becomes state."""
        qco = _make_qco(group_by=["zone"])
        drill = DrillResult(
            case="value_drill",
            drill_axis="geography",
            prev_dimension="zone",
            next_dimension="state",
            drill_value="South",
        )
        intent = {"filters": [{"dimension": "zone", "operator": "equals", "value": "South"}]}
        result = apply_drill_mutation(intent, qco, drill)

        # Check filter was added
        filter_dims = [f["dimension"] for f in result["filters"]]
        assert "zone" in filter_dims

        # Check group_by
        assert result["group_by"] == ["state"]

    def test_mutation_case_c_cross_axis(self):
        """Cross-axis: zone + brand."""
        qco = _make_qco(group_by=["zone"])
        drill = DrillResult(
            case="cross_axis",
            drill_axis="product",
            prev_dimension=None,
            next_dimension="brand",
        )
        intent = {"group_by": ["brand"]}
        result = apply_drill_mutation(intent, qco, drill)
        assert set(result["group_by"]) == {"zone", "brand"}

    def test_mutation_case_d_time(self):
        """Time change: month → week."""
        qco = _make_qco(group_by=["zone"], time_granularity="month")
        drill = DrillResult(
            case="time_change",
            new_granularity="week",
        )
        intent = {"time": {"granularity": "month"}}
        result = apply_drill_mutation(intent, qco, drill)
        assert result["time"]["granularity"] == "week"
        # group_by preserved
        assert result["group_by"] == ["zone"]

    def test_mutation_preserves_other_axes(self):
        """Drill zone→state preserves existing brand axis."""
        qco = _make_qco(group_by=["zone", "brand"])
        drill = DrillResult(
            case="dimension_drill",
            drill_axis="geography",
            prev_dimension="zone",
            next_dimension="state",
        )
        intent = {"group_by": ["state"]}
        result = apply_drill_mutation(intent, qco, drill)
        assert "state" in result["group_by"]
        assert "brand" in result["group_by"]
        assert len(result["group_by"]) == 2


# =============================================================================
# 5. AXIS CONSTRAINT ENFORCEMENT TESTS
# =============================================================================

class TestAxisConstraints:

    def test_one_level_per_axis(self):
        """Same axis: keep deepest only."""
        result = _enforce_axis_limits(["zone", "state"])
        assert result == ["state"]

    def test_max_axes_enforced(self):
        """More than MAX_NON_TIME_AXES → trim to limit."""
        # We only have 2 axes defined, so this test validates the limit
        result = _enforce_axis_limits(["zone", "brand"])
        assert len(result) <= MAX_NON_TIME_AXES

    def test_non_hierarchy_dims_preserved(self):
        """Dimensions not in any hierarchy are kept as-is."""
        result = _enforce_axis_limits(["zone", "distributor_name"])
        assert "zone" in result
        assert "distributor_name" in result
