"""
A/B Router.

Deterministic, per-session assignment to A/B groups.
Group is derived from session_id hash — same session always gets the same group.
"""

import hashlib
import logging
from typing import Optional

from app.rlhf.db import get_session
from app.rlhf.models import ABTestConfig

logger = logging.getLogger(__name__)


def assign_ab_group(session_id: str) -> str:
    """
    Assign A/B group based on session_id hash (per-session, deterministic).

    Returns "A" or "B".
    """
    hash_int = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
    group = "A" if hash_int % 2 == 0 else "B"
    return group


def get_prompt_version_for_group(group: str) -> str:
    """Map A/B group to prompt version tag using active ABTestConfig."""
    with get_session() as session:
        config = session.query(ABTestConfig).filter_by(is_active=True).first()

    if not config:
        from app.rlhf.prompt_manager import get_active_version_tag
        return get_active_version_tag()

    return config.version_a if group == "A" else config.version_b


def get_ab_status() -> Optional[dict]:
    """Get current A/B test status. Returns None if no active test."""
    with get_session() as session:
        config = session.query(ABTestConfig).filter_by(is_active=True).first()
        if not config:
            return None
        return {
            "version_a": config.version_a,
            "version_b": config.version_b,
            "traffic_split": config.traffic_split,
            "is_active": config.is_active,
            "created_at": config.created_at.isoformat() if config.created_at else None,
        }


def create_ab_test(version_a: str, version_b: str, traffic_split: float = 0.5) -> dict:
    """Create a new A/B test, deactivating any existing one."""
    with get_session() as session:
        # Deactivate existing tests
        session.query(ABTestConfig).filter_by(is_active=True).update({"is_active": False})

        config = ABTestConfig(
            version_a=version_a,
            version_b=version_b,
            traffic_split=traffic_split,
            is_active=True,
        )
        session.add(config)
        logger.info(f"A/B test created: {version_a} vs {version_b} (split={traffic_split})")

    return {
        "version_a": version_a,
        "version_b": version_b,
        "traffic_split": traffic_split,
        "is_active": True,
    }


def stop_ab_test() -> bool:
    """Deactivate the current A/B test. Returns True if a test was stopped."""
    with get_session() as session:
        count = session.query(ABTestConfig).filter_by(is_active=True).update({"is_active": False})
        if count > 0:
            logger.info("A/B test stopped")
        return count > 0
