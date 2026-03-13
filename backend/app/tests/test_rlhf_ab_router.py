"""
Tests for RLHF ab_router.py.
"""
import pytest
from sqlalchemy import create_engine

from app.rlhf.db import override_engine
from app.rlhf.models import Base, ABTestConfig
from app.rlhf.ab_router import assign_ab_group, get_prompt_version_for_group, create_ab_test, stop_ab_test


@pytest.fixture(autouse=True)
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    override_engine(engine)
    yield
    Base.metadata.drop_all(engine)


class TestAssignABGroup:
    def test_deterministic_same_session(self):
        """Same session_id always returns the same group."""
        group1 = assign_ab_group("sess_abc123")
        group2 = assign_ab_group("sess_abc123")
        group3 = assign_ab_group("sess_abc123")
        assert group1 == group2 == group3

    def test_returns_a_or_b(self):
        group = assign_ab_group("sess_test123")
        assert group in ("A", "B")

    def test_roughly_balanced_split(self):
        """1000 random session IDs should produce approximately 50/50 split."""
        groups = [assign_ab_group(f"sess_{i}") for i in range(1000)]
        count_a = groups.count("A")
        count_b = groups.count("B")
        # Allow ±10% tolerance
        assert 400 <= count_a <= 600, f"Group A count {count_a} is outside 400-600 range"
        assert 400 <= count_b <= 600, f"Group B count {count_b} is outside 400-600 range"

    def test_different_sessions_can_differ(self):
        """Different session IDs can map to different groups."""
        groups = set(assign_ab_group(f"sess_{i}") for i in range(100))
        assert len(groups) == 2  # Both A and B should appear


class TestGetPromptVersionForGroup:
    def test_returns_configured_version(self):
        create_ab_test("v1", "v2")
        assert get_prompt_version_for_group("A") == "v1"
        assert get_prompt_version_for_group("B") == "v2"


class TestCreateAndStopABTest:
    def test_create_test(self):
        result = create_ab_test("v1", "v2", traffic_split=0.5)
        assert result["version_a"] == "v1"
        assert result["version_b"] == "v2"
        assert result["is_active"] is True

    def test_create_deactivates_previous(self):
        create_ab_test("v1", "v2")
        create_ab_test("v2", "v3")
        # New test should be active
        assert get_prompt_version_for_group("A") == "v2"
        assert get_prompt_version_for_group("B") == "v3"

    def test_stop_test(self):
        create_ab_test("v1", "v2")
        stopped = stop_ab_test()
        assert stopped is True

    def test_stop_when_no_test(self):
        stopped = stop_ab_test()
        assert stopped is False
