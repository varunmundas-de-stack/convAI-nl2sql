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
    # RULE 2: metrics — inherit from QCO if new intent has none
    # Injects the full list of Metric objects: [{"name": "net_value", "aggregation": "sum"}]
    # This matches the Intent model's expected format exactly.
    # -------------------------------------------------------------------------
    if not merged.get("metrics") and previous_qco.metrics:
        merged["metrics"] = [
            {"name": m.name, "aggregation": m.aggregation}
            for m in previous_qco.metrics
        ]
        logger.debug(f"Inherited metrics from QCO: {[m.name for m in previous_qco.metrics]}")

    # -------------------------------------------------------------------------
    # RULE 3: time — inherit resolved dates if new intent has no time block
    # Maps the QCO's concrete start/end dates back into the TimeSpec format
    # so the normalizer can process it correctly.
    # -------------------------------------------------------------------------
    if not merged.get("time") and previous_qco.time_range:
        merged["time"] = {
            "dimension": previous_qco.time_dimension or "invoice_date",
            "window": None,
            "start_date": previous_qco.time_range.start_date,
            "end_date": previous_qco.time_range.end_date,
            "granularity": previous_qco.time_granularity,  # keep granularity if it was set
        }
        logger.debug(
            f"Inherited time: {previous_qco.time_range.start_date} -> "
            f"{previous_qco.time_range.end_date}, "
            f"granularity={previous_qco.time_granularity}"
        )

    # -------------------------------------------------------------------------
    # RULE 4: filters — additive merge
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
    # RULE 5: group_by — hierarchy-aware
    # Drill mutation is applied BEFORE this merger (Step 2.5 in orchestrator).
    # If drill already set group_by → use it as-is.
    #
    # BUG-07 FIX: distinguish "key absent" (inherit) from "key explicitly null"
    # (user wants no grouping, e.g. "just show me total sales").
    # -------------------------------------------------------------------------
    if "group_by" not in new_intent and previous_qco.group_by:
        # Key was absent from the LLM output — inherit for continuation queries
        merged["group_by"] = list(previous_qco.group_by)
        logger.debug(f"Inherited group_by: {previous_qco.group_by}")
    elif "group_by" in new_intent and not new_intent["group_by"]:
        # Key is present but null/empty — user explicitly wants no grouping; respect it
        logger.debug("group_by explicitly null in new intent — not inheriting from QCO")

    # -------------------------------------------------------------------------
    # RULE 6: visualization_type — inherit if missing
    # -------------------------------------------------------------------------
    if not merged.get("visualization_type") and previous_qco.visualization_type:
        merged["visualization_type"] = previous_qco.visualization_type
        logger.debug(f"Inherited visualization_type: {previous_qco.visualization_type}")

    # -------------------------------------------------------------------------
    # RULE 7: ranking limit — inherit if new intent has no ranking configured
    # Injects limit back into post_processing.ranking so the query builder
    # applies the same top-N constraint for follow-up scoping queries.
    # -------------------------------------------------------------------------
    if previous_qco.limit is not None:
        pp = merged.get("post_processing") or {}
        ranking = pp.get("ranking") or {}
        # Only inherit if the new intent did NOT set its own ranking
        if not ranking.get("enabled"):
            pp["ranking"] = {
                "enabled": True,
                "order": ranking.get("order", "desc"),
                "limit": previous_qco.limit,
            }
            merged["post_processing"] = pp
            logger.debug(f"Inherited ranking limit: {previous_qco.limit}")

    logger.info(f"Merge complete: {merged}")
    return merged
