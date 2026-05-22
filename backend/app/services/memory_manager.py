"""
Persistent User Memory Manager

Stores the last 20 conversation turns per user in a SQLite sidecar (memory.db).
On each new question, fetches this user's history, computes similarity with the
current question, and injects top-5 similar prior turns as context into DSPy
intent extraction — saving tokens by reducing ambiguity without extra LLM calls.
"""

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Memory DB lives next to rlhf.db in the backend root
_DB_PATH = Path(__file__).parent.parent.parent.parent / "memory.db"
_MAX_TURNS_PER_USER = 20
_CONTEXT_TOP_K = 5
_CONTEXT_MIN_SIMILARITY = 0.75

_DB_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def init_memory_db() -> None:
    """Create memory.db and user_memory table if not already present."""
    with _db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_memory (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT    NOT NULL,
                session_id    TEXT,
                turn_id       TEXT,
                question      TEXT    NOT NULL,
                answer        TEXT,
                intent_tag    TEXT,
                -- BLOB: float32 numpy array (384-dim from all-MiniLM-L6-v2)
                question_embedding BLOB,
                timestamp     TEXT    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_um_user ON user_memory(user_id)")
    logger.info(f"memory.db initialised at {_DB_PATH}")


@contextmanager
def _db_conn():
    with _DB_LOCK:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Embedding helper (re-uses cache_manager's singleton to avoid double-loading)
# ---------------------------------------------------------------------------

def _embed(text: str) -> np.ndarray:
    from app.services.cache_manager import _embed as _ce
    return _ce(text)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_turn(
    user_id: str,
    question: str,
    answer: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    intent_tag: Optional[str] = None,
) -> None:
    """
    Persist a question/answer turn for this user and prune to MAX_TURNS_PER_USER.
    Called after a successful live-pipeline response to build up memory over time.
    """
    try:
        q_emb = _embed(question)
        emb_blob = q_emb.tobytes()
        ts = datetime.now(timezone.utc).isoformat()

        with _db_conn() as conn:
            conn.execute(
                """
                INSERT INTO user_memory
                    (user_id, session_id, turn_id, question, answer, intent_tag, question_embedding, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, session_id, turn_id, question, answer, intent_tag, emb_blob, ts),
            )
            # Prune: keep only the latest MAX_TURNS_PER_USER rows for this user
            conn.execute(
                """
                DELETE FROM user_memory
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM user_memory WHERE user_id = ?
                    ORDER BY id DESC LIMIT ?
                )
                """,
                (user_id, user_id, _MAX_TURNS_PER_USER),
            )
        logger.debug(f"[Memory] Saved turn for user={user_id} intent={intent_tag}")
    except Exception as e:
        logger.warning(f"[Memory] save_turn error (non-fatal): {e}")


def get_turns(user_id: str, n: int = _MAX_TURNS_PER_USER) -> List[Dict[str, Any]]:
    """Return the last N memory turns for a user (most recent first)."""
    try:
        with _db_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, turn_id, question, answer, intent_tag, timestamp
                FROM user_memory
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, n),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"[Memory] get_turns error: {e}")
        return []


def build_context_for_question(user_id: str, current_question: str) -> str:
    """
    Fetch all stored turns for this user, compute similarity with current_question,
    and return a formatted context string containing the top-5 similar prior turns.

    This context string is injected into the DSPy intent extraction system prompt
    to reduce ambiguity resolution token cost (model already 'knows' what the user
    typically queries for, so fewer back-and-forth clarification calls).
    """
    try:
        with _db_conn() as conn:
            rows = conn.execute(
                """
                SELECT question, answer, intent_tag, question_embedding
                FROM user_memory WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, _MAX_TURNS_PER_USER),
            ).fetchall()

        if not rows:
            return ""

        q_emb = _embed(current_question)
        scored: List[tuple] = []

        for row in rows:
            emb_blob = row["question_embedding"]
            if not emb_blob:
                continue
            stored_emb = np.frombuffer(emb_blob, dtype="float32")
            score = _cosine(q_emb, stored_emb)
            if score >= _CONTEXT_MIN_SIMILARITY:
                scored.append((score, row))

        if not scored:
            return ""

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:_CONTEXT_TOP_K]

        lines = ["### Prior conversation context (similar questions from this user):"]
        for rank, (score, row) in enumerate(top, 1):
            lines.append(
                f"{rank}. Q: {row['question']}\n"
                f"   Intent: {row['intent_tag'] or 'unknown'}\n"
                f"   A summary: {(row['answer'] or '')[:200]}"
            )
        lines.append("Use this context to better interpret the current question.")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[Memory] build_context_for_question error (non-fatal): {e}")
        return ""
