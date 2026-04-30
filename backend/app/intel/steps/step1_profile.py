"""
Step 1 — Interest Profile Mining.

Reads the last 90 days of chat_messages for a user and extracts:
  - top_kpis:              weighted list of metric names
  - top_entities:          weighted list of {type, value} pairs (zone, brand, etc.)
  - top_dimensions:        most-grouped-by dimensions
  - preferred_time_windows: time window keywords (MTD, last_7d, etc.)

Source of truth for KPI extraction is the structured `raw_data->>'intent'`
JSONB column (populated by the main pipeline). Raw text parsing is used as a
fallback for older messages that predate structured logging.

Upserts the result into app_meta.user_interest_profiles via ON CONFLICT (user_id).
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.intel.db import get_conn, dict_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Catalog constants — mirrors what catalog.yaml exposes
# ---------------------------------------------------------------------------
_KNOWN_KPIS: set[str] = {
    "net_value", "gross_value", "tax_value",
    "billed_qty", "billed_volume", "billed_weight",
}

_KPI_ALIASES: dict[str, str] = {
    "revenue": "net_value",
    "net revenue": "net_value",
    "sales": "net_value",
    "gross": "gross_value",
    "quantity": "billed_qty",
    "qty": "billed_qty",
    "volume": "billed_volume",
    "weight": "billed_weight",
}

_KNOWN_DIMENSIONS: set[str] = {
    "zone", "state", "city", "brand", "category",
    "sub_category", "retailer_type", "channel",
    "distributor", "salesrep", "route",
}

_TIME_WINDOW_KEYWORDS: list[str] = [
    "MTD", "last_7d", "last_30d", "last_90d", "YTD", "weekly", "daily",
    "this month", "last month", "this week", "last week",
]

# Recency decay: messages older than 30d are down-weighted
_RECENT_DAYS = 30
_DECAY_FACTOR = 0.5   # messages 30-90d old get weight × 0.5


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def refresh_interest_profile(user: dict[str, Any], conn=None) -> None:
    """
    Mine the last 90 days of chat_messages for ``user`` and upsert
    into ``app_meta.user_interest_profiles``.

    Args:
        user: Row dict from app_meta.users (must include user_id, client_id, role).
        conn: Optional existing psycopg2 connection (for testing). If None,
              a fresh connection is opened and committed.
    """
    user_id = user["user_id"]
    client_id = user["client_id"]
    logger.info(f"[step1] Refreshing interest profile: user_id={user_id}")

    messages = _fetch_messages(user_id, conn)
    if not messages:
        logger.info(f"[step1] No messages found for user_id={user_id}, skipping")
        return

    kpi_weights: dict[str, float] = defaultdict(float)
    entity_weights: dict[tuple[str, str], float] = defaultdict(float)
    dim_weights: dict[str, float] = defaultdict(float)
    time_window_weights: dict[str, float] = defaultdict(float)

    now = datetime.now(timezone.utc)

    for msg in messages:
        weight = _recency_weight(msg["created_at"], now)
        _extract_from_message(msg, weight, kpi_weights, entity_weights, dim_weights, time_window_weights)

    profile = {
        "top_kpis": _to_weighted_list(kpi_weights, "kpi"),
        "top_entities": [
            {"type": t, "value": v, "weight": round(w, 3)}
            for (t, v), w in sorted(entity_weights.items(), key=lambda x: -x[1])[:20]
        ],
        "top_dimensions": [d for d, _ in sorted(dim_weights.items(), key=lambda x: -x[1])[:10]],
        "preferred_time_windows": [tw for tw, _ in sorted(time_window_weights.items(), key=lambda x: -x[1])[:5]],
    }

    _upsert_profile(user_id, client_id, len(messages), profile, conn)
    logger.info(
        f"[step1] Profile upserted: user_id={user_id}, "
        f"kpis={[k['kpi'] for k in profile['top_kpis']]}, "
        f"messages_analyzed={len(messages)}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_messages(user_id: int, conn=None) -> list[dict[str, Any]]:
    sql = """
        SELECT m.content, m.raw_data, m.created_at
        FROM app_meta.chat_messages m
        JOIN app_meta.chat_sessions s ON s.session_id = m.session_id
        WHERE m.user_id = %s
          AND m.role = 'user'
          AND m.created_at >= NOW() - INTERVAL '90 days'
        ORDER BY m.created_at DESC
    """
    if conn:
        with dict_cursor(conn) as cur:
            cur.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]

    with get_conn() as c:
        with dict_cursor(c) as cur:
            cur.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]


def _recency_weight(created_at: Any, now: datetime) -> float:
    """Return 1.0 for messages < 30d old, 0.5 for 30-90d."""
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = (now - created_at).days
    return 1.0 if age_days <= _RECENT_DAYS else _DECAY_FACTOR


def _extract_from_message(
    msg: dict[str, Any],
    weight: float,
    kpi_weights: dict,
    entity_weights: dict,
    dim_weights: dict,
    time_window_weights: dict,
) -> None:
    """Extract signals from one chat message row."""
    # ── Priority path: structured intent from raw_data JSONB ──────────────
    raw_data = msg.get("raw_data")
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            raw_data = None

    if raw_data and isinstance(raw_data, dict):
        _mine_structured(raw_data, weight, kpi_weights, entity_weights, dim_weights, time_window_weights)

    # ── Fallback: raw text scanning ────────────────────────────────────────
    content = (msg.get("content") or "").lower()
    _mine_text(content, weight, kpi_weights, entity_weights, dim_weights, time_window_weights)


def _mine_structured(
    raw_data: dict[str, Any],
    weight: float,
    kpi_weights: dict,
    entity_weights: dict,
    dim_weights: dict,
    time_window_weights: dict,
) -> None:
    """Extract from the pipeline response JSONB (raw_data column)."""
    # Metrics from intent
    for section in ("intent", "merged_intent", "raw_intent"):
        intent = raw_data.get(section) or {}
        if isinstance(intent, str):
            try:
                intent = json.loads(intent)
            except Exception:
                continue

        # metrics list [{name, aggregation}]
        for m in (intent.get("metrics") or []):
            name = m.get("name") if isinstance(m, dict) else str(m)
            if name in _KNOWN_KPIS:
                kpi_weights[name] += weight * 2.0  # structured signal gets 2× boost

        # group_by → dimensions
        for dim in (intent.get("group_by") or []):
            dim_clean = dim.split(".")[0].lower()
            if dim_clean in _KNOWN_DIMENSIONS:
                dim_weights[dim_clean] += weight

        # filters → entities
        for fil in (intent.get("filters") or []):
            if isinstance(fil, dict):
                field = (fil.get("field") or "").split(".")[0].lower()
                value = fil.get("value")
                if field and value:
                    entity_weights[(field, str(value))] += weight

        # time window
        tw = intent.get("time_window") or ""
        if tw:
            time_window_weights[tw] += weight


def _mine_text(
    text: str,
    weight: float,
    kpi_weights: dict,
    entity_weights: dict,
    dim_weights: dict,
    time_window_weights: dict,
) -> None:
    """Scan raw query text for KPI aliases, dimensions, and time keywords."""
    for alias, canonical in _KPI_ALIASES.items():
        if alias in text:
            kpi_weights[canonical] += weight * 0.5  # lower confidence

    for dim in _KNOWN_DIMENSIONS:
        if dim in text:
            dim_weights[dim] += weight * 0.3

    for tw in _TIME_WINDOW_KEYWORDS:
        if tw.lower() in text:
            time_window_weights[tw] += weight


def _to_weighted_list(weights: dict[str, float], key: str) -> list[dict[str, Any]]:
    return [
        {key: k, "weight": round(v, 3)}
        for k, v in sorted(weights.items(), key=lambda x: -x[1])[:10]
    ]


def _upsert_profile(
    user_id: int,
    client_id: str,
    messages_analyzed: int,
    profile: dict[str, Any],
    conn=None,
) -> None:
    sql = """
        INSERT INTO app_meta.user_interest_profiles
          (user_id, client_id, top_kpis, top_entities, top_dimensions,
           preferred_time_windows, chat_messages_analyzed, last_computed_at, updated_at)
        VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW(), NOW())
        ON CONFLICT (user_id) DO UPDATE SET
          top_kpis                = EXCLUDED.top_kpis,
          top_entities            = EXCLUDED.top_entities,
          top_dimensions          = EXCLUDED.top_dimensions,
          preferred_time_windows  = EXCLUDED.preferred_time_windows,
          chat_messages_analyzed  = EXCLUDED.chat_messages_analyzed,
          last_computed_at        = NOW(),
          updated_at              = NOW()
    """
    args = (
        user_id,
        client_id,
        json.dumps(profile["top_kpis"]),
        json.dumps(profile["top_entities"]),
        json.dumps(profile["top_dimensions"]),
        json.dumps(profile["preferred_time_windows"]),
        messages_analyzed,
    )
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
        return
    with get_conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, args)
