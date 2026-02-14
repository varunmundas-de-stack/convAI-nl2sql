"""
QCO Store - Redis-backed storage for Query Context Objects.

Stores QCOs keyed by session_id with automatic expiration.
Falls back to in-memory storage if Redis is unavailable.
"""

import json
import logging
import os
import threading
import time
from typing import Optional

import redis

from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QCO_TTL_SECONDS = int(os.getenv("QCO_TTL", "1800"))  # 30 minutes default
ALL_TIME_YEARS_BACK = 25  # For "all_time" window - go back 25 years


class QCONotFound(Exception):
    """Raised when no QCO exists for a session."""
    pass


class QCOStore:
    """Redis-backed QCO store with automatic expiration and thread-safe initialization."""

    def __init__(self, redis_url: str = REDIS_URL, ttl: int = QCO_TTL_SECONDS):
        self.ttl = ttl
        self._redis: Optional[redis.Redis] = None
        self._redis_url = redis_url
        self._fallback_store: dict[str, tuple[QueryContextObject, float]] = {}  # (qco, timestamp)
        self._use_fallback = False
        self._lock = threading.Lock()  # Thread-safe initialization

    def _get_redis(self) -> Optional[redis.Redis]:
        """Lazy initialization of Redis connection (thread-safe)."""
        if self._use_fallback:
            return None

        if self._redis is None:
            with self._lock:
                # Double-check after acquiring lock
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
    
    def _cleanup_expired_fallback(self) -> None:
        """Remove expired entries from fallback store to prevent memory leak."""
        now = time.time()
        expired = [
            session_id
            for session_id, (qco, timestamp) in self._fallback_store.items()
            if now - timestamp > self.ttl
        ]
        for session_id in expired:
            del self._fallback_store[session_id]
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired QCO(s) from fallback store")

    def save(self, session_id: str, qco: QueryContextObject) -> None:
        """Save QCO for a session."""
        r = self._get_redis()

        if r is None:
            self._fallback_store[session_id] = (qco, time.time())
            self._cleanup_expired_fallback()
            logger.info(f"Saved QCO for session {session_id} to in-memory fallback")
            return

        try:
            key = self._key(session_id)
            data = qco.model_dump_json()
            r.setex(key, self.ttl, data)
            logger.info(f"Saved QCO for session {session_id} to Redis (TTL={self.ttl}s)")
        except redis.RedisError as e:
            logger.error(f"Redis QCO save failed, using fallback: {e}")
            self._fallback_store[session_id] = (qco, time.time())
            self._cleanup_expired_fallback()

    def load(self, session_id: str) -> Optional[QueryContextObject]:
        """
        Load QCO for a session.
        
        Returns None if no QCO exists (not an error — first query in session).
        Handles schema version migration gracefully.
        """
        r = self._get_redis()

        if r is None:
            entry = self._fallback_store.get(session_id)
            if entry:
                qco, timestamp = entry
                # Check if expired
                if time.time() - timestamp > self.ttl:
                    del self._fallback_store[session_id]
                    logger.debug(f"QCO for session {session_id} expired in fallback")
                    return None
                logger.debug(f"Loaded QCO for session {session_id} from fallback")
                return qco
            return None

        try:
            key = self._key(session_id)
            data = r.get(key)
            if data is None:
                return None
            
            # Try to load QCO
            try:
                qco = QueryContextObject.model_validate_json(data)
                logger.debug(f"Loaded QCO for session {session_id} from Redis (v{qco.schema_version})")
                return qco
            except Exception as e:
                # Schema version mismatch or validation error
                logger.warning(f"Failed to load QCO for session {session_id} (likely schema version mismatch): {e}")
                # Delete invalid QCO
                r.delete(key)
                return None
                
        except redis.RedisError as e:
            logger.error(f"Redis QCO load failed, checking fallback: {e}")
            entry = self._fallback_store.get(session_id)
            if entry:
                qco, timestamp = entry
                if time.time() - timestamp > self.ttl:
                    del self._fallback_store[session_id]
                    return None
                return qco
            return None

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
