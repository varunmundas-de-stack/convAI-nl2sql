"""
Tests for Period & Growth Execution:
- PeriodPlanner.determine_strategy decision tree
- GrowthComputer: row-wise growth, dual-query merge, contribution %
"""

import pytest
from app.models.intent import Intent, Metric, TimeSpec, PostProcessing, ComparisonSpec
from app.services.cube.period_planner import QueryStrategy, determine_strategy
from app.services.growth_computer import (
    compute_row_wise_growth,
    merge_and_compute_growth,
    compute_contribution,
    GROWTH_KEY,
    PREVIOUS_KEY,
    CONTRIBUTION_KEY,
)


# =============================================================================
# HELPERS
# =============================================================================

def _make_intent(
    derived_metric=None,
    comparison_type="none",
    comparison_window=None,
    window="last_30_days",
    start_date=None,
    end_date=None,
    granularity="week",
    group_by=None,
):
    """Build a minimal valid-ish Intent for testing period_planner."""
    pp = PostProcessing(
        derived_metric=derived_metric,
        comparison=ComparisonSpec(type=comparison_type, comparison_window=comparison_window),
    )
    time = TimeSpec(
        dimension="fact_secondary_sales.invoice_date",
        window=window,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
    )
    return Intent(
        metrics=[Metric(name="fact_secondary_sales.net_value")],
        time=time,
        post_processing=pp,
        group_by=group_by,
    )


# =============================================================================
# PERIOD PLANNER TESTS
# =============================================================================

