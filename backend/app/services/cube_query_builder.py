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


def _today_str() -> str:
    return date.today().isoformat()


def _years_ago_str(years: int) -> str:
    return date(date.today().year - years, 1, 1).isoformat()



class CubeQueryBuildError(Exception):
    """Exception raised when a Cube Query cannot be built."""
    pass

# =============================================================================
# INTERNAL TRANSLATION FUNCTIONS 
# =============================================================================

def _build_measures(intent: Intent) -> list[str]:
    measures: list[str] = []
    for m in intent.metrics:
        if "." not in m.name:
            raise ValueError(f"CubeQueryBuilder received non-normalized metric: {m.name}")
        measures.append(m.name)
    return measures


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
    if intent.time is None:
        return None

    t = intent.time
    td: dict[str, Any] = {"dimension": t.dimension}

    # Granularity — only set for trend queries
    if t.granularity:
        td["granularity"] = t.granularity

    # Date range — named window takes priority over explicit dates
    if t.window:
        td["dateRange"] = resolve_time_window(t.window)
    elif t.start_date and t.end_date:
        td["dateRange"] = [str(t.start_date), str(t.end_date)]

    return [td]

def _build_order(intent: Intent) -> dict[str, str]:
    # Order by the first (primary) metric; direction comes from ranking spec if present
    primary = intent.metrics[0].name
    if "." not in primary:
        raise ValueError(f"CubeQueryBuilder received non-normalized order metric: {primary}")
    ranking = intent.post_processing.ranking if intent.post_processing else None
    direction = (ranking.order or "desc") if (ranking and ranking.enabled) else "desc"
    return {primary: direction}


def _build_limit(intent: Intent) -> int:
    """Return the limit from ranking spec, or default if not specified."""
    ranking = intent.post_processing.ranking if intent.post_processing else None
    if ranking and ranking.enabled and ranking.limit is not None:
        return ranking.limit
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

    elif window == "all_time":
        start = date(today.year - 25, 1, 1)
        end = today

    else:
        raise ValueError(f"Unsupported TREND time window: {window}")

    return [start.isoformat(), end.isoformat()]
