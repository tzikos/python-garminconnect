"""Strength workout primitive.

Garmin's structured-workout format for strength is limited (no real
progressive overload tracking, no per-exercise sets/reps logged on most
watches). Strategy: model the session richly in the description string so
the watch displays the actual prescription, while the structured part is
a single timer covering the whole session.

The exercises list is the source of truth. The DB stores it inside
ScheduledWorkout.primitive_params, so manual editing of the JSON works.

Schema for an exercise dict:
    {
        "name":     str,    required
        "sets":     int,    required
        "reps":     str | int,    required ("8", "8-10", "AMRAP", ...)
        "weight":   str | None,   optional ("60kg", "BW", "RPE 8")
        "rest":     str | None,   optional ("90s", "2min")
        "notes":    str | None,   optional ("paused", "tempo 3-1-1", ...)
    }
"""

from __future__ import annotations

from typing import Any

from garminconnect.workout import (
    BaseWorkout,
    WorkoutSegment,
    create_interval_step,
)

# Strength training as its own sport — Garmin returns sportTypeId=5 with
# sportTypeKey="strength_training" for these workouts. If the watch shows
# them under the wrong activity profile we'll revisit.
_STRENGTH_SPORT = {
    "sportTypeId": 5,
    "sportTypeKey": "strength_training",
    "displayOrder": 5,
}


def _format_exercises(exercises: list[dict[str, Any]]) -> str:
    """Render exercises as a compact, watch-readable block."""
    lines: list[str] = []
    for i, ex in enumerate(exercises):
        label = chr(ord("A") + i) if i < 26 else f"{i + 1}."
        sets = ex["sets"]
        reps = ex["reps"]
        line = f"{label}) {ex['name']} - {sets}x{reps}"
        if ex.get("weight"):
            line += f" @ {ex['weight']}"
        if ex.get("rest"):
            line += f", rest {ex['rest']}"
        if ex.get("notes"):
            line += f" ({ex['notes']})"
        lines.append(line)
    return "\n".join(lines)


def strength_session(
    duration_min: float,
    exercises: list[dict[str, Any]],
    name: str | None = None,
    why: str | None = None,
) -> BaseWorkout:
    """A strength workout. The full prescription lives in the description.

    `why`: optional short rationale shown above the exercise list (1-2 lines).
    """
    if not exercises:
        raise ValueError("exercises must be non-empty")

    body = _format_exercises(exercises)
    description = f"{why.strip()}\n\n{body}" if why else body

    duration_s = duration_min * 60
    step = create_interval_step(duration_seconds=duration_s, step_order=1)

    return BaseWorkout(
        workoutName=name or f"Strength {int(duration_min)}min",
        sportType=_STRENGTH_SPORT,
        estimatedDurationInSecs=int(duration_s),
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType=_STRENGTH_SPORT,
                workoutSteps=[step],
            )
        ],
        description=description,
    )
