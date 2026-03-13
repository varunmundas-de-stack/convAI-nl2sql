"""
RLHF Refinement Scheduler.

Runs the full refinement cycle with guardrails:
- Extract preference pairs
- Refine prompt via Claude
- Inject few-shots
- Save new version

Returns structured results with explicit skip-reason logging.
"""

import logging
from typing import Optional

from app.rlhf.feedback_service import get_version_stats, get_preference_pairs
from app.rlhf.refiner import run_refinement, apply_refinement, promote_version

logger = logging.getLogger(__name__)

# Configurable guardrails
MIN_RATINGS = 50
MIN_IMPROVEMENT_THRESHOLD = 0.3


def run_refinement_cycle(
    baseline_version: str,
    min_ratings: int = MIN_RATINGS,
    min_improvement: float = MIN_IMPROVEMENT_THRESHOLD,
) -> dict:
    """
    Full refinement cycle with guardrails.

    Returns a dict with:
    - status: "refined", "skipped", or "error"
    - reason: human-readable explanation
    - details: additional context
    """
    try:
        # Guardrail 1: minimum sample size
        stats = get_version_stats(baseline_version)
        if stats["count"] < min_ratings:
            reason = (
                f"Cycle skipped: only {stats['count']}/{min_ratings} ratings "
                f"collected for {baseline_version}"
            )
            logger.warning(reason)
            return {
                "status": "skipped",
                "reason": reason,
                "details": {"current_count": stats["count"], "required": min_ratings},
            }

        # Guardrail 2: check for preference pairs
        pairs = get_preference_pairs(baseline_version, min_gap=2)
        if not pairs:
            reason = (
                f"Cycle skipped: no preference pairs with sufficient rating gap "
                f"found for {baseline_version}"
            )
            logger.warning(reason)
            return {
                "status": "skipped",
                "reason": reason,
                "details": {"pairs_found": 0, "min_gap": 2},
            }

        # Run refinement
        refinement_result = run_refinement(baseline_version)
        if refinement_result.get("status") != "success":
            reason = f"Refinement failed: {refinement_result.get('reason', 'unknown')}"
            logger.warning(reason)
            return {
                "status": "error",
                "reason": reason,
                "details": refinement_result,
            }

        # Apply refinement — creates new version file
        new_version = apply_refinement(refinement_result, baseline_version)
        logger.info(
            f"Refinement cycle complete: {baseline_version} → {new_version} "
            f"(based on {len(pairs)} preference pairs, {stats['count']} ratings)"
        )

        return {
            "status": "refined",
            "reason": f"New version {new_version} created from {baseline_version}",
            "details": {
                "new_version": new_version,
                "baseline_version": baseline_version,
                "pairs_used": len(pairs),
                "baseline_avg_rating": stats["avg_rating"],
                "baseline_count": stats["count"],
            },
        }

    except Exception as e:
        reason = f"Refinement cycle error: {e}"
        logger.error(reason, exc_info=True)
        return {
            "status": "error",
            "reason": reason,
            "details": {"exception": str(e)},
        }
