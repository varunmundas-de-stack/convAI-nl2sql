"""
Intent Merger - Merges new LLM-extracted intent with previous QCO context.

MERGE RULES (Override semantics):
1. If the new intent provides a field → USE IT (new always wins)
2. If the new intent has null/missing field → INHERIT from previous QCO
3. Exception: if the user explicitly changes intent_type, don't inherit
   fields that don't make sense for the new type

This enables follow-up queries like:
- "now show by brand"     → inherits metric, scope, time_range; overrides group_by
- "for last 7 days"       → inherits metric, scope, group_by; overrides time_range
- "drill into Mumbai"     → inherits metric, scope, time; adds city filter
"""

import copy
import logging
from typing import Any, Optional

from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)


def merge_intent(
    new_intent: dict[str, Any],
    previous_qco: Optional[QueryContextObject],
) -> dict[str, Any]:
    """
    Merge new LLM-extracted intent with previous QCO.

    If no previous QCO exists, returns the new intent unchanged.

    Args:
        new_intent: Raw intent dict from LLM (pre-normalization)
        previous_qco: Previous QCO (or None if first query in session)

    Returns:
        Merged intent dict ready for normalization → validation
    """
    if previous_qco is None:
        logger.info("No previous QCO — using new intent as-is")
        return new_intent

    merged = copy.deepcopy(new_intent)

    logger.info(f"Merging intent with previous QCO (prev query: '{previous_qco.original_query}')")

    # -------------------------------------------------------------------------
    # RULE 1: sales_scope — inherit if missing
    # -------------------------------------------------------------------------
    if not merged.get("sales_scope"):
        merged["sales_scope"] = previous_qco.sales_scope
        logger.debug(f"Inherited sales_scope: {previous_qco.sales_scope}")

    # -------------------------------------------------------------------------
    # RULE 2: metric — inherit if missing
    # -------------------------------------------------------------------------
    if not merged.get("metric"):
        merged["metric"] = previous_qco.metric
        logger.debug(f"Inherited metric: {previous_qco.metric}")

    # -------------------------------------------------------------------------
    # RULE 3: time_range — inherit if missing
    # -------------------------------------------------------------------------
    if not merged.get("time_range") and previous_qco.time_range:
        merged["time_range"] = {
            "window": None,
            "start_date": previous_qco.time_range.start_date,
            "end_date": previous_qco.time_range.end_date,
        }
        logger.debug(f"Inherited time_range: {previous_qco.time_range.start_date} to {previous_qco.time_range.end_date}")

    # -------------------------------------------------------------------------
    # RULE 4: time_dimension — inherit dimension and granularity if missing
    # -------------------------------------------------------------------------
    if not merged.get("time_dimension") and (previous_qco.time_dimension or previous_qco.time_granularity):
        # Only inherit if the intent type benefits from it (trend, comparison)
        intent_type = merged.get("intent_type", "")
        if intent_type in ("trend", "comparison"):
            # Use stored time dimension, fallback to invoice_date if not available
            dimension = previous_qco.time_dimension or "invoice_date"
            merged["time_dimension"] = {
                "dimension": dimension,
                "granularity": previous_qco.time_granularity or "day",
            }
            logger.debug(f"Inherited time_dimension: {dimension} @ {previous_qco.time_granularity}")

    # -------------------------------------------------------------------------
    # RULE 5: filters — additive merge
    #   - New filters override previous filters on the same dimension
    #   - Previous filters on OTHER dimensions are inherited
    # -------------------------------------------------------------------------
    new_filters = merged.get("filters") or []
    prev_filters = previous_qco.filters or []

    if prev_filters:
        # Get dimensions already in new filters
        new_filter_dims = {f["dimension"] for f in new_filters if isinstance(f, dict)}

        # Inherit previous filters for dimensions NOT in new intent
        for pf in prev_filters:
            if pf.dimension not in new_filter_dims:
                new_filters.append({
                    "dimension": pf.dimension,
                    "operator": pf.operator,
                    "value": pf.value,
                })
                logger.debug(f"Inherited filter: {pf.dimension} {pf.operator} {pf.value}")

        if new_filters:
            merged["filters"] = new_filters

    # -------------------------------------------------------------------------
    # RULE 6: group_by — hierarchy-aware
    # Drill mutation is applied BEFORE this merger (Step 2.5 in orchestrator).
    # If drill already set group_by → use it as-is.
    # If no group_by and previous QCO has one → inherit for continuation queries.
    # -------------------------------------------------------------------------
    if not merged.get("group_by") and previous_qco.group_by:
        # Inherit previous group_by for continuation (e.g. "show me last month" keeps group_by)
        merged["group_by"] = list(previous_qco.group_by)
        logger.debug(f"Inherited group_by: {previous_qco.group_by}")

    # -------------------------------------------------------------------------
    # RULE 7: visualization_type — inherit if missing
    # -------------------------------------------------------------------------
    if not merged.get("visualization_type") and previous_qco.visualization_type:
        merged["visualization_type"] = previous_qco.visualization_type
        logger.debug(f"Inherited visualization_type: {previous_qco.visualization_type}")

    # -------------------------------------------------------------------------
    # RULE 8: limit — inherit if missing
    # -------------------------------------------------------------------------
    if merged.get("limit") is None and previous_qco.limit is not None:
        merged["limit"] = previous_qco.limit
        logger.debug(f"Inherited limit: {previous_qco.limit}")

    logger.info(f"Merge complete: {merged}")
    return merged
