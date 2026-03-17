"""
RLHF SQLAlchemy ORM Models.

Three tables:
- FeedbackLog: stores per-response feedback (ratings, corrections, full context)
- PromptVersion: tracks versioned prompt files with parent lineage for rollback
- ABTestConfig: defines A/B test variants and traffic split
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean, DateTime, CheckConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class FeedbackLog(Base):
    __tablename__ = "feedback_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), nullable=False, index=True)
    query = Column(Text, nullable=False)
    response_summary = Column(Text, nullable=False)  # First 500 chars of refined insights
    full_response = Column(Text, nullable=True)       # Full refined insights JSON
    sql_query = Column(Text, nullable=True)            # Generated Cube query JSON
    prompt_version = Column(String(16), nullable=False, index=True)
    ab_group = Column(String(1), nullable=True)        # "A" or "B", null if no A/B test
    rating = Column(Integer, nullable=False)
    correction = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rating_range"),
    )


class PromptVersion(Base):
    __tablename__ = "prompt_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_tag = Column(String(16), nullable=False, unique=True)  # e.g. "v1", "v2"
    filename = Column(String(128), nullable=False)                  # e.g. "intent_extraction_v1.txt"
    few_shot_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=False, nullable=False)
    parent_version = Column(String(16), nullable=True)             # For rollback lineage
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class ABTestConfig(Base):
    __tablename__ = "ab_test_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_a = Column(String(16), nullable=False)
    version_b = Column(String(16), nullable=False)
    traffic_split = Column(Float, default=0.5)  # Fraction of traffic to version A
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class RetryLog(Base):
    __tablename__ = "retry_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_request_id = Column(String(64), nullable=False, index=True)
    retry_request_id = Column(String(64), nullable=False, index=True)
    original_query = Column(Text, nullable=False)
    modified_query = Column(Text, nullable=False)
    session_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
