"""
QCO Resolver - Converts a validated Intent into a Query Context Object.

After a query succeeds, this module builds the QCO snapshot that captures
the resolved analytical state (with concrete dates, semantic names, etc.)
for use as context in follow-up queries.

DESIGN PRINCIPLES:
- Runs AFTER validation succeeds and query executes
- Resolves time windows to concrete date ranges
- Stores semantic names (not Cube IDs) so the QCO is LLM-friendly
- Pure function: Intent + query → QCO
"""

import logging
from datetime import date, timedelta
from typing import Optional

from app.models.intent import Intent
from app.models.qco import QueryContextObject, QCOTimeRange, QCOFilter, QCOMetric
from app.models.hierarchy import get_axis
from app.services.cube_query_builder import resolve_time_window

logger = logging.getLogger(__name__)

# Constants
ALL_TIME_YEARS_BACK = 25  # For "all_time" window - go back 25 years


def resolve_qco(intent: Intent, query: str) -> QueryContextObject:
    """
    Build a QCO from a validated Intent.

    This captures the resolved state of the query so follow-up queries
    can inherit context (metric, scope, filters, time range, etc.).

    Args:
        intent: Validated Intent object (Pydantic model)
        query: The original NL query string

    Returns:
        QueryContextObject with all resolved parameters
    """
    from app.models.intent import derive_intent_type

    # Resolve time to concrete dates
    time_range = _resolve_time_range(intent)

    # Time dimension and granularity from unified intent.time (TimeSpec)
    time_dimension = None
    time_granularity = None
    if intent.time is not None:
        time_dimension = _to_semantic_name(intent.time.dimension)
        time_granularity = intent.time.granularity

    # Full metrics list — strip Cube prefixes, preserve aggregation
    qco_metrics = [
        QCOMetric(
            name=_to_semantic_name(m.name),
            aggregation=m.aggregation,
        )
        for m in intent.metrics
    ]

    # Group-by — strip cube prefixes
    group_by = None
    if intent.group_by:
        group_by = [_to_semantic_name(d) for d in intent.group_by]

    # Filters — strip cube prefixes
    filters = None
    if intent.filters:
        filters = [
            QCOFilter(
                dimension=_to_semantic_name(f.dimension),
                operator=f.operator,
                value=f.value,
            )
            for f in intent.filters
        ]

    # Derive intent type deterministically from structure
    try:
        intent_type = derive_intent_type(intent).value
    except Exception:
        intent_type = "snapshot"

    # Compute active hierarchy state from group_by
    active_hierarchies = {}
    for dim in (group_by or []):
        axis = get_axis(dim)
        if axis:
            active_hierarchies[axis] = dim

    # Extract ranking limit from post_processing (for follow-up inheritance)
    limit = None
    if (
        intent.post_processing
        and intent.post_processing.ranking
        and intent.post_processing.ranking.enabled
        and intent.post_processing.ranking.limit is not None
    ):
        limit = intent.post_processing.ranking.limit

    qco = QueryContextObject(
        original_query=query,
        intent_type=intent_type,
        sales_scope=intent.sales_scope,
        metrics=qco_metrics,
        group_by=group_by,
        time_dimension=time_dimension,
        time_granularity=time_granularity,
        time_range=time_range,
        filters=filters,
        limit=limit,
        active_hierarchies=active_hierarchies or None,
    )

    primary_metric = qco_metrics[0].name if qco_metrics else ""
    logger.info(f"QCO resolved: metrics={[m.name for m in qco_metrics]}, scope={intent.sales_scope}, "
                f"time_range={time_range}, group_by={group_by}, "
                f"intent_type={intent_type}, limit={limit}, "
                f"active_hierarchies={active_hierarchies or 'none'}")

    return qco


def _resolve_time_range(intent: Intent) -> Optional[QCOTimeRange]:
    """
    Resolve the intent's time to concrete start/end dates.

    Reads from intent.time (unified TimeSpec). Named windows are resolved
    to explicit ISO dates so the QCO always stores concrete dates.
    """
    t = intent.time
    if t is None:
        return None

    # Explicit dates provided — use them directly
    if t.start_date and t.end_date:
        return QCOTimeRange(start_date=t.start_date, end_date=t.end_date)

    # Resolve named window to concrete dates
    if t.window:
        start, end = _resolve_window_to_dates(t.window)
        return QCOTimeRange(start_date=start.isoformat(), end_date=end.isoformat())

    return None


def _resolve_window_to_dates(window: str) -> tuple[date, date]:
    """
    Resolve a named time window to concrete start and end dates.

    BUG-05 FIX: Delegates to the canonical resolve_time_window() in
    cube_query_builder so both resolvers are always in sync and cover
    all named windows (last_14_days, last_2_months, etc.).
    """
    try:
        start_str, end_str = resolve_time_window(window)
        return date.fromisoformat(start_str), date.fromisoformat(end_str)
    except (ValueError, KeyError):
        logger.warning(f"Unknown time window '{window}', defaulting to last 30 days")
        today = date.today()
        return today - timedelta(days=30), today


def _to_semantic_name(cube_field: Optional[str]) -> str:
    """
    Strip the Cube prefix from a field name to get the semantic name.

    e.g. 'fact_secondary_sales.net_value' -> 'net_value'
         'net_value' -> 'net_value'  (already semantic)
         None -> ''  (empty string for None)
    """
    if not cube_field:
        return ""
    if "." in cube_field:
        return cube_field.split(".", 1)[1]
    return cube_field

