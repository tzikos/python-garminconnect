"""Layer 2 — deterministic helpers the LLM uses as tools."""

from coach.tools.checks import (
    HARDNESS,
    Warning,
    interference_check,
    validate_workout,
)
from coach.tools.pacing import (
    HRRange,
    PaceRange,
    compute_hr_zones,
    compute_pace_zones,
    format_pace,
)
from coach.tools.progression import weekly_volume_progression
from coach.tools.scheduling import place_in_calendar

__all__ = [
    "HARDNESS",
    "HRRange",
    "PaceRange",
    "Warning",
    "compute_hr_zones",
    "compute_pace_zones",
    "format_pace",
    "interference_check",
    "place_in_calendar",
    "validate_workout",
    "weekly_volume_progression",
]
