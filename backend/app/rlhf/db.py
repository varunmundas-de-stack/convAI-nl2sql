"""
RLHF Database session management.

- init_db(): creates all tables in backend/rlhf.db (called at app startup)
- get_session(): context-managed SQLAlchemy session factory
"""

import logging
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.rlhf.models import Base

logger = logging.getLogger(__name__)

# Database lives alongside the backend directory
DB_PATH = Path(__file__).parent.parent.parent / "rlhf.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

_engine = None
_SessionFactory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False)
    return _engine


def init_db():
    """Create all RLHF tables. Safe to call multiple times."""
    engine = _get_engine()
    Base.metadata.create_all(engine)
    logger.info(f"RLHF database initialized at {DB_PATH}")


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=_get_engine(), expire_on_commit=False)
    return _SessionFactory


@contextmanager
def get_session():
    """Context-managed database session. Auto-commits on success, rolls back on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def override_engine(engine):
    """Override the engine (for testing with in-memory SQLite)."""
    global _engine, _SessionFactory
    _engine = engine
    _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
