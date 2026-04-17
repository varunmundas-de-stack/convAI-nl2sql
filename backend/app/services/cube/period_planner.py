"""
Period Planner - Decides the Cube query strategy for period/growth queries.

INPUT:  Validated Intent
OUTPUT: QueryStrategy enum value

Decision tree (in priority order):
1. derived_metric in growth_metrics → check contiguous/equal → SINGLE_TIME_SERIES or DUAL_QUERY
2. derived_metric == contribution_percent → CONTRIBUTION
3. comparison.type == "period" → check contiguous/equal → SINGLE_TIME_SERIES or DUAL_QUERY
4. Otherwise → SINGLE_QUERY

Contiguous + equal-size means:
- Named rolling window (last_7_days, last_30_days, last_year, etc.)
- NOT a "to-date" partial window (month_to_date, quarter_to_date, year_to_date)
- NOT custom explicit dates (start_date/end_date set)
"""

from enum import Enum
from typing import Optional

from app.models.intent import Intent


# =============================================================================
# QUERY STRATEGY ENUM
# =============================================================================

class QueryStrategy(str, Enum):
    SINGLE_QUERY       = "single_query"       # Standard: one Cube call, no post-processing
    SINGLE_TIME_SERIES = "single_time_series" # One Cube call, row-wise growth between buckets
    DUAL_QUERY         = "dual_query"         # Two Cube calls, merge + growth computation
    CONTRIBUTION       = "contribution"       # Two Cube calls: grouped + ungrouped total


# =============================================================================
# CONSTANTS
# =============================================================================

# Derived metrics that require growth computation
GROWTH_METRICS = {"wow_growth", "mom_growth", "yoy_growth", "period_change"}

# Time windows that are partial/asymmetric — never contiguous with a symmetric window
NON_CONTIGUOUS_WINDOWS = {
    "month_to_date",
    "quarter_to_date",
    "year_to_date",
    "today",
    "yesterday",
}


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def determine_strategy(intent: Intent) -> QueryStrategy:
    """
    Determine the Cube query execution strategy from a validated Intent.

    Args:
        intent: Validated Intent object (post-normalization)

    Returns:
        QueryStrategy enum value
    """
    pp = intent.post_processing
    derived = pp.derived_metric if pp else None
    comparison = pp.comparison if pp else None

    # 1. Growth metrics
    if derived in GROWTH_METRICS:
        if _periods_contiguous_and_equal(intent):
            return QueryStrategy.SINGLE_TIME_SERIES
        return QueryStrategy.DUAL_QUERY

    # 2. Contribution percent
    if derived == "contribution_percent":
        return QueryStrategy.CONTRIBUTION

    # 3. Period comparison (no derived metric, but explicit comparison.type == "period")
    if comparison and comparison.type == "period":
        if _periods_contiguous_and_equal(intent):
            return QueryStrategy.SINGLE_TIME_SERIES
        return QueryStrategy.DUAL_QUERY

    # 4. Default: single Cube query
    return QueryStrategy.SINGLE_QUERY


def transform_intent_for_strategy(intent: Intent, strategy: QueryStrategy) -> Intent:
    """
    Mutate intent fields to satisfy the requirements of the selected strategy.

    Pipeline position:
        Intent → determine_strategy() → transform_intent_for_strategy()  ← HERE
        → build_cube_query() → execute → post_process_by_strategy()

    Mutations per strategy:

    SINGLE_TIME_SERIES
        1. Expand window  — double it so Cube returns ≥2 buckets to compare
           last_7_days → last_14_days  |  last_30_days → last_60_days
           last_month  → last_2_months |  last_year    → last_2_years
        2. Inject granularity — derived from derived_metric
           wow_growth → week  |  mom_growth → month  |  yoy_growth → year
        3. Override order — time dimension ascending (not metric descending)

    DUAL_QUERY
        1. Normalize freeform comparison_window strings
           'last week' → 'last_7_days'  |  'last month' → 'last_month'

    Returns:
        A new Intent instance with mutations applied (original is not modified).
    """
    import logging
    _log = logging.getLogger(__name__)

    # Work on a deep copy so original validated intent is never mutated
    intent = intent.model_copy(deep=True)

    if strategy == QueryStrategy.SINGLE_TIME_SERIES:
        intent = _transform_single_time_series(intent, _log)

    elif strategy == QueryStrategy.DUAL_QUERY:
        intent = _normalize_comparison_window(intent, _log)

    elif strategy == QueryStrategy.CONTRIBUTION:
        if not intent.group_by:
            _log.warning(
                "CONTRIBUTION strategy but intent has no group_by — "
                "contribution percentages will be meaningless"
            )

    return intent


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

# ---------------------------------------------------------------------------
# Window expansion map: primary window → doubled coverage window
# ---------------------------------------------------------------------------
_EXPAND_WINDOW: dict[str, str] = {
    "last_7_days":  "last_14_days",
    "last_14_days": "last_28_days",
    "last_30_days": "last_60_days",
    "last_60_days": "last_120_days",
    "last_90_days": "last_180_days",
    "last_month":   "last_2_months",
    "last_quarter": "last_2_quarters",
    "last_year":    "last_2_years",
}

# ---------------------------------------------------------------------------
# Granularity inferred from the derived_metric
# ---------------------------------------------------------------------------
_DERIVED_TO_GRANULARITY: dict[str, str] = {
    "wow_growth":    "week",
    "mom_growth":    "month",
    "yoy_growth":    "year",
    "period_change": None,    # generic fallback
}

