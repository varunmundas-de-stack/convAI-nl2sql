"""
Hierarchy Definitions for Drill-Down Support.

Defines dimensional hierarchies and time granularity ordering.
All drill-down detection and mutation logic references this module.

DESIGN:
- HIERARCHIES: dimension axes with ordered levels (shallow → deep)
- TIME_GRANULARITY_ORDER: granularity ordering (coarse → fine)
- Time is NOT in HIERARCHIES — it operates on `time.granularity`, not `group_by`
- To add a new axis, add an entry to HIERARCHIES. No other code changes needed.
"""

from typing import Optional


# =============================================================================
# HIERARCHY DEFINITIONS
# =============================================================================

HIERARCHIES: dict[str, list[str]] = {
    "geography": ["zone", "state", "city"],
    "product": ["category", "sub_category", "brand", "sku_code"],
}

TIME_GRANULARITY_ORDER: list[str] = ["year", "quarter", "month", "week", "day"]

# Constraints
MAX_NON_TIME_AXES = 2   # Max 2 non-time hierarchy axes active at once
MAX_LEVELS_PER_AXIS = 1  # Only 1 active level per axis


# =============================================================================
# LOOKUP HELPERS
# =============================================================================

# Pre-compute reverse lookup: dimension → (axis_name, level_index)
_DIM_TO_AXIS: dict[str, tuple[str, int]] = {}
for _axis_name, _levels in HIERARCHIES.items():
    for _i, _dim in enumerate(_levels):
        _DIM_TO_AXIS[_dim] = (_axis_name, _i)

# Pre-compute granularity lookup: granularity → index
_GRAN_TO_INDEX: dict[str, int] = {g: i for i, g in enumerate(TIME_GRANULARITY_ORDER)}


# =============================================================================
# PUBLIC API
# =============================================================================

def get_axis(dimension: str) -> Optional[str]:
    """
    Which hierarchy axis does this dimension belong to?

    Returns axis name (e.g. "geography") or None if not in any hierarchy.
    """
    entry = _DIM_TO_AXIS.get(dimension)
    return entry[0] if entry else None


def get_level(dimension: str) -> Optional[int]:
    """
    Depth index of a dimension within its axis (0 = shallowest).

    Returns None if dimension is not in any hierarchy.
    """
    entry = _DIM_TO_AXIS.get(dimension)
    return entry[1] if entry else None


def get_next_level(dimension: str) -> Optional[str]:
    """
    Get the next deeper dimension in the same axis.

    Returns None if already at the deepest level or not in a hierarchy.
    """
    entry = _DIM_TO_AXIS.get(dimension)
    if entry is None:
        return None
    axis_name, idx = entry
    levels = HIERARCHIES[axis_name]
    if idx + 1 < len(levels):
        return levels[idx + 1]
    return None


def is_deeper(dim_a: str, dim_b: str) -> bool:
    """
    True if dim_a is deeper than dim_b on the SAME axis.

    Returns False if either dimension is not in a hierarchy,
    or they belong to different axes.
    """
    entry_a = _DIM_TO_AXIS.get(dim_a)
    entry_b = _DIM_TO_AXIS.get(dim_b)
    if entry_a is None or entry_b is None:
        return False
    if entry_a[0] != entry_b[0]:
        return False
    return entry_a[1] > entry_b[1]


def get_axis_dimensions(axis: str) -> list[str]:
    """All dimensions in a hierarchy axis, shallow → deep."""
    return list(HIERARCHIES.get(axis, []))


def is_finer_granularity(gran_a: str, gran_b: str) -> bool:
    """
    True if gran_a is finer (deeper) than gran_b in time granularity order.

    e.g. is_finer_granularity("week", "month") → True
    """
    idx_a = _GRAN_TO_INDEX.get(gran_a)
    idx_b = _GRAN_TO_INDEX.get(gran_b)
    if idx_a is None or idx_b is None:
        return False
    return idx_a > idx_b


def get_next_granularity(granularity: str) -> Optional[str]:
    """
    Get the next finer granularity.

    e.g. get_next_granularity("month") → "week"
    Returns None if already at finest or not recognized.
    """
    idx = _GRAN_TO_INDEX.get(granularity)
    if idx is None or idx + 1 >= len(TIME_GRANULARITY_ORDER):
        return None
    return TIME_GRANULARITY_ORDER[idx + 1]


def all_hierarchy_dimensions() -> set[str]:
    """Return the set of all dimension names across all hierarchy axes."""
    return set(_DIM_TO_AXIS.keys())
