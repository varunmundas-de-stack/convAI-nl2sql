"""
Cube Query Builder - Pure Intent → Cube Query JSON translator.

This module converts a normalized Intent object into a Cube Query JSON object.

DESIGN PRINCIPLES:
- Input is a normalized Intent (not raw dict, not LLM output)
- Output is Cube Query JSON only (measures, dimensions, filters, timeDimensions, order, limit)
- Mapping is mechanical, not inferential (direct field translations)
- Missing fields raise ValueError
- Fully unit-testable (Intent A → exact Cube query JSON B)

"""

from typing import Any

from app.models.intent import Intent, IntentType
from datetime import date, timedelta


# =============================================================================
# HARD-CODED DEFAULTS (Explicit, documented, global)
# =============================================================================

DEFAULT_LIMIT = 1000
DEFAULT_TIMEZONE = "Asia/Kolkata"




TIME_WINDOW_TO_CUBE_RANGE: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "last_7_days": "last 7 days",
    "last_30_days": "last 30 days",
    "last_90_days": "last 90 days",
    "month_to_date": "this month",
    "quarter_to_date": "this quarter",
    "year_to_date": "this year",
    "last_month": "last month",
    "last_quarter": "last quarter",
    "last_year": "last year",
}


class CubeQueryBuildError(Exception):
    """Exception raised when a Cube Query cannot be built."""
    pass

# =============================================================================
# INTERNAL TRANSLATION FUNCTIONS 
# =============================================================================

def _build_measures(intent: Intent) -> list[str]:
    metric = intent.metric
    if "." not in metric:
        raise ValueError(f"CubeQueryBuilder received non-normalized metric: {metric}")
    return [metric]


def _build_dimensions(intent: Intent) -> list[str] | None:
    if not intent.group_by:
        return None

    dims: list[str] = []
    for dim in intent.group_by:
        if "." not in dim:
            raise ValueError(f"CubeQueryBuilder received non-normalized dimension: {dim}")
        dims.append(dim)

    return dims



def _build_filters(intent: Intent) -> list[dict[str, Any]] | None:
    if not intent.filters:
        return None

    filters: list[dict[str, Any]] = []

    for flt in intent.filters:
        dim = flt.dimension
        if "." not in dim:
            raise ValueError(f"CubeQueryBuilder received non-normalized filter dimension: {dim}")

        values = (
            [str(v) for v in flt.value]
            if isinstance(flt.value, list)
            else [str(flt.value)]
        )

        filters.append({
            "member": dim,
            "operator": flt.operator,
            "values": values,
        })

    return filters


def _build_time_dimensions(intent: Intent) -> list[dict[str, Any]] | None:
    if intent.time_dimension is None and intent.time_range is None:
        return None

    td: dict[str, Any] = {}

    if intent.time_dimension:
        dim = intent.time_dimension.dimension
        if "." not in dim:
            raise ValueError(f"CubeQueryBuilder received non-normalized time dimension: {dim}")

        td["dimension"] = dim

        if intent.intent_type == IntentType.TREND:
            td["granularity"] = intent.time_dimension.granularity
    else:
        # snapshot with time_range but no time_dimension
        td["dimension"] = "sales_fact.invoice_date"

    if intent.time_range:
        if intent.time_range.window:
            if intent.intent_type == IntentType.TREND:
                td["dateRange"] = resolve_time_window(intent.time_range.window)
            else:
                cube_range = TIME_WINDOW_TO_CUBE_RANGE.get(intent.time_range.window)
                if cube_range is None:
                    raise ValueError(
                        f"Unknown time window: {intent.time_range.window}"
                    )
                td["dateRange"] = cube_range
        else:
            # Explicit range must be TWO STRINGS
            td["dateRange"] = [
                str(intent.time_range.start_date),
                str(intent.time_range.end_date),
            ]

    return [td]


def _build_order(intent: Intent) -> dict[str, str]:
    metric = intent.metric
    if "." not in metric:
        raise ValueError(f"CubeQueryBuilder received non-normalized order metric: {metric}")
    return {metric: "desc"}


def _build_limit(intent: Intent) -> int:
    """Return the limit from intent, or default if not specified."""
    if intent.limit is not None:
        return intent.limit
    return DEFAULT_LIMIT


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def build_cube_query(intent: Intent) -> dict[str, Any]:
    """
    Build a Cube Query JSON from a validated Intent.
    
    This is the ONLY public function in this module.
    It is a PURE FUNCTION: same input always produces same output.
    
    Args:
        intent: A validated Intent object (NOT a raw dict)
        
    Returns:
        Cube Query JSON object ready for the Cube REST API
    """
    query: dict[str, Any] = {}
    
    # measures (required)
    query["measures"] = _build_measures(intent)
    
    # dimensions (optional)
    dimensions = _build_dimensions(intent)
    if dimensions:
        query["dimensions"] = dimensions
    
    # filters (optional)
    filters = _build_filters(intent)
    if filters:
        query["filters"] = filters
    
    # timeDimensions (optional)
    time_dimensions = _build_time_dimensions(intent)
    if time_dimensions:
        query["timeDimensions"] = time_dimensions
    
    # order (optional, but we apply default)
    order = _build_order(intent)
    if order:
        query["order"] = order
    
    # limit (always included with default)
    query["limit"] = _build_limit(intent)
    
    # timezone (fixed system timezone)
    query["timezone"] = DEFAULT_TIMEZONE
    
    return query


# Helper function

from datetime import date, timedelta

def resolve_time_window(window: str) -> list[str]:
    today = date.today()

    if window == "today":
        start = end = today

    elif window == "yesterday":
        start = end = today - timedelta(days=1)

    elif window == "last_7_days":
        start = today - timedelta(days=7)
        end = today

    elif window == "last_30_days":
        start = today - timedelta(days=30)
        end = today

    elif window == "last_90_days":
        start = today - timedelta(days=90)
        end = today

    elif window == "month_to_date":
        start = today.replace(day=1)
        end = today

    elif window == "quarter_to_date":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        start = date(today.year, quarter_start_month, 1)
        end = today

    elif window == "year_to_date":
        start = date(today.year, 1, 1)
        end = today

    elif window == "last_month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        start = last_month_end.replace(day=1)
        end = last_month_end

    elif window == "last_quarter":
        quarter = (today.month - 1) // 3
        if quarter == 0:
            start = date(today.year - 1, 10, 1)
            end = date(today.year - 1, 12, 31)
        else:
            start_month = (quarter - 1) * 3 + 1
            start = date(today.year, start_month, 1)
            end = date(today.year, start_month + 3, 1) - timedelta(days=1)

    elif window == "last_year":
        start = date(today.year - 1, 1, 1)
        end = date(today.year - 1, 12, 31)

    else:
        raise ValueError(f"Unsupported TREND time window: {window}")

    return [start.isoformat(), end.isoformat()]
