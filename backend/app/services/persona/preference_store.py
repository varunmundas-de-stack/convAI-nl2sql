"""
User Preference Store — Spec 20 Tier-3 runtime resolution.

Key  : user_prefs:{user_id}
Value: JSON dict of user preference overrides
TTL  : 90 days
DB   : 3 (separate from session DB 2, cache DB 1, default DB 0)
"""

from __future__ import annotations

import json
import logging
import os

import redis

logger = logging.getLogger(__name__)

_TTL_SECONDS = 90 * 24 * 3600  # 90 days
_DB = 3


def _client() -> redis.Redis:
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=_DB,
        decode_responses=True,
    )


def _key(user_id: int) -> str:
    return f"user_prefs:{user_id}"


def save_preferences(user_id: int, prefs: dict) -> None:
    """Store user preference dict in Redis with 90-day TTL."""
    try:
        _client().set(_key(user_id), json.dumps(prefs), ex=_TTL_SECONDS)
        logger.info(f"[PreferenceStore] Saved preferences for user_id={user_id}")
    except Exception as e:
        logger.warning(f"[PreferenceStore] save failed (non-fatal): {e}")


def load_preferences(user_id: int) -> dict:
    """Return stored preference dict, or empty dict if missing/error."""
    try:
        raw = _client().get(_key(user_id))
        return json.loads(raw) if raw else {}
    except Exception as e:
        logger.warning(f"[PreferenceStore] load failed (non-fatal): {e}")
        return {}


def resolve_preferences(user_id: int, card_defaults: dict) -> dict:
    """
    Merge card defaults (lowest priority) with stored user prefs (higher priority).
    Returns the merged dict.
    """
    merged = dict(card_defaults)
    merged.update(load_preferences(user_id))
    return merged
