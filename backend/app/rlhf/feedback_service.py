"""
RLHF Feedback Service.

Core logic for logging feedback, extracting preference pairs,
finding top responses, and computing version stats.
"""

import json
import logging
from typing import Optional
from collections import defaultdict

from sqlalchemy import func

from app.rlhf.db import get_session
from app.rlhf.models import FeedbackLog

logger = logging.getLogger(__name__)


def log_feedback(
    request_id: str,
    query: str,
    response_summary: str,
    prompt_version: str,
    rating: int,
    ab_group: Optional[str] = None,
    correction: Optional[str] = None,
    full_response: Optional[str] = None,
    sql_query: Optional[str] = None,
) -> int:
    """
    Write one feedback row to FeedbackLog.

    Returns the ID of the inserted row.
    """
    with get_session() as session:
        entry = FeedbackLog(
            request_id=request_id,
            query=query,
            response_summary=response_summary,
            full_response=full_response,
            sql_query=sql_query,
            prompt_version=prompt_version,
            ab_group=ab_group,
            rating=rating,
            correction=correction,
        )
        session.add(entry)
        session.flush()
        entry_id = entry.id
        logger.info(f"Feedback logged: request_id={request_id}, rating={rating}, version={prompt_version}")
        return entry_id


def get_preference_pairs(
    version: str,
    min_gap: int = 2,
) -> list[dict]:
    """
    Group feedback by query, return (query, chosen, rejected) triples
    where the rating gap >= min_gap.

    Uses full_response + sql_query for richer context when available.
    """
    with get_session() as session:
        logs = (
            session.query(FeedbackLog)
            .filter(FeedbackLog.prompt_version == version)
            .order_by(FeedbackLog.query, FeedbackLog.rating.desc())
            .all()
        )

    # Group by query text
    groups = defaultdict(list)
    for log in logs:
        groups[log.query].append(log)

    pairs = []
    for query_text, entries in groups.items():
        if len(entries) < 2:
            continue

        # Sort descending by rating
        entries.sort(key=lambda e: e.rating, reverse=True)
        best = entries[0]
        worst = entries[-1]

        if best.rating - worst.rating >= min_gap:
            pairs.append({
                "query": query_text,
                "chosen": {
                    "response_summary": best.response_summary,
                    "full_response": best.full_response,
                    "sql_query": best.sql_query,
                    "rating": best.rating,
                    "correction": best.correction,
                },
                "rejected": {
                    "response_summary": worst.response_summary,
                    "full_response": worst.full_response,
                    "sql_query": worst.sql_query,
                    "rating": worst.rating,
                    "correction": worst.correction,
                },
            })

    logger.info(f"Found {len(pairs)} preference pairs for version {version} (min_gap={min_gap})")
    return pairs


def get_top_responses(version: str, top_n: int = 5) -> list[dict]:
    """Return the N highest-rated responses for few-shot injection."""
    with get_session() as session:
        logs = (
            session.query(FeedbackLog)
            .filter(FeedbackLog.prompt_version == version)
            .filter(FeedbackLog.rating >= 4)  # Only use well-rated responses
            .order_by(FeedbackLog.rating.desc(), FeedbackLog.created_at.desc())
            .limit(top_n)
            .all()
        )

    return [
        {
            "query": log.query,
            "response": log.correction or log.response_summary,
            "rating": log.rating,
        }
        for log in logs
    ]


def get_version_stats(version: str) -> dict:
    """Compute average rating, count, and distribution for a prompt version."""
    with get_session() as session:
        logs = (
            session.query(FeedbackLog)
            .filter(FeedbackLog.prompt_version == version)
            .all()
        )

    if not logs:
        return {
            "version": version,
            "count": 0,
            "avg_rating": 0.0,
            "distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        }

    ratings = [log.rating for log in logs]
    distribution = {i: ratings.count(i) for i in range(1, 6)}

    return {
        "version": version,
        "count": len(ratings),
        "avg_rating": round(sum(ratings) / len(ratings), 3),
        "distribution": distribution,
    }


def compare_versions(version_a: str, version_b: str) -> dict:
    """Side-by-side stats for two versions."""
    stats_a = get_version_stats(version_a)
    stats_b = get_version_stats(version_b)

    improvement = stats_b["avg_rating"] - stats_a["avg_rating"]

    return {
        "version_a": stats_a,
        "version_b": stats_b,
        "improvement": round(improvement, 3),
        "winner": version_b if improvement > 0 else version_a if improvement < 0 else "tie",
    }
