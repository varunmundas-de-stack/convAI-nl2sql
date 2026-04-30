"""
Intel RBAC Helper — Build RBAC-safe WHERE clauses for fact table queries.

Maps user sales_hierarchy_level → the correct column + value filter so the
intel scheduler never reads data outside a user's permitted scope.

Hierarchy levels (from app_meta.users):
  NSM   → National Sales Manager      → no restriction (full national view)
  ZSM   → Zonal Sales Manager         → filter by zsm_name
  ASM   → Area Sales Manager          → filter by asm_name
  SO    → Sales Officer               → filter by so_name  (using so_code value)
  SR    → Sales Representative        → filter by salesrep_code
  admin → cross-client admin          → no restriction
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RbacFilter:
    """A single WHERE-clause fragment and its bind parameters."""
    clause: str           # e.g. "zsm_name = %s"  (empty string = no filter)
    params: list[Any]     # bind params for the clause


# Maps sales_hierarchy_level → (fact_table_column, user_attribute)
_HIERARCHY_MAP: dict[str, tuple[str, str]] = {
    "ZSM": ("zsm_name",      "zsm_code"),
    "ASM": ("asm_name",      "asm_code"),
    "SO":  ("so_name",       "so_code"),   # so_name in fact table, so_code in users
    "SR":  ("salesrep_code", "salesrep_code"),
}


def build_rbac_filter(user: dict[str, Any]) -> RbacFilter:
    """
    Return a RbacFilter for a user row from app_meta.users.

    Args:
        user: dict with keys role, sales_hierarchy_level, and the *_code fields.

    Returns:
        RbacFilter with clause="" and params=[] for unrestricted roles.
    """
    role = (user.get("role") or "").upper()
    level = (user.get("sales_hierarchy_level") or role).upper()

    # Unrestricted roles
    if level in ("NSM", "ADMIN") or role in ("NSM", "ADMIN", "ANALYST"):
        return RbacFilter(clause="", params=[])

    mapping = _HIERARCHY_MAP.get(level)
    if not mapping:
        # Unknown level — default to no data (safe fallback)
        return RbacFilter(clause="1 = 0", params=[])

    col, attr = mapping
    value = user.get(attr)
    if not value:
        # User has the level set but no code — no data (safe fallback)
        return RbacFilter(clause="1 = 0", params=[])

    return RbacFilter(clause=f"{col} = %s", params=[value])


def apply_rbac_to_query(base_sql: str, params: list[Any], rbac: RbacFilter) -> tuple[str, list[Any]]:
    """
    Append the RBAC WHERE fragment to an existing SQL string.

    Args:
        base_sql: SQL string that already ends with a WHERE or AND-able clause.
        params:   Existing bind params list.
        rbac:     RbacFilter from build_rbac_filter().

    Returns:
        (final_sql, final_params) tuple ready for cursor.execute().
    """
    if not rbac.clause:
        return base_sql, list(params)
    return f"{base_sql} AND {rbac.clause}", list(params) + rbac.params
