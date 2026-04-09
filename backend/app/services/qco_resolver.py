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
from datetime import date, timedelta, datetime
from typing import Optional, Dict, Any

from app.models.intent import Intent
from app.models.qco import QueryContextObject, QCOTimeRange, QCOFilter, QCOMetric, SlotMeta
from app.models.hierarchy import get_axis
from app.services.cube.cube_query_builder import resolve_time_window
from app.dspy_pipeline.pipeline import get_stored_agent_results, clear_stored_agent_results

logger = logging.getLogger(__name__)

# Constants
ALL_TIME_YEARS_BACK = 25  # For "all_time" window - go back 25 years


def resolve_qco_with_agent_caching(
    intent: Intent,
    query: str,
    agent_results: Optional[Dict[str, Any]] = None,
    previous_qco: Optional[QueryContextObject] = None
) -> QueryContextObject:
    """
    Build a QCO from a validated Intent and cache agent results for context injection.

    This is an enhanced version of resolve_qco that additionally caches the agent
    results from the DSPy pipeline for selective re-execution in future queries.

    Args:
        intent: Validated Intent object (Pydantic model)
        query: The original NL query string
        agent_results: Dict of agent results from context injection manager
        previous_qco: Previous QCO for turn indexing and slot metadata

    Returns:
        QueryContextObject with all resolved parameters and cached agent results
    """
    # Start with the standard QCO resolution
    qco = _resolve_qco_standard(intent, query)

    # Add cached agent results for context injection
    cached_scope_result = None
    cached_time_result = None
    cached_metrics_result = None
    cached_dimensions_result = None

    if agent_results:
        # Convert agent results to dicts for caching
        if 'scope' in agent_results:
            cached_scope_result = agent_results['scope'].model_dump()

        if 'time' in agent_results:
            cached_time_result = agent_results['time'].model_dump()

        if 'metrics' in agent_results:
            cached_metrics_result = agent_results['metrics'].model_dump()

        if 'dimensions' in agent_results:
            cached_dimensions_result = agent_results['dimensions'].model_dump()

        logger.info(f"[QCO Resolver] Cached agent results: {list(agent_results.keys())}")

    # Update slot metadata with execution information
    slot_metadata = {}
    current_turn = (previous_qco.turn_index + 1) if previous_qco else 1
    timestamp = datetime.now()

    # Update metadata for executed agents
    if agent_results:
        for agent_name in agent_results:
            slot_metadata[agent_name] = SlotMeta(
                source="override",  # Fresh execution
                turn=current_turn,
                timestamp=timestamp
            )

    # Inherit metadata for cached agents
    if previous_qco and previous_qco.slot_metadata:
        for agent_name, meta in previous_qco.slot_metadata.items():
            if agent_name not in slot_metadata:
                # Mark as carry forward from previous turn
                slot_metadata[agent_name] = SlotMeta(
                    source="carry_forward",
                    turn=meta.turn,  # Keep original turn
                    timestamp=timestamp
                )

    # Create enhanced QCO
    enhanced_qco = QueryContextObject(
        # Copy all standard QCO fields
        original_query=qco.original_query,
        intent_type=qco.intent_type,
        sales_scope=qco.sales_scope,
        metrics=qco.metrics,
        group_by=qco.group_by,
        time_dimension=qco.time_dimension,
        time_granularity=qco.time_granularity,
        time_range=qco.time_range,
        filters=qco.filters,
        visualization_type=qco.visualization_type,
        limit=qco.limit,
        active_hierarchies=qco.active_hierarchies,

        # Add context injection fields
        cached_scope_result=cached_scope_result,
        cached_time_result=cached_time_result,
        cached_metrics_result=cached_metrics_result,
        cached_dimensions_result=cached_dimensions_result,
        slot_metadata=slot_metadata,
        turn_index=current_turn,
        parent_request_id=getattr(previous_qco, 'parent_request_id', None) if previous_qco else None
    )

    logger.info(f"[QCO Resolver] Enhanced QCO created with turn_index={current_turn}, "
                f"cached_agents={list(agent_results.keys()) if agent_results else []}")

    return enhanced_qco


def resolve_qco(intent: Intent, query: str) -> QueryContextObject:
    """
    Build a QCO from a validated Intent.

    This captures the resolved state of the query so follow-up queries
    can inherit context (metric, scope, filters, time range, etc.).

    If agent results are available from context injection (stored in thread-local
    storage), this will automatically use the enhanced version with caching.

    Args:
        intent: Validated Intent object (Pydantic model)
        query: The original NL query string

    Returns:
        QueryContextObject with all resolved parameters
    """
    # Check for stored agent results from context injection
    try:
        agent_results = get_stored_agent_results()

        if agent_results:
            logger.info("[QCO Resolver] Using enhanced QCO resolution with agent caching")
            # Clear the stored results to avoid memory leaks
            clear_stored_agent_results()
            return resolve_qco_with_agent_caching(intent, query, agent_results)
    except ImportError:
        # Fallback if context injection is not available
        pass

    # Standard QCO resolution
    return _resolve_qco_standard(intent, query)


def _resolve_qco_standard(intent: Intent, query: str) -> QueryContextObject:
    """
    Build a QCO from a validated Intent (standard version without agent caching).

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

