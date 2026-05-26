"""
Redis conversation session cache — last 10 turns per user/session.

Key  : conv:{user_id}:{session_id}
Value: JSON list of {role, content} dicts (most recent last)
TTL  : 3600s
DB   : 2 (separate from query cache DB 1 and default DB 0)
"""

import json
import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)

_MAX_TURNS = 10
_TTL = 3600
_DB = 2


def _client() -> redis.Redis:
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=_DB,
        decode_responses=True,
    )


def _key(user_id: str, session_id: str) -> str:
    return f"conv:{user_id}:{session_id}"


def get_session_turns(user_id: str, session_id: Optional[str]) -> list[dict]:
    """Return cached turns for this user/session, or [] on miss/error."""
    if not session_id:
        return []
    try:
        raw = _client().get(_key(user_id, session_id))
        return json.loads(raw) if raw else []
    except Exception as e:
        logger.warning(f"[RedisSession] get failed: {e}")
        return []


def append_session_turn(user_id: str, session_id: Optional[str], role: str, content: str) -> None:
    """Append a turn, keep only last _MAX_TURNS, refresh TTL."""
    if not session_id:
        return
    try:
        r = _client()
        k = _key(user_id, session_id)
        raw = r.get(k)
        turns: list[dict] = json.loads(raw) if raw else []
        turns.append({"role": role, "content": content})
        turns = turns[-_MAX_TURNS:]
        r.set(k, json.dumps(turns), ex=_TTL)
    except Exception as e:
        logger.warning(f"[RedisSession] append failed (non-fatal): {e}")