class TestDetermineStrategy:

    def test_wow_growth_rolling_window_is_single_time_series(self):
        intent = _make_intent(derived_metric="wow_growth", window="last_30_days")
        assert determine_strategy(intent) == QueryStrategy.SINGLE_TIME_SERIES

    def test_mom_growth_rolling_window_is_single_time_series(self):
        intent = _make_intent(derived_metric="mom_growth", window="last_90_days", granularity="month")
        assert determine_strategy(intent) == QueryStrategy.SINGLE_TIME_SERIES

    def test_yoy_growth_rolling_window_is_single_time_series(self):
        intent = _make_intent(derived_metric="yoy_growth", window="last_year", granularity="year")
        assert determine_strategy(intent) == QueryStrategy.SINGLE_TIME_SERIES

    def test_period_change_rolling_window_is_single_time_series(self):
        intent = _make_intent(derived_metric="period_change", window="last_7_days")
        assert determine_strategy(intent) == QueryStrategy.SINGLE_TIME_SERIES

    def test_wow_growth_month_to_date_is_dual_query(self):
        intent = _make_intent(derived_metric="wow_growth", window="month_to_date")
        assert determine_strategy(intent) == QueryStrategy.DUAL_QUERY

    def test_wow_growth_custom_dates_is_dual_query(self):
        intent = _make_intent(
            derived_metric="wow_growth",
            window=None,
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        assert determine_strategy(intent) == QueryStrategy.DUAL_QUERY

    def test_mom_growth_comparison_window_non_contiguous_is_dual(self):
        # comparison_window is a to-date window → dual
        intent = _make_intent(
            derived_metric="mom_growth",
            window="last_30_days",
            comparison_window="month_to_date",
        )
        assert determine_strategy(intent) == QueryStrategy.DUAL_QUERY

    def test_contribution_percent_is_contribution(self):
        intent = _make_intent(derived_metric="contribution_percent")
        assert determine_strategy(intent) == QueryStrategy.CONTRIBUTION

    def test_period_comparison_rolling_is_single_time_series(self):
        intent = _make_intent(
            comparison_type="period",
            comparison_window="last_month",
            window="last_30_days",
        )
        assert determine_strategy(intent) == QueryStrategy.SINGLE_TIME_SERIES

    def test_period_comparison_mtd_is_dual_query(self):
        intent = _make_intent(
            comparison_type="period",
            comparison_window="last_month",
            window="month_to_date",
        )
        assert determine_strategy(intent) == QueryStrategy.DUAL_QUERY

    def test_no_growth_no_comparison_is_single_query(self):
        intent = _make_intent()
        assert determine_strategy(intent) == QueryStrategy.SINGLE_QUERY

    def test_dimension_comparison_is_single_query(self):
        intent = _make_intent(comparison_type="dimension")
        assert determine_strategy(intent) == QueryStrategy.SINGLE_QUERY


# =============================================================================
# GROWTH COMPUTER TESTS
# =============================================================================

METRIC = "fact_secondary_sales.net_value"
TIME_COL = "fact_secondary_sales.invoice_date.week"


class TestComputeRowWiseGrowth:

    def test_first_row_has_no_growth(self):
        data = [
            {METRIC: "100", TIME_COL: "2024-01-01"},
            {METRIC: "120", TIME_COL: "2024-01-08"},
        ]
        result = compute_row_wise_growth(data, METRIC, TIME_COL)
        assert result[0][GROWTH_KEY] is None

    def test_correct_growth_calculation(self):
        data = [
            {METRIC: "100", TIME_COL: "2024-01-01"},
            {METRIC: "120", TIME_COL: "2024-01-08"},
        ]
        result = compute_row_wise_growth(data, METRIC, TIME_COL)
        assert result[1][GROWTH_KEY] == pytest.approx(0.20)

    def test_negative_growth(self):
        data = [
            {METRIC: "200", TIME_COL: "2024-01-01"},
            {METRIC: "150", TIME_COL: "2024-01-08"},
        ]
        result = compute_row_wise_growth(data, METRIC, TIME_COL)
        assert result[1][GROWTH_KEY] == pytest.approx(-0.25)

    def test_division_by_zero_returns_none(self):
        data = [
            {METRIC: "0", TIME_COL: "2024-01-01"},
            {METRIC: "100", TIME_COL: "2024-01-08"},
        ]
        result = compute_row_wise_growth(data, METRIC, TIME_COL)
        assert result[1][GROWTH_KEY] is None

    def test_sorts_ascending_regardless_of_input_order(self):
        data = [
            {METRIC: "120", TIME_COL: "2024-01-08"},
            {METRIC: "100", TIME_COL: "2024-01-01"},  # out of order
        ]
        result = compute_row_wise_growth(data, METRIC, TIME_COL)
        # After sorting, row 0 is 2024-01-01 (100), row 1 is 2024-01-08 (120)
        assert result[0][GROWTH_KEY] is None
        assert result[1][GROWTH_KEY] == pytest.approx(0.20)

    def test_empty_data_returns_empty(self):
        assert compute_row_wise_growth([], METRIC, TIME_COL) == []

    def test_single_row_has_no_growth(self):
        data = [{METRIC: "100", TIME_COL: "2024-01-01"}]
        result = compute_row_wise_growth(data, METRIC, TIME_COL)
        assert len(result) == 1
        assert result[0][GROWTH_KEY] is None


class TestMergeAndComputeGrowth:

    GROUP = "fact_secondary_sales.zone"

    def test_correct_growth_for_matching_keys(self):
        data_a = [{METRIC: "120", self.GROUP: "North"}]
        data_b = [{METRIC: "100", self.GROUP: "North"}]
        result = merge_and_compute_growth(data_a, data_b, METRIC, [self.GROUP])
        assert result[0][GROWTH_KEY] == pytest.approx(0.20)
        assert result[0][PREVIOUS_KEY] == pytest.approx(100.0)

    def test_missing_key_in_comparison_treated_as_zero(self):
        data_a = [{METRIC: "120", self.GROUP: "South"}]
        data_b = []  # South absent → previous = 0
        result = merge_and_compute_growth(data_a, data_b, METRIC, [self.GROUP])
        assert result[0][PREVIOUS_KEY] == 0.0
        assert result[0][GROWTH_KEY] is None  # div by zero

    def test_multiple_groups(self):
        data_a = [
            {METRIC: "120", self.GROUP: "North"},
            {METRIC: "90", self.GROUP: "South"},
        ]
        data_b = [
            {METRIC: "100", self.GROUP: "North"},
            {METRIC: "100", self.GROUP: "South"},
        ]
        result = merge_and_compute_growth(data_a, data_b, METRIC, [self.GROUP])
        north = next(r for r in result if r[self.GROUP] == "North")
        south = next(r for r in result if r[self.GROUP] == "South")
        assert north[GROWTH_KEY] == pytest.approx(0.20)
        assert south[GROWTH_KEY] == pytest.approx(-0.10)

    def test_empty_data_a_returns_empty(self):
        result = merge_and_compute_growth([], [{METRIC: "100"}], METRIC, [self.GROUP])
        assert result == []


class TestComputeContribution:

    GROUP = "fact_secondary_sales.brand"

    def test_contribution_sums_correctly(self):
        data = [
            {METRIC: "60", self.GROUP: "BrandA"},
            {METRIC: "40", self.GROUP: "BrandB"},
        ]
        total_data = [{METRIC: "100"}]
        result = compute_contribution(data, total_data, METRIC)
        brand_a = next(r for r in result if r[self.GROUP] == "BrandA")
        brand_b = next(r for r in result if r[self.GROUP] == "BrandB")
        assert brand_a[CONTRIBUTION_KEY] == pytest.approx(60.0)
        assert brand_b[CONTRIBUTION_KEY] == pytest.approx(40.0)

    def test_zero_total_returns_none(self):
        data = [{METRIC: "60", self.GROUP: "BrandA"}]
        total_data = [{METRIC: "0"}]
        result = compute_contribution(data, total_data, METRIC)
        assert result[0][CONTRIBUTION_KEY] is None

    def test_empty_total_data_means_zero_total(self):
        data = [{METRIC: "60", self.GROUP: "BrandA"}]
        result = compute_contribution(data, [], METRIC)
        assert result[0][CONTRIBUTION_KEY] is None

    def test_empty_data_returns_empty(self):
        result = compute_contribution([], [{METRIC: "100"}], METRIC)
        assert result == []
