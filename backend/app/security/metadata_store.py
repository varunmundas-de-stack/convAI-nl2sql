import json
import os
import uuid
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras

from app.security.context import UserContext


def _dsn() -> dict:
    return {
        "host": os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "localhost")),
        "port": int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
        "dbname": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "sales_analytics")),
        "user": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres")),
        "password": os.getenv("DB_PASS", os.getenv("POSTGRES_PASSWORD", "postgres")),
    }


@contextmanager
def get_conn():
    conn = psycopg2.connect(**_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _pick_hierarchy_code(row: dict[str, Any]) -> str | None:
    role = (row.get("role") or "").upper()
    if role == "SO":
        return row.get("salesrep_code") or row.get("so_code")
    if role == "ASM":
        return row.get("asm_code")
    if role == "ZSM":
        return row.get("zsm_code")
    if role == "NSM":
        return row.get("nsm_code")
    return None


def _row_to_user(row: dict[str, Any]) -> UserContext:
    return UserContext(
        user_id=row["user_id"],
        username=row["username"],
        email=row["email"],
        full_name=row["full_name"],
        client_id=row["client_id"],
        client_name=row["client_name"],
        schema_name=row["schema_name"],
        role=row["role"],
        department=row["department"],
        hierarchy_code=_pick_hierarchy_code(row),
        salesrep_code=row.get("salesrep_code"),
        so_code=row.get("so_code"),
        asm_code=row.get("asm_code"),
        zsm_code=row.get("zsm_code"),
        nsm_code=row.get("nsm_code"),
    )


def get_user_by_username(username: str) -> tuple[UserContext, str] | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.*, c.client_name, c.schema_name
                FROM app_meta.users u
                JOIN app_meta.clients c ON c.client_id = u.client_id
                WHERE u.username = %s AND u.is_active = TRUE AND c.is_active = TRUE
                """,
                (username,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_user(row), row["password_hash"]


def get_user_by_id(user_id: int) -> UserContext | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.*, c.client_name, c.schema_name
                FROM app_meta.users u
                JOIN app_meta.clients c ON c.client_id = u.client_id
                WHERE u.user_id = %s AND u.is_active = TRUE AND c.is_active = TRUE
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return _row_to_user(row) if row else None


def update_last_login(user_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_meta.users SET last_login = CURRENT_TIMESTAMP WHERE user_id = %s", (user_id,))


def ensure_chat_session(session_id: str, user: UserContext, title: str | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_meta.chat_sessions (session_id, user_id, client_id, title)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP
                """,
                (session_id, user.user_id, user.client_id, (title or "New conversation")[:200]),
            )


def save_chat_message(
    session_id: str,
    user: UserContext,
    role: str,
    content: str,
    raw_data: dict[str, Any] | list[Any] | None = None,
    query_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    ensure_chat_session(session_id, user, content if role == "user" else None)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_meta.chat_messages
                  (message_id, session_id, user_id, role, content, raw_data, query_type, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    uuid.uuid4().hex,
                    session_id,
                    user.user_id,
                    role,
                    content,
                    json.dumps(raw_data) if raw_data is not None else None,
                    query_type,
                    json.dumps(metadata or {}),
                ),
            )
            cur.execute(
                "UPDATE app_meta.chat_sessions SET last_active = CURRENT_TIMESTAMP WHERE session_id = %s",
                (session_id,),
            )


def log_audit(
    user: UserContext,
    question: str,
    cube_query: dict[str, Any] | None,
    success: bool,
    error_message: str | None,
    duration_ms: int | None,
    cache_hit: bool = False,
    cache_tier: str | None = None,
    tokens_used: int | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_meta.audit_log
                  (user_id, username, client_id, question, cube_query, success,
                   error_message, duration_ms, cache_hit, cache_tier, tokens_used)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user.user_id,
                    user.username,
                    user.client_id,
                    question,
                    json.dumps(cube_query) if cube_query is not None else None,
                    success,
                    error_message,
                    duration_ms,
                    cache_hit,
                    cache_tier,
                    tokens_used,
                ),
            )


def list_sessions(user: UserContext) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT session_id, title, created_at, last_active
                FROM app_meta.chat_sessions
                WHERE user_id = %s AND is_active = TRUE
                ORDER BY last_active DESC
                """,
                (user.user_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def list_messages(user: UserContext, session_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.message_id, m.role, m.content, m.raw_data, m.query_type, m.metadata, m.created_at
                FROM app_meta.chat_messages m
                JOIN app_meta.chat_sessions s ON s.session_id = m.session_id
                WHERE m.session_id = %s AND s.user_id = %s AND s.is_active = TRUE
                ORDER BY m.created_at ASC
                """,
                (session_id, user.user_id),
            )
            return [dict(r) for r in cur.fetchall()]


def update_session(user: UserContext, session_id: str, title: str | None, is_active: bool | None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if title is not None:
                cur.execute(
                    "UPDATE app_meta.chat_sessions SET title = %s WHERE session_id = %s AND user_id = %s",
                    (title[:200], session_id, user.user_id),
                )
            if is_active is not None:
                cur.execute(
                    "UPDATE app_meta.chat_sessions SET is_active = %s WHERE session_id = %s AND user_id = %s",
                    (is_active, session_id, user.user_id),
                )


def list_insights(user: UserContext, limit: int = 20) -> list[dict[str, Any]]:
    role = (user.role or "").upper()
    params: list[Any] = [user.client_id, user.user_id]
    scope = ["i.hierarchy_level IN ('all', 'NSM', 'ZSM', 'ASM', 'SO')"]
    if role == "SO" and user.salesrep_code:
        scope.append("(i.salesrep_code IS NULL OR i.salesrep_code = %s)")
        params.append(user.salesrep_code)
    if role in ("SO", "ASM") and user.asm_code:
        scope.append("(i.asm_code IS NULL OR i.asm_code = %s)")
        params.append(user.asm_code)
    if role in ("SO", "ASM", "ZSM") and user.zsm_code:
        scope.append("(i.zsm_code IS NULL OR i.zsm_code = %s)")
        params.append(user.zsm_code)
    params.append(limit)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT i.*,
                       CASE WHEN r.insight_id IS NULL THEN FALSE ELSE TRUE END AS is_read
                FROM app_meta.insights i
                LEFT JOIN app_meta.insight_reads r
                  ON r.insight_id = i.insight_id AND r.user_id = %s
                WHERE i.tenant_id = %s
                  AND i.is_active = TRUE
                  AND (i.expires_at IS NULL OR i.expires_at > CURRENT_TIMESTAMP)
                  AND {' AND '.join(scope)}
                ORDER BY CASE i.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                         i.created_at DESC
                LIMIT %s
                """,
                [params[1], params[0], *params[2:]],
            )
            return [dict(r) for r in cur.fetchall()]


def mark_insight_read(user: UserContext, insight_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_meta.insight_reads (insight_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (insight_id, user.user_id),
            )
