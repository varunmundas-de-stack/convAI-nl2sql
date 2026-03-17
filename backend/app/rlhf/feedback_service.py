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
from app.rlhf.models import FeedbackLog, RetryLog

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


def log_retry(
    original_request_id: str,
    retry_request_id: str,
    original_query: str,
    modified_query: str,
    session_id: str,
) -> int:
    """
    Log a retry attempt linking the original request to the new retry request.

    Returns the ID of the inserted retry log entry.
    """
    with get_session() as session:
        entry = RetryLog(
            original_request_id=original_request_id,
            retry_request_id=retry_request_id,
            original_query=original_query,
            modified_query=modified_query,
            session_id=session_id,
        )
        session.add(entry)
        session.flush()
        entry_id = entry.id
        logger.info(f"Retry logged: original_id={original_request_id}, retry_id={retry_request_id}")
        return entry_id


def get_retry_statistics(version: Optional[str] = None) -> dict:
    """
    Get statistics about retry patterns for analysis.

    Args:
        version: Optional prompt version to filter by (looks up via FeedbackLog)

    Returns:
        Dictionary with retry statistics
    """
    with get_session() as session:
        query = session.query(RetryLog)

        if version:
            # Filter by prompt version via FeedbackLog
            query = query.join(
                FeedbackLog,
                RetryLog.original_request_id == FeedbackLog.request_id
            ).filter(FeedbackLog.prompt_version == version)

        retry_logs = query.all()

        if not retry_logs:
            return {
                "total_retries": 0,
                "unique_sessions": 0,
                "avg_query_length_change": 0.0,
                "common_modifications": [],
            }

        total_retries = len(retry_logs)
        unique_sessions = len(set(log.session_id for log in retry_logs))

        # Calculate average query length change
        length_changes = []
        for log in retry_logs:
            original_len = len(log.original_query.strip())
            modified_len = len(log.modified_query.strip())
            length_changes.append(modified_len - original_len)

        avg_length_change = sum(length_changes) / len(length_changes) if length_changes else 0

        return {
            "total_retries": total_retries,
            "unique_sessions": unique_sessions,
            "avg_query_length_change": round(avg_length_change, 2),
            "retry_rate": round(unique_sessions / total_retries if total_retries > 0 else 0, 3),
        }
