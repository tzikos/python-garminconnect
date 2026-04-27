"""Filesystem paths and config for the coach app."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "garmin-coach"


def app_dir() -> Path:
    """Return the per-user data dir, creating it if missing."""
    override = os.environ.get("GARMIN_COACH_HOME")
    base = Path(override) if override else Path.home() / f".{APP_NAME}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    """Return path to the SQLite DB file."""
    return app_dir() / "coach.db"
