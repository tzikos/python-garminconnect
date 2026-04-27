"""SQLite engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from coach.config import db_path
from coach.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def engine() -> Engine:
    """Lazy-init the SQLite engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(f"sqlite:///{db_path()}", future=True)
    return _engine


def init_db() -> None:
    """Create all tables. Idempotent."""
    Base.metadata.create_all(engine())


@contextmanager
def session() -> Iterator[Session]:
    """Context-managed Session. Commits on exit, rolls back on exception."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
