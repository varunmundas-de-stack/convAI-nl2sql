"""
Tests for RLHF refiner.py (with mocked Claude calls).
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine

from app.rlhf.db import override_engine
from app.rlhf.models import Base, PromptVersion
from app.rlhf.refiner import build_meta_prompt, apply_refinement, rollback_version, promote_version
from app.rlhf.db import get_session


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    override_engine(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def seed_v1():
    """Register v1 in the database."""
    with get_session() as session:
        session.add(PromptVersion(
            version_tag="v1",
            filename="intent_extraction_v1.txt",
            is_active=True,
        ))


class TestBuildMetaPrompt:
    def test_includes_all_preference_pairs(self):
        pairs = [
            {
                "query": "Show total sales",
                "chosen": {
                    "response_summary": "Total sales: ₹10L",
                    "full_response": '{"executive_summary": "strong"}',
                    "sql_query": '{"measures": ["Sales.total"]}',
                    "rating": 5,
                    "correction": None,
                },
                "rejected": {
                    "response_summary": "Sales data",
                    "full_response": None,
                    "sql_query": None,
                    "rating": 2,
                    "correction": "Too vague",
                },
            },
            {
                "query": "Sales by region",
                "chosen": {
                    "response_summary": "Regional breakdown shows...",
                    "full_response": None,
                    "sql_query": None,
                    "rating": 4,
                    "correction": None,
                },
                "rejected": {
                    "response_summary": "Error occurred",
                    "full_response": None,
                    "sql_query": None,
                    "rating": 1,
                    "correction": None,
                },
            },
        ]

        prompt = build_meta_prompt(pairs, "You are an intent extractor...")
        assert "Pair 1" in prompt
        assert "Pair 2" in prompt
        assert "Show total sales" in prompt
        assert "Sales by region" in prompt
        assert "CHOSEN" in prompt
        assert "REJECTED" in prompt
        assert "Too vague" in prompt  # Human correction included

    def test_includes_full_response_and_sql(self):
        pairs = [{
            "query": "Test query",
            "chosen": {
                "response_summary": "Summary",
                "full_response": '{"key": "value"}',
                "sql_query": '{"measures": ["M"]}',
                "rating": 5,
                "correction": None,
            },
            "rejected": {
                "response_summary": "Bad",
                "full_response": None,
                "sql_query": None,
                "rating": 1,
                "correction": None,
            },
        }]

        prompt = build_meta_prompt(pairs, "System prompt")
        assert "Full Response" in prompt
        assert "SQL Query" in prompt


class TestApplyRefinement:
    def test_creates_new_version_file(self, seed_v1, tmp_path):
        from app.rlhf import prompt_manager
        # Temporarily redirect PROMPTS_DIR
        original_dir = prompt_manager.PROMPTS_DIR
        prompt_manager.PROMPTS_DIR = tmp_path

        refinement = {"new_prompt": "Improved system prompt text here."}

        with patch("app.rlhf.refiner.get_top_responses", return_value=[]):
            with patch("app.rlhf.refiner.PROMPTS_DIR", tmp_path):
                new_tag = apply_refinement(refinement, "v1")

        assert new_tag == "v2"
        # Check file was created
        new_file = tmp_path / "intent_extraction_v2.txt"
        assert new_file.exists()
        assert "Improved system prompt" in new_file.read_text()

        # Check DB registration
        with get_session() as session:
            v2 = session.query(PromptVersion).filter_by(version_tag="v2").first()
            assert v2 is not None
            assert v2.parent_version == "v1"
            assert v2.is_active is False  # Not active until promoted

        prompt_manager.PROMPTS_DIR = original_dir


class TestRollbackVersion:
    def test_rollback_to_parent(self, seed_v1):
        # Create v2 with v1 as parent
        with get_session() as session:
            session.add(PromptVersion(
                version_tag="v2",
                filename="intent_extraction_v2.txt",
                is_active=True,
                parent_version="v1",
            ))
            # Deactivate v1
            v1 = session.query(PromptVersion).filter_by(version_tag="v1").first()
            v1.is_active = False

        parent = rollback_version("v2")
        assert parent == "v1"

        # Check v1 is active again
        with get_session() as session:
            v1 = session.query(PromptVersion).filter_by(version_tag="v1").first()
            assert v1.is_active is True

    def test_rollback_no_parent_raises(self, seed_v1):
        with pytest.raises(ValueError, match="no parent"):
            rollback_version("v1")

    def test_rollback_nonexistent_version_raises(self):
        with pytest.raises(ValueError, match="not found"):
            rollback_version("v99")


class TestPromoteVersion:
    def test_promote(self, seed_v1):
        with get_session() as session:
            session.add(PromptVersion(
                version_tag="v2",
                filename="intent_extraction_v2.txt",
                is_active=False,
                parent_version="v1",
            ))

        promote_version("v2")

        with get_session() as session:
            v1 = session.query(PromptVersion).filter_by(version_tag="v1").first()
            v2 = session.query(PromptVersion).filter_by(version_tag="v2").first()
            assert v1.is_active is False
            assert v2.is_active is True

    def test_promote_nonexistent_raises(self):
        with pytest.raises(ValueError, match="not found"):
            promote_version("v99")
