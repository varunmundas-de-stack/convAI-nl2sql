"""
Step 2 — Sync Watch Configs.

Diffs the freshly-computed user_interest_profile against the existing
intel_watch_configs rows to:
  - INSERT new watches for emerging KPI × entity combinations
  - UPDATE is_active = FALSE for watches whose combined weight dropped below threshold
  - Never touch user-pinned watches (source = 'user')

Watch priority_score = kpi_weight × entity_weight (capped at 1.0).
Default alert thresholds are set conservatively and can be tuned per watch.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.intel.db import get_conn, dict_cursor

logger = logging.getLogger(__name__)

# Minimum combined weight for a watch to be created / kept active
_MIN_PRIORITY = 0.20

# Alert defaults
_DEFAULT_PCT_CHANGE_THRESHOLD = 15.0   # trigger if metric changes > 15%
_DEFAULT_LOOKBACK_DAYS = 30


def sync_watch_configs(user: dict[str, Any], profile: dict[str, Any] | None, conn=None) -> dict[str, int]:
    """
    Sync intel_watch_configs for ``user`` based on the freshly-mined profile.

    Args:
        user:    Row dict from app_meta.users.
        profile: Row dict from app_meta.user_interest_profiles (may be None if
                 the user has no chat history yet).
        conn:    Optional existing psycopg2 connection.

    Returns:
        Dict with keys: added, deactivated.
    """
    user_id = user["user_id"]
    client_id = user["client_id"]
    logger.info(f"[step2] Syncing watch configs: user_id={user_id}")

    if not profile:
        logger.info(f"[step2] No profile for user_id={user_id}, skipping watch sync")
        return {"added": 0, "deactivated": 0}

    top_kpis: list[dict] = profile.get("top_kpis") or []
    top_entities: list[dict] = profile.get("top_entities") or []

    if isinstance(top_kpis, str):
        try:
            top_kpis = json.loads(top_kpis)
        except Exception:
            top_kpis = []
    if isinstance(top_entities, str):
        try:
            top_entities = json.loads(top_entities)
        except Exception:
            top_entities = []

    # Build desired watch set: kpi × entity combinations above threshold
    desired: dict[tuple[str, str, str], float] = {}   # (kpi, entity_type, entity_value) → priority
    for kpi_item in top_kpis[:5]:                      # top 5 KPIs
        kpi = kpi_item.get("kpi") or kpi_item.get("name", "")
        kw = float(kpi_item.get("weight", 0))
        if not kpi or kw < 0.1:
            continue
        for ent_item in top_entities[:8]:              # top 8 entities
            ent_type = ent_item.get("type", "")
            ent_val = ent_item.get("value", "")
            ew = float(ent_item.get("weight", 0))
            if not ent_type or not ent_val or ew < 0.1:
                continue
            priority = min(kw * ew, 1.0)
            if priority >= _MIN_PRIORITY:
                desired[(kpi, ent_type, ent_val)] = priority

    # ── Load existing system watches ────────────────────────────────────────
    existing = _load_existing_watches(user_id, conn)
    existing_keys = {
        (w["kpi"], _dim_key(w["dimension_filters"]), _val_key(w["dimension_filters"])): w
        for w in existing
    }

    added = 0
    deactivated = 0

    # ── INSERT new watches ──────────────────────────────────────────────────
    for (kpi, ent_type, ent_val), priority in desired.items():
        key = (kpi, ent_type, ent_val)
        if key not in existing_keys:
            _insert_watch(user_id, client_id, kpi, ent_type, ent_val, priority, conn)
            added += 1
            logger.debug(f"[step2] Added watch: {kpi}/{ent_type}={ent_val} priority={priority:.2f}")
        else:
            # Update priority score on existing watch
            _update_priority(existing_keys[key]["watch_id"], priority, conn)

    # ── DEACTIVATE stale system watches ────────────────────────────────────
    for key, watch in existing_keys.items():
        if key not in desired:
            _deactivate_watch(watch["watch_id"], conn)
            deactivated += 1
            logger.debug(f"[step2] Deactivated watch: watch_id={watch['watch_id']}")

    logger.info(f"[step2] Done: user_id={user_id}, added={added}, deactivated={deactivated}")
    return {"added": added, "deactivated": deactivated}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dim_key(dim_filters: Any) -> str:
    """Extract entity type (first key) from dimension_filters JSONB."""
    if isinstance(dim_filters, str):
        try:
            dim_filters = json.loads(dim_filters)
        except Exception:
            return ""
    if isinstance(dim_filters, dict) and dim_filters:
        return next(iter(dim_filters))
    return ""


def _val_key(dim_filters: Any) -> str:
    """Extract entity value (first value) from dimension_filters JSONB."""
    if isinstance(dim_filters, str):
        try:
            dim_filters = json.loads(dim_filters)
        except Exception:
            return ""
    if isinstance(dim_filters, dict) and dim_filters:
        return str(next(iter(dim_filters.values())))
    return ""


def _load_existing_watches(user_id: int, conn=None) -> list[dict[str, Any]]:
    sql = """
        SELECT watch_id, kpi, dimension_filters, priority_score, is_active
        FROM app_meta.intel_watch_configs
        WHERE user_id = %s AND source = 'system' AND is_active = TRUE
    """
    if conn:
        with dict_cursor(conn) as cur:
            cur.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]
    with get_conn() as c:
        with dict_cursor(c) as cur:
            cur.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]


def _insert_watch(
    user_id: int,
    client_id: str,
    kpi: str,
    ent_type: str,
    ent_val: str,
    priority: float,
    conn=None,
) -> None:
    dim_filters = json.dumps({ent_type: ent_val})
    sql = """
        INSERT INTO app_meta.intel_watch_configs
          (user_id, client_id, kpi, dimension_filters, granularity, lookback_days,
           alert_on_pct_change, source, priority_score, is_active)
        VALUES (%s, %s, %s, %s::jsonb, 'daily', %s, %s, 'system', %s, TRUE)
    """
    args = (user_id, client_id, kpi, dim_filters, _DEFAULT_LOOKBACK_DAYS,
            _DEFAULT_PCT_CHANGE_THRESHOLD, round(priority, 4))
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
        return
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, args)


def _update_priority(watch_id: int, priority: float, conn=None) -> None:
    sql = """
        UPDATE app_meta.intel_watch_configs
        SET priority_score = %s, updated_at = NOW()
        WHERE watch_id = %s
    """
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, (round(priority, 4), watch_id))
        return
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, (round(priority, 4), watch_id))


def _deactivate_watch(watch_id: int, conn=None) -> None:
    sql = """
        UPDATE app_meta.intel_watch_configs
        SET is_active = FALSE, updated_at = NOW()
        WHERE watch_id = %s AND source = 'system'
    """
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, (watch_id,))
        return
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, (watch_id,))
