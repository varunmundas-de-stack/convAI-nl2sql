"""
Integration tests for RLHF endpoints using FastAPI TestClient.
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.rlhf.db import override_engine
from app.rlhf.models import Base, PromptVersion
from app.rlhf.db import get_session


@pytest.fixture(autouse=True)
def in_memory_db():
    """Override engine BEFORE any test runs."""
    engine = create_engine("sqlite:///:memory:")
    override_engine(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(in_memory_db):
    """
    Create TestClient after engine override.
    The lifespan's init_db() + ensure_v1_registered() will run on the in-memory engine.
    """
    from app.main import app
    with TestClient(app) as c:
        yield c


class TestFeedbackEndpoint:
    def test_submit_valid_feedback(self, client):
        resp = client.post("/rlhf/feedback", json={
            "request_id": "req_test_001",
            "query": "Show total sales",
            "response_summary": "Total sales is 10L",
            "prompt_version": "v1",
            "rating": 4,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "feedback_id" in data

    def test_submit_feedback_with_all_fields(self, client):
        resp = client.post("/rlhf/feedback", json={
            "request_id": "req_test_002",
            "query": "Show metrics",
            "response_summary": "Metrics summary",
            "prompt_version": "v1",
            "rating": 5,
            "ab_group": "A",
            "correction": "Should include percentages",
            "full_response": '{"executive_summary": "test"}',
            "sql_query": '{"measures": ["Sales.total"]}',
        })
        assert resp.status_code == 200

    def test_submit_feedback_invalid_rating(self, client):
        resp = client.post("/rlhf/feedback", json={
            "request_id": "req_test_003",
            "query": "Test",
            "response_summary": "Test",
            "prompt_version": "v1",
            "rating": 6,  # Out of range
        })
        assert resp.status_code == 422

    def test_submit_feedback_missing_fields(self, client):
        resp = client.post("/rlhf/feedback", json={
            "request_id": "req_test_004",
            # Missing required fields
        })
        assert resp.status_code == 422


class TestPromptVersionsEndpoint:
    def test_list_versions(self, client):
        resp = client.get("/rlhf/prompt-versions")
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert len(data["versions"]) >= 1
        v1 = next(v for v in data["versions"] if v["version_tag"] == "v1")
        assert v1["is_active"] is True


class TestPreferencePairsEndpoint:
    def test_get_preference_pairs(self, client):
        resp = client.get("/rlhf/preference-pairs?version=v1")
        assert resp.status_code == 200
        data = resp.json()
        assert "pairs" in data
        assert isinstance(data["pairs"], list)


class TestABStatusEndpoint:
    def test_no_active_test(self, client):
        resp = client.get("/rlhf/ab-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    def test_with_active_test(self, client):
        # Create a test
        client.post("/rlhf/ab-test", json={
            "version_a": "v1",
            "version_b": "v1",
            "traffic_split": 0.5,
        })
        resp = client.get("/rlhf/ab-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True


class TestRollbackEndpoint:
    def test_rollback_no_parent(self, client):
        resp = client.post("/rlhf/rollback?version=v1")
        assert resp.status_code == 400

    def test_rollback_nonexistent(self, client):
        resp = client.post("/rlhf/rollback?version=v99")
        assert resp.status_code == 400


class TestPromoteEndpoint:
    def test_promote_existing(self, client):
        resp = client.post("/rlhf/promote?version=v1")
        assert resp.status_code == 200
        assert resp.json()["promoted"] == "v1"

    def test_promote_nonexistent(self, client):
        resp = client.post("/rlhf/promote?version=v99")
        assert resp.status_code == 404


class TestCompareEndpoint:
    def test_compare_versions(self, client):
        # Submit feedback for both versions
        client.post("/rlhf/feedback", json={
            "request_id": "cmp1", "query": "Q", "response_summary": "R",
            "prompt_version": "v1", "rating": 3,
        })

        resp = client.get("/rlhf/compare?version_a=v1&version_b=v2")
        assert resp.status_code == 200
        data = resp.json()
        assert "version_a" in data
        assert "version_b" in data
        assert "winner" in data
