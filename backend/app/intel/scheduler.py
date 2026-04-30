"""
Intel Scheduler — Main Orchestrator.

Runs every 6 hours (configurable via INTEL_SCHEDULER_INTERVAL_HOURS env var).
For each active client → each active user, executes Steps 1–6 and logs the
run in intel_run_log.

Hooked into FastAPI lifespan in main.py:
    from app.intel.scheduler import start_scheduler, stop_scheduler
    start_scheduler()   # in startup
    stop_scheduler()    # in shutdown

A manual trigger endpoint is exposed at POST /insights/intel/run (admin only).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.intel.db import get_conn, dict_cursor
from app.intel.steps.step1_profile import refresh_interest_profile
from app.intel.steps.step2_watches import sync_watch_configs
from app.intel.steps.step3_execute import execute_watches, load_active_watches
from app.intel.steps.step4_detect import detect_patterns, filter_signals_for_llm
from app.intel.steps.step5_narrate import generate_narratives
from app.intel.steps.step6_store import deduplicate_and_store

logger = logging.getLogger(__name__)

_INTERVAL_HOURS = int(os.getenv("INTEL_SCHEDULER_INTERVAL_HOURS", "6"))

_scheduler: AsyncIOScheduler | None = None


# =============================================================================
# Lifecycle
# =============================================================================

def start_scheduler() -> None:
    """Start the APScheduler. Call from FastAPI lifespan startup."""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.info("[intel] Scheduler already running")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_intel_scheduler,
        trigger=IntervalTrigger(hours=_INTERVAL_HOURS),
        id="intel_run",
        replace_existing=True,
        misfire_grace_time=60 * 30,   # allow 30-min misfire
    )
    _scheduler.start()
    logger.info(f"[intel] Scheduler started (interval={_INTERVAL_HOURS}h)")


def stop_scheduler() -> None:
    """Stop the APScheduler. Call from FastAPI lifespan shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[intel] Scheduler stopped")


# =============================================================================
# Main job — called by scheduler + manual trigger endpoint
# =============================================================================

async def run_intel_scheduler(triggered_by: str = "scheduler") -> dict[str, Any]:
    """
    Full intel pipeline run across all active clients and users.

    Returns a summary dict suitable for the manual trigger API response.
    """
    logger.info(f"[intel] Run started (triggered_by={triggered_by})")

    clients = _load_active_clients()
    total_users = 0
    total_insights = 0
    total_suppressed = 0
    errors: list[str] = []

    for client in clients:
        client_id = client["client_id"]
        schema_name = client["schema_name"]

        run_id = _log_run_start(client_id, triggered_by)
        users_done = 0
        client_insights = 0
        client_suppressed = 0

        try:
            users = _load_active_users(client_id)
            for user in users:
                try:
                    result = await _process_user(user, schema_name)
                    users_done += 1
                    client_insights += result["stored"]
                    client_suppressed += result["suppressed"]
                except Exception as e:
                    logger.error(
                        f"[intel] User processing failed: user_id={user.get('user_id')}, err={e}",
                        exc_info=True,
                    )
                    errors.append(f"user_id={user.get('user_id')}: {e}")

            _log_run_complete(
                run_id,
                status="completed",
                users_processed=users_done,
                insights_generated=client_insights,
                insights_suppressed=client_suppressed,
            )
        except Exception as e:
            logger.error(f"[intel] Client run failed: client_id={client_id}, err={e}", exc_info=True)
            _log_run_complete(run_id, status="failed", error_detail=str(e))
            errors.append(f"client_id={client_id}: {e}")

        total_users += users_done
        total_insights += client_insights
        total_suppressed += client_suppressed

    summary = {
        "triggered_by":        triggered_by,
        "clients_processed":   len(clients),
        "users_processed":     total_users,
        "insights_generated":  total_insights,
        "insights_suppressed": total_suppressed,
        "errors":              errors,
        "completed_at":        datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"[intel] Run complete: {summary}")
    return summary


# =============================================================================
# Per-user pipeline
# =============================================================================

async def _process_user(user: dict[str, Any], schema_name: str) -> dict[str, int]:
    user_id = user["user_id"]
    client_id = user["client_id"]
    logger.debug(f"[intel] Processing user_id={user_id}")

    # Step 1 — Refresh interest profile
    refresh_interest_profile(user)

    # Load refreshed profile
    profile = _load_profile(user_id)

    # Step 2 — Sync watch configs
    sync_watch_configs(user, profile)

    # Step 3 — Execute watches
    watches = load_active_watches(user_id)
    if not watches:
        return {"stored": 0, "suppressed": 0}

    watch_results = execute_watches(user, watches, schema_name)

    # Step 4 — Detect patterns
    all_signals: list[dict] = []
    for wr in watch_results:
        signals = detect_patterns(wr)
        all_signals.extend(signals)

    llm_signals = filter_signals_for_llm(all_signals)

    if not llm_signals:
        return {"stored": 0, "suppressed": len(all_signals)}

    # Step 5 — LLM narrative generation
    enriched = generate_narratives(llm_signals, user)

    # Step 6 — Deduplicate + store
    store_result = deduplicate_and_store(enriched, user, client_id)
    return store_result


# =============================================================================
# DB helpers
# =============================================================================

def _load_active_clients() -> list[dict[str, Any]]:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                "SELECT client_id, schema_name FROM app_meta.clients WHERE is_active = TRUE"
            )
            return [dict(r) for r in cur.fetchall()]


def _load_active_users(client_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                SELECT user_id, username, client_id, role, department,
                       sales_hierarchy_level, salesrep_code, so_code,
                       asm_code, zsm_code, nsm_code
                FROM app_meta.users
                WHERE client_id = %s AND is_active = TRUE
                """,
                (client_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def _load_profile(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                SELECT top_kpis, top_entities, top_dimensions, preferred_time_windows
                FROM app_meta.user_interest_profiles
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def _log_run_start(client_id: str, triggered_by: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_meta.intel_run_log
                  (client_id, triggered_by, run_status)
                VALUES (%s, %s, 'running')
                RETURNING run_id
                """,
                (client_id, triggered_by),
            )
            return cur.fetchone()[0]


def _log_run_complete(
    run_id: int,
    status: str,
    users_processed: int = 0,
    insights_generated: int = 0,
    insights_suppressed: int = 0,
    error_detail: str | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app_meta.intel_run_log SET
                    run_status          = %s,
                    users_processed     = %s,
                    insights_generated  = %s,
                    insights_suppressed = %s,
                    error_detail        = %s,
                    completed_at        = NOW()
                WHERE run_id = %s
                """,
                (
                    status,
                    users_processed,
                    insights_generated,
                    insights_suppressed,
                    error_detail,
                    run_id,
                ),
            )
