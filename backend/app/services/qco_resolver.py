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
from app.models.qco import QueryContextObject, QCOTimeRange, QCOFilter

logger = logging.getLogger(__name__)


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
    # Resolve time range to concrete dates
    time_range = _resolve_time_range(intent)

    # Resolve granularity
    time_granularity = None
    if intent.time_dimension and hasattr(intent.time_dimension, "granularity"):
        time_granularity = intent.time_dimension.granularity

    # Extract semantic metric name (strip cube prefix if present)
    metric = _to_semantic_name(intent.metric)

    # Extract semantic dimension names
    group_by = None
    if intent.group_by:
        group_by = [_to_semantic_name(d) for d in intent.group_by]

    # Resolve filters to semantic names
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

    # Get intent_type as string
    intent_type = intent.intent_type
    if hasattr(intent_type, "value"):
        intent_type = intent_type.value

    qco = QueryContextObject(
        original_query=query,
        intent_type=intent_type,
        sales_scope=intent.sales_scope,
        metric=metric,
        group_by=group_by,
        time_granularity=time_granularity,
        time_range=time_range,
        filters=filters,
        visualization_type=intent.visualization_type,
        limit=intent.limit,
    )

    logger.info(f"QCO resolved: metric={metric}, scope={intent.sales_scope}, "
                f"time_range={time_range}, group_by={group_by}")

    return qco


def _resolve_time_range(intent: Intent) -> Optional[QCOTimeRange]:
    """
    Resolve the intent's time range to concrete start/end dates.

    If the intent uses a named window (e.g. 'last_30_days'), we resolve
    it to explicit dates so the QCO always has concrete dates.
    """
    if intent.time_range is None:
        return None

    # If explicit dates already provided, use them directly
    if intent.time_range.start_date and intent.time_range.end_date:
        return QCOTimeRange(
            start_date=intent.time_range.start_date,
            end_date=intent.time_range.end_date,
        )

    # Resolve named window to concrete dates
    if intent.time_range.window:
        start, end = _resolve_window_to_dates(intent.time_range.window)
        return QCOTimeRange(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    return None


def _resolve_window_to_dates(window: str) -> tuple[date, date]:
    """Resolve a named time window to concrete start and end dates."""
    today = date.today()

    match window:
        case "today":
            return today, today
        case "yesterday":
            d = today - timedelta(days=1)
            return d, d
        case "last_7_days":
            return today - timedelta(days=7), today
        case "last_30_days":
            return today - timedelta(days=30), today
        case "last_90_days":
            return today - timedelta(days=90), today
        case "month_to_date":
            return today.replace(day=1), today
        case "quarter_to_date":
            q_start = ((today.month - 1) // 3) * 3 + 1
            return date(today.year, q_start, 1), today
        case "year_to_date":
            return date(today.year, 1, 1), today
        case "last_month":
            first = today.replace(day=1)
            last_end = first - timedelta(days=1)
            return last_end.replace(day=1), last_end
        case "last_quarter":
            q = (today.month - 1) // 3
            if q == 0:
                return date(today.year - 1, 10, 1), date(today.year - 1, 12, 31)
            sm = (q - 1) * 3 + 1
            return date(today.year, sm, 1), date(today.year, sm + 3, 1) - timedelta(days=1)
        case "last_year":
            return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        case "all_time":
            return date(today.year - 25, 1, 1), today
        case _:
            # Fallback: just use last 30 days
            logger.warning(f"Unknown time window '{window}', defaulting to last 30 days")
            return today - timedelta(days=30), today


def _to_semantic_name(cube_field: str) -> str:
    """
    Strip the Cube prefix from a field name to get the semantic name.

    e.g. 'fact_secondary_sales.net_value' → 'net_value'
         'net_value' → 'net_value'  (already semantic)
    """
    if "." in cube_field:
        return cube_field.split(".", 1)[1]
    return cube_field
