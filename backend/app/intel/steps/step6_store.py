"""
Step 6 — Deduplicate + Store.

Computes a deterministic SHA-256 insight_hash and inserts into
app_meta.insights using ON CONFLICT (insight_hash) DO NOTHING.

Hash input: tenant_id + user_id + kpi + dimension_filters + period_start
            + period_end + detection_method

TTL:
  - daily granularity  → expires_at = NOW() + 48h
  - weekly granularity → expires_at = NOW() + 7d
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from app.intel.db import get_conn

logger = logging.getLogger(__name__)


def deduplicate_and_store(
    enriched_signals: list[dict[str, Any]],
    user: dict[str, Any],
    client_id: str,
    granularity: str = "daily",
    conn=None,
) -> dict[str, int]:
    """
    Insert enriched signal dicts as insights. Silently skips duplicates.

    Args:
        enriched_signals: Signals from step5 with narrative fields.
        user:             Row dict from app_meta.users.
        client_id:        Tenant identifier.
        granularity:      'daily' | 'weekly' — drives TTL.
        conn:             Optional psycopg2 connection.

    Returns:
        Dict with keys: stored, suppressed.
    """
    stored = 0
    suppressed = 0

    for signal in enriched_signals:
        try:
            inserted = _store_one(signal, user, client_id, granularity, conn)
            if inserted:
                stored += 1
            else:
                suppressed += 1
        except Exception as e:
            logger.warning(
                f"[step6] Store failed for watch_id={signal.get('watch_id')}: {e}"
            )
            suppressed += 1

    logger.info(f"[step6] Stored={stored}, Suppressed={suppressed} for user_id={user['user_id']}")
    return {"stored": stored, "suppressed": suppressed}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def compute_insight_hash(
    tenant_id: str,
    user_id: int,
    kpi: str,
    dimension_filters: dict,
    period_start: str,
    period_end: str,
    detection_method: str,
) -> str:
    payload = json.dumps(
        {
            "tenant":  tenant_id,
            "user":    user_id,
            "kpi":     kpi,
            "filters": sorted(dimension_filters.items()) if dimension_filters else [],
            "period":  f"{period_start}/{period_end}",
            "method":  detection_method,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:64]


def _ttl_interval(granularity: str) -> str:
    return "INTERVAL '7 days'" if granularity == "weekly" else "INTERVAL '48 hours'"


def _store_one(
    signal: dict[str, Any],
    user: dict[str, Any],
    client_id: str,
    granularity: str,
    conn=None,
) -> bool:
    """Insert one insight row. Returns True if actually inserted, False if suppressed."""
    user_id = user["user_id"]
    kpi = signal.get("kpi") or ""
    dim_filters = signal.get("dimension_filters") or {}
    period_start = signal.get("period_start") or ""
    period_end = signal.get("period_end") or ""
    detection_method = signal.get("type") or "anomaly"
    severity = signal.get("severity") or "high"
    priority = _map_priority(severity)

    insight_hash = compute_insight_hash(
        tenant_id=client_id,
        user_id=user_id,
        kpi=kpi,
        dimension_filters=dim_filters if isinstance(dim_filters, dict) else {},
        period_start=period_start,
        period_end=period_end,
        detection_method=detection_method,
    )

    # Build hierarchy_level / hierarchy codes from user
    hierarchy_level = (user.get("sales_hierarchy_level") or user.get("role") or "all").upper()

    # Generate a stable insight_id from the hash
    insight_id = f"intel_{insight_hash[:40]}"

    # Merge title / description from narrative (step5) output
    title = signal.get("title") or f"{kpi} {detection_method} detected"
    description = signal.get("description") or signal.get("narrative") or ""
    suggested_action = signal.get("suggested_action") or ""

    sql = f"""
        INSERT INTO app_meta.insights (
            insight_id, tenant_id, hierarchy_level,
            salesrep_code, so_code, asm_code, zsm_code, nsm_code,
            title, description, insight_type, priority,
            metric_value, metric_change_pct, suggested_action,
            data_json, expires_at, is_active,
            watch_id, detection_method, period_start, period_end,
            insight_hash
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s::jsonb, NOW() + {_ttl_interval(granularity)}, TRUE,
            %s, %s, %s::date, %s::date,
            %s
        )
        ON CONFLICT (insight_hash) DO NOTHING
    """

    args = (
        insight_id,
        client_id,
        hierarchy_level,
        user.get("salesrep_code"),
        user.get("so_code"),
        user.get("asm_code"),
        user.get("zsm_code"),
        user.get("nsm_code"),
        title[:500],
        description,
        detection_method,
        priority,
        signal.get("latest_value"),
        signal.get("change_pct"),
        suggested_action,
        json.dumps({"signal": signal}),
        signal.get("watch_id"),
        detection_method,
        period_start or None,
        period_end or None,
        insight_hash,
    )

    inserted = False
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            inserted = cur.rowcount > 0
    else:
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, args)
                inserted = cur.rowcount > 0

    return inserted


def _map_priority(severity: str) -> str:
    return {"critical": "high", "high": "high", "medium": "medium", "low": "low"}.get(
        severity.lower(), "medium"
    )
