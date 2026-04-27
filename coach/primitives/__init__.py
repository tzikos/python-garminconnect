"""Workout primitive registry.

A primitive maps a (type_key, params_dict) pair to a garminconnect typed
workout. The DB stores type_key + params; sync time looks up the function
here and materializes the workout for upload.

Adding a new primitive: write the function, register it below.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from coach.primitives.running import (
    easy_run,
    interval_session,
    long_run,
    tempo_run,
)
from coach.primitives.strength import strength_session

PRIMITIVES: dict[str, Callable[..., Any]] = {
    "easy_run": easy_run,
    "long_run": long_run,
    "tempo_run": tempo_run,
    "interval_session": interval_session,
    "strength_session": strength_session,
}


def build(primitive_type: str, params: dict[str, Any]) -> Any:
    """Look up and invoke a registered primitive."""
    if primitive_type not in PRIMITIVES:
        raise KeyError(
            f"Unknown primitive {primitive_type!r}. "
            f"Registered: {sorted(PRIMITIVES)}"
        )
    return PRIMITIVES[primitive_type](**params)


__all__ = [
    "PRIMITIVES",
    "build",
    "easy_run",
    "long_run",
    "tempo_run",
    "interval_session",
    "strength_session",
]
