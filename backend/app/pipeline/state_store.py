"""
Pipeline State Store - Redis-backed storage for pipeline states.

Stores PipelineState objects in Redis with automatic expiration.
Falls back to in-memory storage if Redis is unavailable.
"""

import os
import json
import logging
from typing import Optional
import redis

from app.pipeline.pipeline_state import PipelineState

logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STATE_TTL_SECONDS = int(os.getenv("PIPELINE_STATE_TTL", 3600))  # 1 hour default


class PipelineStateNotFound(Exception):
    """Raised when a pipeline state is not found."""
    pass


class RedisStateStore:
    """Redis-backed state store with automatic expiration."""
    
    def __init__(self, redis_url: str = REDIS_URL, ttl: int = STATE_TTL_SECONDS):
        self.ttl = ttl
        self._redis: Optional[redis.Redis] = None
        self._redis_url = redis_url
        self._fallback_store: dict[str, PipelineState] = {}
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
                    socket_connect_timeout=5
                )
                # Test connection
                self._redis.ping()
                logger.info(f"Connected to Redis at {self._redis_url}")
            except redis.ConnectionError as e:
                logger.warning(f"Redis unavailable, using in-memory fallback: {e}")
                self._use_fallback = True
                return None
        return self._redis
    
    def _state_to_dict(self, state: PipelineState) -> dict:
        """Convert PipelineState to JSON-serializable dict."""
        return {
            "request_id": state.request_id,
            "original_query": state.original_query,
            "intent": state.intent,
            "missing_fields": state.missing_fields,
        }
    
    def _dict_to_state(self, data: dict) -> PipelineState:
        """Convert dict back to PipelineState."""
        return PipelineState(
            request_id=data["request_id"],
            original_query=data["original_query"],
            intent=data["intent"],
            missing_fields=data["missing_fields"],
        )
    
    def _key(self, request_id: str) -> str:
        """Generate Redis key for a request_id."""
        return f"pipeline:state:{request_id}"
    
    def save(self, state: PipelineState) -> None:
        """Save pipeline state to Redis with TTL."""
        r = self._get_redis()

        
        if r is None:
            # Fallback to in-memory
            logger.warning("Redis is not available, using in-memory fallback")
            self._fallback_store[state.request_id] = state
            logger.info(f"Saved state {state.request_id} to in-memory fallback (missing_fields={state.missing_fields})")
            return
            
        try:
            key = self._key(state.request_id)
            data = json.dumps(self._state_to_dict(state))
            r.setex(key, self.ttl, data)
            logger.info(f"Saved state {state.request_id} to Redis with TTL {self.ttl}s (missing_fields={state.missing_fields})")
        except redis.RedisError as e:
            logger.error(f"Redis save failed, using fallback: {e}")
            self._fallback_store[state.request_id] = state
    
    def load(self, request_id: str) -> PipelineState:
        """Load pipeline state from Redis."""
        r = self._get_redis()
        
        if r is None:
            # Fallback to in-memory
            logger.debug(f"Loading state {request_id} from in-memory fallback")
            state = self._fallback_store.get(request_id)
            if state is None:
                logger.info(f"State not found in fallback store: {request_id}. Available keys: {list(self._fallback_store.keys())}")
                raise PipelineStateNotFound(request_id)
            logger.debug(f"Loaded state {request_id} from fallback")
            return state
            
        try:
            key = self._key(request_id)
            logger.debug(f"Loading state from Redis: {key}")
            data = r.get(key)
            
            if data is None:
                # Check if key exists but expired or never existed
                logger.info(f"State not found in Redis: {request_id} (key={key})")
                raise PipelineStateNotFound(request_id)
            
            logger.debug(f"Loaded state {request_id} from Redis")
            return self._dict_to_state(json.loads(data))
        except redis.RedisError as e:
            logger.error(f"Redis load failed, checking fallback: {e}")
            state = self._fallback_store.get(request_id)
            if state is None:
                raise PipelineStateNotFound(request_id)
            return state
    
    def delete(self, request_id: str) -> None:
        """Delete pipeline state from Redis."""
        r = self._get_redis()
        
        if r is None:
            # Fallback to in-memory
            self._fallback_store.pop(request_id, None)
            return
            
        try:
            key = self._key(request_id)
            r.delete(key)
            logger.info(f"Deleted state {request_id}")
        except redis.RedisError as e:
            logger.error(f"Redis delete failed: {e}")
            self._fallback_store.pop(request_id, None)


# Singleton instance
_store = RedisStateStore()


# Public API (backwards compatible)
def save_state(state: PipelineState) -> None:
    """Save pipeline state."""
    _store.save(state)


def load_state(request_id: str) -> PipelineState:
    """Load pipeline state. Raises PipelineStateNotFound if not found."""
    return _store.load(request_id)


def delete_state(request_id: str) -> None:
    """Delete pipeline state."""
    _store.delete(request_id)
