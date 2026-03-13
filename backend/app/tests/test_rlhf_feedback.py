"""
Tests for RLHF feedback_service.py.

Uses in-memory SQLite via override_engine.
"""
import pytest
from sqlalchemy import create_engine

from app.rlhf.db import override_engine
from app.rlhf.models import Base
from app.rlhf import feedback_service


@pytest.fixture(autouse=True)
def in_memory_db():
    """Set up an in-memory SQLite database for each test."""
    engine = create_engine("sqlite:///:memory:")
    override_engine(engine)
    yield
    Base.metadata.drop_all(engine)


class TestLogFeedback:
    def test_log_feedback_creates_row(self):
        entry_id = feedback_service.log_feedback(
            request_id="req_001",
            query="Show total sales",
            response_summary="Total sales is 1M",
            prompt_version="v1",
            rating=4,
        )
        assert entry_id is not None
        assert entry_id > 0

    def test_log_feedback_with_full_response_and_sql(self):
        entry_id = feedback_service.log_feedback(
            request_id="req_002",
            query="Show sales by region",
            response_summary="Sales by region breakdown",
            prompt_version="v1",
            rating=5,
            full_response='{"executive_summary": "strong growth"}',
            sql_query='{"measures": ["Sales.total"]}',
            correction="The values should include lakhs",
        )
        assert entry_id > 0


class TestGetPreferencePairs:
    def test_finds_pairs_with_gap(self):
        # Same query, two different ratings
        feedback_service.log_feedback(
            request_id="req_a1", query="Show sales", response_summary="Great response",
            prompt_version="v1", rating=5,
        )
        feedback_service.log_feedback(
            request_id="req_a2", query="Show sales", response_summary="Bad response",
            prompt_version="v1", rating=2,
        )

        pairs = feedback_service.get_preference_pairs("v1", min_gap=2)
        assert len(pairs) == 1
        assert pairs[0]["query"] == "Show sales"
        assert pairs[0]["chosen"]["rating"] == 5
        assert pairs[0]["rejected"]["rating"] == 2

    def test_ignores_pairs_below_gap(self):
        feedback_service.log_feedback(
            request_id="req_b1", query="Show metrics", response_summary="Resp A",
            prompt_version="v1", rating=4,
        )
        feedback_service.log_feedback(
            request_id="req_b2", query="Show metrics", response_summary="Resp B",
            prompt_version="v1", rating=3,
        )

        pairs = feedback_service.get_preference_pairs("v1", min_gap=2)
        assert len(pairs) == 0

    def test_requires_at_least_two_entries(self):
        feedback_service.log_feedback(
            request_id="req_c1", query="Unique query", response_summary="Only one",
            prompt_version="v1", rating=5,
        )

        pairs = feedback_service.get_preference_pairs("v1", min_gap=2)
        assert len(pairs) == 0


class TestGetTopResponses:
    def test_returns_in_descending_rating_order(self):
        for i, rating in enumerate([3, 5, 4, 2, 5]):
            feedback_service.log_feedback(
                request_id=f"req_top_{i}", query=f"Query {i}",
                response_summary=f"Response {i}", prompt_version="v1", rating=rating,
            )

        top = feedback_service.get_top_responses("v1", top_n=3)
        assert len(top) == 3
        assert all(r["rating"] >= 4 for r in top)
        # First should be highest rated
        assert top[0]["rating"] >= top[1]["rating"]


class TestGetVersionStats:
    def test_computes_correct_avg(self):
        for rating in [3, 4, 5, 4, 4]:
            feedback_service.log_feedback(
                request_id=f"req_stat_{rating}", query="Test",
                response_summary="Test resp", prompt_version="v1", rating=rating,
            )

        stats = feedback_service.get_version_stats("v1")
        assert stats["count"] == 5
        assert stats["avg_rating"] == 4.0
        assert stats["distribution"][4] == 3
        assert stats["distribution"][5] == 1

    def test_empty_version(self):
        stats = feedback_service.get_version_stats("v99")
        assert stats["count"] == 0
        assert stats["avg_rating"] == 0.0


class TestCompareVersions:
    def test_compare(self):
        feedback_service.log_feedback(
            request_id="req_cmp_1", query="Q", response_summary="R",
            prompt_version="v1", rating=3,
        )
        feedback_service.log_feedback(
            request_id="req_cmp_2", query="Q", response_summary="R",
            prompt_version="v2", rating=5,
        )

        result = feedback_service.compare_versions("v1", "v2")
        assert result["improvement"] == 2.0
        assert result["winner"] == "v2"
