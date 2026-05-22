"""
Cache Manager — 3-Tier Semantic Cache

Tier 1: Golden Q&A FAISS in-memory index (cosine >= 0.95 → immediate return, zero Claude calls)
Tier 2: Redis semantic cache per user (cosine >= 0.92 → skip DSPy + Cube + Claude)
Tier 3: Live pipeline (miss on both tiers)

Token-saving rationale:
- Tier 1 hit: saves ~2000 tokens (intent extraction + cube narration calls)
- Tier 2 hit: saves ~1500 tokens (same minus FAISS overhead)
- Every miss falls through to the existing pipeline unchanged
"""

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports for heavy ML deps (sentence-transformers / faiss)
# ---------------------------------------------------------------------------

_embedder = None
_embedder_lock = threading.Lock()

def _get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("SentenceTransformer loaded: all-MiniLM-L6-v2")
    return _embedder


def _embed(text: str) -> np.ndarray:
    emb = _get_embedder().encode([text], normalize_embeddings=True)
    return emb[0].astype("float32")


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    # Both already L2-normalised by sentence-transformers, so dot == cosine
    return float(np.dot(a, b))


# ---------------------------------------------------------------------------
# TTL rules per intent tag (seconds)
# ---------------------------------------------------------------------------

_INTENT_TTL: Dict[str, int] = {
    "sales_trend":    86_400,   # 24 h — aggregation, low churn
    "market_share":   86_400,
    "forecast":       86_400,
    "promo_lift":     86_400,
    "product_mix":    86_400,
    "customer_segment": 86_400,
    "inventory":      3_600,    # 1 h — transactional / volatile
    "distribution":   3_600,
    "pricing":        3_600,
    "competitor":     3_600,
}
_DEFAULT_TTL = 3_600


def _ttl_for_intent(intent_tag: Optional[str]) -> int:
    return _INTENT_TTL.get(intent_tag or "", _DEFAULT_TTL)


# ---------------------------------------------------------------------------
# Stats counters (in-memory, reset on restart)
# ---------------------------------------------------------------------------

@dataclass
class _Stats:
    golden_hits: int = 0
    semantic_hits: int = 0
    live_hits: int = 0
    tokens_saved: int = 0
    top_questions: List[str] = field(default_factory=list)

_STATS = _Stats()
_STATS_LOCK = threading.Lock()


def _record_hit(tier: str, question: str = "") -> None:
    with _STATS_LOCK:
        if tier == "golden":
            _STATS.golden_hits += 1
            _STATS.tokens_saved += 2000  # intent extraction + narration saved
        elif tier == "semantic":
            _STATS.semantic_hits += 1
            _STATS.tokens_saved += 1500
        else:
            _STATS.live_hits += 1
        if question:
            _STATS.top_questions.append(question)
            _STATS.top_questions = _STATS.top_questions[-50:]


def get_cache_stats() -> Dict[str, Any]:
    with _STATS_LOCK:
        total = _STATS.golden_hits + _STATS.semantic_hits + _STATS.live_hits
        from collections import Counter
        top = [q for q, _ in Counter(_STATS.top_questions).most_common(10)]
        return {
            "golden_hits": _STATS.golden_hits,
            "semantic_hits": _STATS.semantic_hits,
            "live_hits": _STATS.live_hits,
            "total_requests": total,
            "tokens_saved_estimate": _STATS.tokens_saved,
            "top_cached_questions": top,
        }


# ===========================================================================
# TIER 1 — Golden Q&A Cache
# ===========================================================================

@dataclass
class GoldenEntry:
    id: str
    intent: str
    question_variants: List[str]
    canonical_cube_query: Dict[str, Any]
    prebuilt_answer: str
    hit_count: int = 0
    last_refreshed: Optional[str] = None
    # Runtime: embedding matrix for all variants (shape N×384)
    _embeddings: Optional[np.ndarray] = field(default=None, repr=False)