# ---------------------------------------------------------------------------
# Freeform comparison window aliases → canonical window names
# ---------------------------------------------------------------------------
_COMPARISON_ALIASES: dict[str, str] = {
    "last week":     "last_7_days",
    "previous week": "last_7_days",
    "last 7 days":   "last_7_days",
    "last month":    "last_month",
    "previous month":"last_month",
    "last 30 days":  "last_30_days",
    "last quarter":  "last_quarter",
    "last year":     "last_year",
    "previous year": "last_year",
    "last 90 days":  "last_90_days",
}


def _transform_single_time_series(intent: Intent, log) -> Intent:
    """
    Apply the three mandatory mutations for SINGLE_TIME_SERIES:
        1. Expand the time window so there are ≥ 2 granular buckets to compare.
        2. Inject granularity from the derived_metric.
        3. Override ordering to time-dimension ascending.
    """
    derived = (
        intent.post_processing.derived_metric
        if intent.post_processing else None
    )

    # ---- 1. Expand window --------------------------------------------------
    if intent.time and intent.time.window:
        original = intent.time.window
        expanded = _EXPAND_WINDOW.get(original)
        if expanded:
            object.__setattr__(intent.time, "window", expanded)
            log.info(f"SINGLE_TIME_SERIES: expanded window {original!r} → {expanded!r}")
        else:
            log.warning(
                f"SINGLE_TIME_SERIES: no expansion rule for window {original!r} — "
                "Cube may return only 1 bucket"
            )

    # ---- 2. Inject granularity --------------------------------------------
    if intent.time:
        if not intent.time.granularity:
            granularity = _DERIVED_TO_GRANULARITY.get(derived or "", None)
            
            if granularity is None and derived == "period_change":
                # Infer from comparison_window
                comp_window = getattr(
                    getattr(intent.post_processing, "comparison", None),
                    "comparison_window", None
                )
                if comp_window in ("last_7_days",):
                    granularity = "day"
                elif comp_window in ("last_month", "last_30_days"):
                    granularity = "week"
                elif comp_window in ("last_quarter", "last_90_days"):
                    granularity = "month"
                elif comp_window in ("last_year",):
                    granularity = "quarter"
                else:
                    granularity = "week"  # safe default
            
            object.__setattr__(intent.time, "granularity", granularity)
        else:
            log.info(
                f"SINGLE_TIME_SERIES: granularity already set to {intent.time.granularity!r}"
            )

    # ---- 3. Override ordering to time ascending ---------------------------
    # Reuse post_processing but set ranking to disabled so _build_order
    # in cube_query_builder will use the time column, not the metric.
    # We signal this by tagging the intent so the builder can detect it.
    # Simpler: we'll override via a ranking-disabled spec with a sentinel flag.
    # The cube_query_builder._build_order already defaults to metric desc, so
    # we patch post_processing.ranking to be disabled + asc — this tells the
    # builder to sort asc. The actual time-sort happens in insight_engine
    # post-processing, but having the query sorted correctly avoids Cube
    # returning data in an arbitrary order.
    if intent.post_processing:
        from app.models.intent import RankingSpec
        current_ranking = intent.post_processing.ranking
        if not (current_ranking and current_ranking.enabled):
            # Set a time-ascending order override
            object.__setattr__(
                intent.post_processing,
                "ranking",
                RankingSpec(enabled=True, order="asc", limit=None),
            )
            log.info("SINGLE_TIME_SERIES: overrode ordering to ascending for time-series sort")

    return intent


def _normalize_comparison_window(intent: Intent, log) -> Intent:
    pp = intent.post_processing
    if not (pp and pp.comparison):
        return intent

    # Explicit date comparison — start_date/end_date are the comparison period
    # No window needed, just pass through
    if intent.time and intent.time.start_date:
        log.info("DUAL_QUERY: explicit date range comparison, no window normalization needed")
        return intent

    if not pp.comparison.comparison_window:
        log.warning(
            "DUAL_QUERY strategy but no comparison_window set — "
            "comparison query will fail"
        )
        return intent

    raw = pp.comparison.comparison_window.strip().lower()
    canonical = _COMPARISON_ALIASES.get(raw, raw)
    if canonical != raw:
        object.__setattr__(pp.comparison, "comparison_window", canonical)
        log.info(f"DUAL_QUERY: normalized comparison_window {raw!r} → {canonical!r}")
    return intent


def _periods_contiguous_and_equal(intent: Intent) -> bool:
    """
    Return True if the current and comparison periods are contiguous and equal-size.

    Rules:
    - Custom explicit dates (start_date set) → always False (non-contiguous)
    - "to-date" windows (partial periods) → always False
    - Rolling named windows (last_7_days, last_month, last_year) → True
      as long as BOTH the primary window and the comparison window are non-partial
    """
    time = intent.time
    if time is None:
        return False

    # Custom explicit dates → always dual
    if time.start_date is not None:
        return False

    # Primary window must be a named rolling window
    primary_window = time.window
    if not primary_window:
        return False

    if primary_window in NON_CONTIGUOUS_WINDOWS:
        return False
    

    # Check comparison window if present
    pp = intent.post_processing
    if pp and pp.comparison and pp.comparison.comparison_window:
        comp_window = _COMPARISON_ALIASES.get(
            pp.comparison.comparison_window.strip().lower(),
            pp.comparison.comparison_window,
        )
        if comp_window in NON_CONTIGUOUS_WINDOWS:
            return False

    return True
