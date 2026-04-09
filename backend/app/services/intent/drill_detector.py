"""
Drill-Down Detector — Determines whether a new intent is a drill-down mutation
or a fresh query, and what kind of mutation to apply.

DETECTION CASES:
  A. dimension_drill — new group_by dimension is deeper in same axis as previous
  B. value_drill     — message contains a value from previous results, no new dimension
  C. cross_axis      — new dimension is on a different axis, add alongside existing
  D. time_change     — time granularity change only
  none               — fresh query, no drill

DESIGN:
- Runs at Step 2.5 in the orchestrator, BEFORE the intent merger
- Pure function: (new_intent, previous_qco) → DrillResult
- Does NOT modify intent — only classifies. Mutation is in apply_drill_mutation().
"""

import copy
import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.models.hierarchy import (
    get_axis,
    get_level,
    get_next_level,
    is_deeper,
    all_hierarchy_dimensions,
    MAX_NON_TIME_AXES,
    TIME_GRANULARITY_ORDER,
)
from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT TYPE
# =============================================================================

@dataclass
class DrillResult:
    """Result of drill-down detection."""
    case: Literal["none", "dimension_drill", "value_drill", "cross_axis", "time_change"]
    drill_axis: Optional[str] = None          # e.g. "geography"
    prev_dimension: Optional[str] = None      # e.g. "zone"
    next_dimension: Optional[str] = None      # e.g. "state"
    drill_value: Optional[str] = None         # e.g. "South" (for value-based drills)
    new_granularity: Optional[str] = None     # e.g. "week" (for time changes)


# =============================================================================
# PUBLIC API
# =============================================================================

def detect_drill(
    new_intent: dict[str, Any],
    previous_qco: QueryContextObject,
) -> DrillResult:
    """
    Detect whether a new intent is a drill-down mutation of the previous QCO.

    Args:
        new_intent: Raw intent dict from LLM (pre-normalization, pre-merge)
        previous_qco: Previous QCO from session

    Returns:
        DrillResult describing the type of mutation (or "none" for fresh query)
    """
    # Guard: no previous context means no drill
    if previous_qco is None:
        return DrillResult(case="none")

    prev_group_by = previous_qco.group_by or []

    new_group_by = new_intent.get("group_by") or []
    new_filters = new_intent.get("filters") or []

    # --- Check for new metric (different metric = fresh query) ---
    new_metrics = new_intent.get("metrics") or []
    if new_metrics:
        # Metrics can be dicts {"name": ..., "aggregation": ...} or plain strings
        new_metric_names = {
            (m.get("name", "") if isinstance(m, dict) else str(m))
            for m in new_metrics
        }
        # If there's a genuinely new metric, it's a fresh query
        # Compare against the primary metric from the previous QCO
        if new_metric_names and not any(
            _semantic_match(nm, previous_qco.metric) for nm in new_metric_names
        ):
            logger.debug(f"New metric detected ({new_metric_names} vs {previous_qco.metric}) — fresh query")
            return DrillResult(case="none")

    # Also check legacy single-metric field
    new_metric = new_intent.get("metric")
    if new_metric and not _semantic_match(new_metric, previous_qco.metric):
        logger.debug(f"New metric detected ({new_metric} vs {previous_qco.metric}) — fresh query")
        return DrillResult(case="none")

    # --- Build previous hierarchy state ---
    prev_axes: dict[str, str] = {}  # axis → dimension
    for dim in prev_group_by:
        axis = get_axis(dim)
        if axis:
            prev_axes[axis] = dim

    # Also check active_hierarchies if available
    if hasattr(previous_qco, 'active_hierarchies') and previous_qco.active_hierarchies:
        for axis, dim in previous_qco.active_hierarchies.items():
            if axis not in prev_axes:
                prev_axes[axis] = dim

    # --- Case D: Time granularity change ---
    result = _check_time_change(new_intent, previous_qco)
    if result:
        return result

    # --- Case A: Dimension-based drill ---
    if new_group_by:
        result = _check_dimension_drill(new_group_by, prev_axes)
        if result:
            return result

        # --- Case C: Cross-axis addition ---
        result = _check_cross_axis(new_group_by, prev_axes)
        if result:
            return result

    # --- Case B: Value-based drill ---
    if new_filters and not new_group_by:
        result = _check_value_drill(new_filters, prev_axes)
        if result:
            return result

    # No drill pattern detected
    return DrillResult(case="none")