class GoldenQACache:
    """
    Loads golden_qa.json into a FAISS flat-IP index at startup.
    Cosine >= 0.95 → return prebuilt_answer without any model call.
    """

    SIMILARITY_THRESHOLD = 0.95

    def __init__(self):
        self._entries: List[GoldenEntry] = []
        # FAISS index — built lazily after load
        self._index = None
        self._index_to_entry: List[int] = []  # faiss row idx → _entries idx
        self._lock = threading.RLock()
        self._loaded = False

    # ------------------------------------------------------------------
    # Data file path
    # ------------------------------------------------------------------

    @staticmethod
    def _data_path() -> Path:
        return Path(__file__).parent.parent / "data" / "golden_qa.json"

    # ------------------------------------------------------------------
    # Load + build index
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load golden_qa.json and build FAISS index. Called at startup."""
        path = self._data_path()
        if not path.exists():
            logger.warning(f"golden_qa.json not found at {path}; Tier-1 cache disabled")
            return

        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        entries = []
        for item in raw:
            entries.append(GoldenEntry(
                id=item["id"],
                intent=item.get("intent", ""),
                question_variants=item.get("question_variants", []),
                canonical_cube_query=item.get("canonical_cube_query", {}),
                prebuilt_answer=item.get("prebuilt_answer", "PENDING_REFRESH"),
                hit_count=item.get("hit_count", 0),
                last_refreshed=item.get("last_refreshed"),
            ))

        with self._lock:
            self._entries = entries
            self._rebuild_index()
            self._loaded = True

        logger.info(f"Golden Q&A cache loaded: {len(entries)} entries, "
                    f"{len(self._index_to_entry)} variant embeddings indexed")

    def _rebuild_index(self) -> None:
        """Build FAISS inner-product index from all question_variants."""
        try:
            import faiss
        except ImportError:
            logger.error("faiss-cpu not installed; install it via requirements.txt")
            return

        all_embs = []
        row_to_entry = []

        for eidx, entry in enumerate(self._entries):
            for variant in entry.question_variants:
                if not variant.strip():
                    continue
                emb = _embed(variant)
                all_embs.append(emb)
                row_to_entry.append(eidx)

        if not all_embs:
            logger.warning("No question variants to embed for golden cache")
            return

        dim = all_embs[0].shape[0]
        index = faiss.IndexFlatIP(dim)  # inner product on normalized vecs == cosine
        mat = np.vstack(all_embs)
        index.add(mat)

        self._index = index
        self._index_to_entry = row_to_entry

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, question: str) -> Optional[Dict[str, Any]]:
        """
        Return a cached answer dict if cosine similarity >= threshold.
        Returns None on miss (Tier-2 / Tier-3 fallthrough).
        Token saving: prevents all LLM calls for repetitive CPG questions.
        """
        if not self._loaded or self._index is None:
            return None

        q_emb = _embed(question).reshape(1, -1)

        with self._lock:
            scores, indices = self._index.search(q_emb, 1)
            if indices[0][0] < 0:
                return None

            score = float(scores[0][0])
            if score < self.SIMILARITY_THRESHOLD:
                return None

            eidx = self._index_to_entry[indices[0][0]]
            entry = self._entries[eidx]

            # Skip if answer not yet materialised
            if entry.prebuilt_answer in ("PENDING_REFRESH", "", None):
                return None

            # Bump hit counter (in memory; also persisted to JSON on refresh)
            entry.hit_count += 1

        _record_hit("golden", question)
        logger.info(f"[Tier-1 HIT] score={score:.3f} intent={entry.intent} id={entry.id}")

        return {
            "answer_text": entry.prebuilt_answer,
            "intent_tag": entry.intent,
            "cube_query": entry.canonical_cube_query,
            "cache_tier": "golden",
            "cache_hit": True,
            "golden_entry_id": entry.id,
            "similarity_score": score,
        }

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": e.id,
                    "intent": e.intent,
                    "question_variants": e.question_variants,
                    "prebuilt_answer": e.prebuilt_answer,
                    "hit_count": e.hit_count,
                    "last_refreshed": e.last_refreshed,
                }
                for e in self._entries
            ]

    # ------------------------------------------------------------------
    # Refresh (re-run canonical SQL via Cube.js, update prebuilt_answer)
    # ------------------------------------------------------------------

    async def refresh_all(self) -> Dict[str, Any]:
        """
        Re-run canonical_cube_query for every entry via the Cube.js executor,
        then ask Claude to narrate the result, and persist to golden_qa.json.
        """
        from app.services.cube.cube_executor import execute_cube_query
        from app.llm.service import generate_insight_narrative

        updated = 0
        errors = 0
        path = self._data_path()

        with self._lock:
            entries_snapshot = list(self._entries)

        for entry in entries_snapshot:
            if not entry.canonical_cube_query:
                continue
            try:
                result = await execute_cube_query(entry.canonical_cube_query)
                narrative = await generate_insight_narrative(
                    data=result,
                    question=entry.question_variants[0] if entry.question_variants else "",
                    intent_tag=entry.intent,
                )
                with self._lock:
                    entry.prebuilt_answer = narrative
                    entry.last_refreshed = datetime.now(timezone.utc).isoformat()
                updated += 1
            except Exception as e:
                logger.warning(f"Golden refresh failed for {entry.id}: {e}")
                errors += 1

        # Persist updated entries to disk
        self._save_to_disk(path)
        return {"updated": updated, "errors": errors, "total": len(entries_snapshot)}

    def _save_to_disk(self, path: Path) -> None:
        with self._lock:
            data = [
                {
                    "id": e.id,
                    "intent": e.intent,
                    "question_variants": e.question_variants,
                    "canonical_cube_query": e.canonical_cube_query,
                    "prebuilt_answer": e.prebuilt_answer,
                    "hit_count": e.hit_count,
                    "last_refreshed": e.last_refreshed,
                }
                for e in self._entries
            ]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        logger.info(f"golden_qa.json saved ({len(data)} entries)")


# Singleton
golden_cache = GoldenQACache()


# ===========================================================================
# TIER 2 — Semantic Redis Cache
# ===========================================================================

class SemanticCache:
    """
    Redis-backed semantic cache keyed by user_id + embedding hash.
    Cosine >= 0.92 against stored embeddings → return cached answer_text.
    Token saving: skips DSPy intent extraction, Cube.js HTTP call, Claude narration.
    """

    SIMILARITY_THRESHOLD = 0.92
    # Sorted set that tracks per-user embedding keys (score = timestamp)
    _INDEX_KEY_TPL = "semcache:idx:{user_id}"
    # Hash entry for each cached question
    _ENTRY_KEY_TPL = "semcache:{user_id}:{emb_hash}"

    def __init__(self):
        self._redis: Optional[redis.Redis] = None

    def _r(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis(
                host=os.getenv("REDIS_HOST", "redis"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_CACHE_DB", "1")),  # separate db from sessions
                decode_responses=False,
            )
        return self._redis

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _emb_hash(emb: np.ndarray) -> str:
        return hashlib.sha1(emb.tobytes()).hexdigest()[:16]

    def _entry_key(self, user_id: str, emb_hash: str) -> str:
        return self._ENTRY_KEY_TPL.format(user_id=user_id, emb_hash=emb_hash)

    def _index_key(self, user_id: str) -> str:
        return self._INDEX_KEY_TPL.format(user_id=user_id)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, user_id: str, question: str) -> Optional[Dict[str, Any]]:
        """
        Find the nearest cached question for this user.
        Returns cached payload dict or None on miss.
        """
        try:
            r = self._r()
            idx_key = self._index_key(user_id)
            # Fetch all stored embedding-hashes for this user from sorted set
            members = r.zrange(idx_key, 0, -1)
            if not members:
                return None

            q_emb = _embed(question)

            best_score = -1.0
            best_payload: Optional[bytes] = None

            for member in members:
                emb_hash = member.decode() if isinstance(member, bytes) else member
                entry_key = self._entry_key(user_id, emb_hash)
                raw = r.hget(entry_key, "embedding")
                if raw is None:
                    continue
                stored_emb = np.frombuffer(raw, dtype="float32")
                score = _cosine(q_emb, stored_emb)
                if score > best_score:
                    best_score = score
                    if score >= self.SIMILARITY_THRESHOLD:
                        best_payload = r.hget(entry_key, "payload")

            if best_score < self.SIMILARITY_THRESHOLD or best_payload is None:
                return None

            payload = json.loads(best_payload.decode())
            _record_hit("semantic", question)
            logger.info(f"[Tier-2 HIT] user={user_id} score={best_score:.3f} intent={payload.get('intent_tag')}")
            payload["cache_tier"] = "semantic"
            payload["cache_hit"] = True
            payload["similarity_score"] = best_score
            return payload

        except Exception as e:
            logger.warning(f"[Tier-2] Redis lookup error (non-fatal): {e}")
            return None

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(
        self,
        user_id: str,
        question: str,
        sql_generated: Optional[str],
        cube_query: Optional[Dict],
        result_json: Any,
        answer_text: str,
        intent_tag: Optional[str],
    ) -> None:
        """
        Store a live-pipeline result into the Redis semantic cache.
        TTL is intent-aware (24 h for aggregations, 1 h for transactional).
        """
        try:
            r = self._r()
            q_emb = _embed(question)
            emb_hash = self._emb_hash(q_emb)
            ttl = _ttl_for_intent(intent_tag)

            payload = {
                "question_text": question,
                "sql_generated": sql_generated or "",
                "cube_query": cube_query or {},
                "result_json": result_json,
                "answer_text": answer_text,
                "intent_tag": intent_tag or "",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ttl_hours": ttl // 3600,
            }

            entry_key = self._entry_key(user_id, emb_hash)
            r.hset(entry_key, mapping={
                "embedding": q_emb.tobytes(),
                "payload": json.dumps(payload, default=str),
            })
            r.expire(entry_key, ttl)

            # Add emb_hash to per-user sorted set (score = epoch, used for ZRANGE)
            idx_key = self._index_key(user_id)
            r.zadd(idx_key, {emb_hash: time.time()})
            r.expire(idx_key, ttl)

            logger.info(f"[Tier-2 STORE] user={user_id} intent={intent_tag} ttl={ttl}s")

        except Exception as e:
            logger.warning(f"[Tier-2] Redis store error (non-fatal): {e}")

    # ------------------------------------------------------------------
    # Clear user cache
    # ------------------------------------------------------------------

    def clear_user(self, user_id: str) -> int:
        """Delete all semantic cache entries for a user. Returns count deleted."""
        try:
            r = self._r()
            idx_key = self._index_key(user_id)
            members = r.zrange(idx_key, 0, -1)
            deleted = 0
            for member in members:
                emb_hash = member.decode() if isinstance(member, bytes) else member
                entry_key = self._entry_key(user_id, emb_hash)
                deleted += r.delete(entry_key)
            r.delete(idx_key)
            logger.info(f"Cleared {deleted} semantic cache entries for user={user_id}")
            return deleted
        except Exception as e:
            logger.warning(f"[Tier-2] clear_user error: {e}")
            return 0


# Singleton
semantic_cache = SemanticCache()
