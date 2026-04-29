"""SQLite engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
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


_LIGHTWEIGHT_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, "ADD COLUMN ... DEFAULT ...")
    ("user_profile", "enabled_sports", "ADD COLUMN enabled_sports JSON DEFAULT '[]'"),
    ("user_profile", "sport_profiles", "ADD COLUMN sport_profiles JSON DEFAULT '{}'"),
]


def _apply_migrations(eng: Engine) -> None:
    """Add missing columns to existing tables.

    SQLAlchemy's `create_all()` only creates new tables, never alters
    existing ones. For local-dev SQLite we run a small set of additive
    `ALTER TABLE ADD COLUMN` statements ourselves. Idempotent.
    """
    inspector = inspect(eng)
    for table, column, statement in _LIGHTWEIGHT_MIGRATIONS:
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column in existing:
            continue
        with eng.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} {statement}"))


def init_db() -> None:
    """Create all tables + run lightweight migrations. Idempotent."""
    Base.metadata.create_all(engine())
    _apply_migrations(engine())


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