def apply_drill_mutation(
    new_intent: dict[str, Any],
    previous_qco: QueryContextObject,
    drill: DrillResult,
) -> dict[str, Any]:
    """
    Apply a drill-down mutation to the intent based on the DrillResult.

    Modifies group_by and filters on the intent dict. Does NOT touch metrics,
    time_range, or sales_scope — those are handled by the intent merger.

    Args:
        new_intent: Raw intent dict (will be deep-copied)
        previous_qco: Previous QCO
        drill: DrillResult from detect_drill()

    Returns:
        Mutated intent dict
    """
    mutated = copy.deepcopy(new_intent)
    prev_group_by = list(previous_qco.group_by or [])

    if drill.case == "dimension_drill":
        # Replace the drilled axis level, preserve other axes
        new_group = []
        for dim in prev_group_by:
            if get_axis(dim) == drill.drill_axis:
                # Replace with deeper level
                new_group.append(drill.next_dimension)
            else:
                new_group.append(dim)

        # If the drilled axis wasn't in prev_group_by, append it
        if drill.next_dimension not in new_group:
            new_group.append(drill.next_dimension)

        mutated["group_by"] = _enforce_axis_limits(new_group)
        logger.info(f"Dimension drill: group_by={mutated['group_by']}")

    elif drill.case == "value_drill":
        # Add filter for the drilled value
        filters = mutated.get("filters") or []
        filters.append({
            "dimension": drill.prev_dimension,
            "operator": "equals",
            "value": drill.drill_value,
        })
        mutated["filters"] = filters

        # Replace the drilled axis level in group_by, preserve others
        new_group = []
        for dim in prev_group_by:
            if get_axis(dim) == drill.drill_axis:
                new_group.append(drill.next_dimension)
            else:
                new_group.append(dim)

        if drill.next_dimension and drill.next_dimension not in new_group:
            new_group.append(drill.next_dimension)

        mutated["group_by"] = _enforce_axis_limits(new_group)
        logger.info(f"Value drill: filter {drill.prev_dimension}={drill.drill_value}, "
                    f"group_by={mutated['group_by']}")

    elif drill.case == "cross_axis":
        # Add the new axis alongside existing axes
        new_group = list(prev_group_by)
        if drill.next_dimension and drill.next_dimension not in new_group:
            new_group.append(drill.next_dimension)
        mutated["group_by"] = _enforce_axis_limits(new_group)
        logger.info(f"Cross-axis: group_by={mutated['group_by']}")

    elif drill.case == "time_change":
        # Change time granularity
        time_spec = mutated.get("time") or {}
        time_spec["granularity"] = drill.new_granularity
        mutated["time"] = time_spec

        # Also handle legacy time_dimension format
        if mutated.get("time_dimension"):
            td = mutated["time_dimension"]
            if isinstance(td, dict):
                td["granularity"] = drill.new_granularity
            elif hasattr(td, "granularity"):
                td.granularity = drill.new_granularity

        # Preserve previous group_by if new intent doesn't specify one
        if not mutated.get("group_by") and prev_group_by:
            mutated["group_by"] = prev_group_by

        logger.info(f"Time change: granularity={drill.new_granularity}")

    return mutated


# =============================================================================
# PRIVATE DETECTION HELPERS
# =============================================================================

def _check_dimension_drill(
    new_group_by: list[str],
    prev_axes: dict[str, str],
) -> Optional[DrillResult]:
    """
    Case A: New group_by has a dimension deeper in the same axis as previous.

    e.g. prev=zone, new=state → dimension drill on geography
    """
    for new_dim in new_group_by:
        new_axis = get_axis(new_dim)
        if new_axis and new_axis in prev_axes:
            prev_dim = prev_axes[new_axis]
            if is_deeper(new_dim, prev_dim):
                return DrillResult(
                    case="dimension_drill",
                    drill_axis=new_axis,
                    prev_dimension=prev_dim,
                    next_dimension=new_dim,
                )
    return None


def _check_value_drill(
    new_filters: list[dict],
    prev_axes: dict[str, str],
) -> Optional[DrillResult]:
    """
    Case B: Filters contain a value for a previous group_by dimension,
    but no new group_by is specified.

    e.g. prev group_by=["zone"], filter added zone="South" → drill into South
    """
    for f in new_filters:
        if not isinstance(f, dict):
            continue
        filter_dim = f.get("dimension", "")
        filter_val = f.get("value", "")

        # Check if this filter targets a dimension that was in previous group_by
        filter_axis = get_axis(filter_dim)
        if filter_axis and filter_axis in prev_axes:
            prev_dim = prev_axes[filter_axis]
            if filter_dim == prev_dim:
                # Drilling into a specific value of the previous group_by dimension
                next_dim = get_next_level(prev_dim)
                if next_dim:
                    val = filter_val
                    if isinstance(val, list):
                        val = val[0] if val else None
                    return DrillResult(
                        case="value_drill",
                        drill_axis=filter_axis,
                        prev_dimension=prev_dim,
                        next_dimension=next_dim,
                        drill_value=val,
                    )
    return None


