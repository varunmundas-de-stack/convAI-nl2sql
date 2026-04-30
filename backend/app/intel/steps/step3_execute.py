"""
Step 3 — Execute Watches (RBAC-Safe Data Pull).

For each active intel_watch_config, queries the client's tenant fact table
(e.g. client_nestle.fact_secondary_sales) and returns time-series rows for
the configured KPI metric within the lookback window.

RBAC is enforced by appending hierarchy-level WHERE clauses via rbac.py.
All queries run directly against PostgreSQL — NOT through Cube.js —
because this is a background privileged scheduler job, not a user request.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from app.intel.db import get_conn, dict_cursor
from app.intel.rbac import build_rbac_filter, apply_rbac_to_query

logger = logging.getLogger(__name__)

# Maps catalog KPI names to fact table column expressions
_KPI_COLUMN_MAP: dict[str, str] = {
    "net_value":      "SUM(net_value)",
    "gross_value":    "SUM(gross_value)",
    "tax_value":      "SUM(tax_value)",
    "billed_qty":     "SUM(billed_qty)",
    "billed_volume":  "SUM(billed_volume)",
    "billed_weight":  "SUM(billed_weight)",
}

# Maps watch dimension_filters keys → fact table column names
_DIMENSION_COL_MAP: dict[str, str] = {
    "zone":         "zone",
    "state":        "state",
    "city":         "city",
    "brand":        "brand",
    "category":     "category",
    "sub_category": "sub_category",
    "retailer_type": "retailer_type",
    "distributor":  "distributor_code",
    "salesrep":     "salesrep_code",
    "route":        "route_code",
}


def execute_watches(
    user: dict[str, Any],
    watches: list[dict[str, Any]],
    schema_name: str,
    conn=None,
) -> list[dict[str, Any]]:
    """
    Execute all active watches for a user and return enriched watch-result dicts.

    Args:
        user:        Row dict from app_meta.users (for RBAC).
        watches:     List of intel_watch_config row dicts.
        schema_name: Tenant schema name (e.g. 'client_nestle').
        conn:        Optional existing psycopg2 connection.

    Returns:
        List of watch-result dicts:
          {watch_id, kpi, dimension_filters, rows: [{date, value}], period_start, period_end}
    """
    rbac = build_rbac_filter(user)
    results = []

    for watch in watches:
        try:
            result = _execute_one_watch(watch, rbac, schema_name, conn)
            if result:
                results.append(result)
        except Exception as e:
            logger.warning(
                f"[step3] Watch execution failed: watch_id={watch.get('watch_id')}, err={e}"
            )

    logger.info(f"[step3] Executed {len(results)}/{len(watches)} watches for user_id={user['user_id']}")
    return results


def load_active_watches(user_id: int, conn=None) -> list[dict[str, Any]]:
    """Load all active intel_watch_configs for a user."""
    sql = """
        SELECT watch_id, user_id, client_id, kpi, dimension_filters,
               granularity, lookback_days,
               alert_on_pct_change, alert_on_abs_value,
               alert_on_rank_drop, alert_on_days_inactive,
               priority_score
        FROM app_meta.intel_watch_configs
        WHERE user_id = %s AND is_active = TRUE
        ORDER BY priority_score DESC
    """
    if conn:
        with dict_cursor(conn) as cur:
            cur.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]
    with get_conn() as c:
        with dict_cursor(c) as cur:
            cur.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _execute_one_watch(
    watch: dict[str, Any],
    rbac,
    schema_name: str,
    conn=None,
) -> dict[str, Any] | None:
    kpi = watch.get("kpi", "")
    agg_expr = _KPI_COLUMN_MAP.get(kpi)
    if not agg_expr:
        logger.debug(f"[step3] Unknown KPI '{kpi}' for watch_id={watch.get('watch_id')}")
        return None

    lookback = int(watch.get("lookback_days") or 30)
    period_end = date.today()
    period_start = period_end - timedelta(days=lookback)

    dim_filters = watch.get("dimension_filters") or {}
    if isinstance(dim_filters, str):
        try:
            dim_filters = json.loads(dim_filters)
        except Exception:
            dim_filters = {}

    # Build SELECT
    table = f"{schema_name}.fact_secondary_sales"
    base_sql = f"""
        SELECT
            invoice_date::date AS period_date,
            {agg_expr}          AS metric_value
        FROM {table}
        WHERE invoice_date >= %s
          AND invoice_date <= %s
    """
    params: list[Any] = [period_start, period_end]

    # Apply dimension_filters
    for dim_key, dim_val in dim_filters.items():
        col = _DIMENSION_COL_MAP.get(dim_key, dim_key)
        base_sql += f" AND {col} = %s"
        params.append(dim_val)

    # Apply RBAC
    base_sql, params = apply_rbac_to_query(base_sql, params, rbac)

    base_sql += " GROUP BY invoice_date::date ORDER BY invoice_date::date ASC"

    rows = _run_query(base_sql, params, conn)

    if not rows:
        return None

    return {
        "watch_id":          watch["watch_id"],
        "kpi":               kpi,
        "dimension_filters": dim_filters,
        "alert_on_pct_change":    watch.get("alert_on_pct_change"),
        "alert_on_abs_value":     watch.get("alert_on_abs_value"),
        "alert_on_rank_drop":     watch.get("alert_on_rank_drop"),
        "alert_on_days_inactive": watch.get("alert_on_days_inactive"),
        "priority_score":    float(watch.get("priority_score") or 0.5),
        "rows":              [{"date": str(r["period_date"]), "value": float(r["metric_value"] or 0)} for r in rows],
        "period_start":      str(period_start),
        "period_end":        str(period_end),
    }


def _run_query(sql: str, params: list, conn=None) -> list[dict[str, Any]]:
    if conn:
        with dict_cursor(conn) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    with get_conn() as c:
        with dict_cursor(c) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
