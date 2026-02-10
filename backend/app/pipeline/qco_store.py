"""
QCO Store - Redis-backed storage for Query Context Objects.

Stores QCOs keyed by session_id with automatic expiration.
Falls back to in-memory storage if Redis is unavailable.
"""

import json
import logging
import os
from typing import Optional

import redis

from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QCO_TTL_SECONDS = int(os.getenv("QCO_TTL", 1800))  # 30 minutes default


class QCONotFound(Exception):
    """Raised when no QCO exists for a session."""
    pass


class QCOStore:
    """Redis-backed QCO store with automatic expiration."""

    def __init__(self, redis_url: str = REDIS_URL, ttl: int = QCO_TTL_SECONDS):
        self.ttl = ttl
        self._redis: Optional[redis.Redis] = None
        self._redis_url = redis_url
        self._fallback_store: dict[str, QueryContextObject] = {}
        self._use_fallback = False

    def _get_redis(self) -> Optional[redis.Redis]:
        """Lazy initialization of Redis connection."""
        if self._use_fallback:
            return None

        if self._redis is None:
            try:
                self._redis = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                self._redis.ping()
                logger.info(f"QCOStore connected to Redis at {self._redis_url}")
            except redis.ConnectionError as e:
                logger.warning(f"Redis unavailable for QCO store, using in-memory fallback: {e}")
                self._use_fallback = True
                return None
        return self._redis

    def _key(self, session_id: str) -> str:
        return f"qco:{session_id}"

    def save(self, session_id: str, qco: QueryContextObject) -> None:
        """Save QCO for a session."""
        r = self._get_redis()

        if r is None:
            self._fallback_store[session_id] = qco
            logger.info(f"Saved QCO for session {session_id} to in-memory fallback")
            return

        try:
            key = self._key(session_id)
            data = qco.model_dump_json()
            r.setex(key, self.ttl, data)
            logger.info(f"Saved QCO for session {session_id} to Redis (TTL={self.ttl}s)")
        except redis.RedisError as e:
            logger.error(f"Redis QCO save failed, using fallback: {e}")
            self._fallback_store[session_id] = qco

    def load(self, session_id: str) -> Optional[QueryContextObject]:
        """
        Load QCO for a session.
        
        Returns None if no QCO exists (not an error — first query in session).
        """
        r = self._get_redis()

        if r is None:
            qco = self._fallback_store.get(session_id)
            if qco:
                logger.debug(f"Loaded QCO for session {session_id} from fallback")
            return qco

        try:
            key = self._key(session_id)
            data = r.get(key)
            if data is None:
                return None
            logger.debug(f"Loaded QCO for session {session_id} from Redis")
            return QueryContextObject.model_validate_json(data)
        except redis.RedisError as e:
            logger.error(f"Redis QCO load failed, checking fallback: {e}")
            return self._fallback_store.get(session_id)

    def delete(self, session_id: str) -> None:
        """Delete QCO for a session."""
        r = self._get_redis()

        if r is None:
            self._fallback_store.pop(session_id, None)
            return

        try:
            r.delete(self._key(session_id))
            logger.info(f"Deleted QCO for session {session_id}")
        except redis.RedisError as e:
            logger.error(f"Redis QCO delete failed: {e}")
            self._fallback_store.pop(session_id, None)


# Singleton
_qco_store = QCOStore()


def save_qco(session_id: str, qco: QueryContextObject) -> None:
    _qco_store.save(session_id, qco)


def load_qco(session_id: str) -> Optional[QueryContextObject]:
    return _qco_store.load(session_id)


def delete_qco(session_id: str) -> None:
    _qco_store.delete(session_id)