def _check_cross_axis(
    new_group_by: list[str],
    prev_axes: dict[str, str],
) -> Optional[DrillResult]:
    """
    Case C: New group_by has a dimension on a DIFFERENT axis than previous.

    e.g. prev=zone (geography), new=brand (product) → cross-axis
    Only if we haven't exceeded MAX_NON_TIME_AXES.
    """
    active_axis_count = len(prev_axes)

    for new_dim in new_group_by:
        new_axis = get_axis(new_dim)
        if new_axis and new_axis not in prev_axes:
            if active_axis_count < MAX_NON_TIME_AXES:
                return DrillResult(
                    case="cross_axis",
                    drill_axis=new_axis,
                    prev_dimension=None,
                    next_dimension=new_dim,
                )
            else:
                logger.warning(
                    f"Cross-axis {new_axis} rejected: already at max "
                    f"{MAX_NON_TIME_AXES} non-time axes"
                )
    return None


def _check_time_change(
    new_intent: dict[str, Any],
    previous_qco: QueryContextObject,
) -> Optional[DrillResult]:
    """
    Case D: Time granularity change.

    e.g. prev=month, new=week
    """
    # Check new-format time spec
    new_time = new_intent.get("time")
    if isinstance(new_time, dict):
        new_gran = new_time.get("granularity")
    else:
        new_gran = None

    # Check legacy format
    if not new_gran:
        td = new_intent.get("time_dimension")
        if isinstance(td, dict):
            new_gran = td.get("granularity")

    if not new_gran:
        return None

    prev_gran = previous_qco.time_granularity
    # BUG-08 FIX: fire when prev_gran is None too — a snapshot context gaining a
    # granularity is still a time_change that should be detected and applied correctly.
    granularity_changed = (new_gran != prev_gran) and new_gran in TIME_GRANULARITY_ORDER
    if granularity_changed:
        # Only treat as time_change if nothing else is changing
        new_group_by = new_intent.get("group_by") or []
        prev_group_by = previous_qco.group_by or []

        # If group_by is unchanged (or empty), this is purely a time change
        if not new_group_by or set(new_group_by) == set(prev_group_by):
            return DrillResult(
                case="time_change",
                new_granularity=new_gran,
            )

    return None


# =============================================================================
# CONSTRAINT ENFORCEMENT
# =============================================================================

def _enforce_axis_limits(group_by: list[str]) -> list[str]:
    """
    Enforce axis constraints on a group_by list:
    - 1 level per axis (keep deepest)
    - Max MAX_NON_TIME_AXES non-time axes

    Returns the filtered list.
    """
    # First pass: 1 level per axis (keep deepest if duplicates)
    axis_dims: dict[str, tuple[str, int]] = {}  # axis → (dim, level)
    non_axis_dims: list[str] = []

    for dim in group_by:
        axis = get_axis(dim)
        if axis:
            level = get_level(dim) or 0
            if axis not in axis_dims or level > axis_dims[axis][1]:
                axis_dims[axis] = (dim, level)
        else:
            non_axis_dims.append(dim)

    # Second pass: enforce max axes
    axes_sorted = list(axis_dims.keys())
    if len(axes_sorted) > MAX_NON_TIME_AXES:
        # Keep only the first MAX_NON_TIME_AXES (preserve order of first appearance)
        axes_to_keep = set(axes_sorted[:MAX_NON_TIME_AXES])
        logger.warning(
            f"Trimming axes to {MAX_NON_TIME_AXES}: keeping {axes_to_keep}, "
            f"dropping {set(axes_sorted) - axes_to_keep}"
        )
        axis_dims = {k: v for k, v in axis_dims.items() if k in axes_to_keep}

    # Rebuild list preserving original order
    result = []
    seen = set()
    for dim in group_by:
        axis = get_axis(dim)
        if axis:
            if axis in axis_dims and axis not in seen:
                result.append(axis_dims[axis][0])
                seen.add(axis)
        else:
            result.append(dim)

    return result


def _semantic_match(new_metric: str, prev_metric: str) -> bool:
    """
    Check if two metric names refer to the same metric.

    Handles stripping cube prefixes (e.g. "fact_secondary_sales.net_value" → "net_value")
    """
    def _strip(m: str) -> str:
        if "." in m:
            return m.split(".", 1)[1]
        return m

    return _strip(new_metric) == _strip(prev_metric)
