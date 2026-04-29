"""Canonical sport list + benchmark field schemas.

Single source of truth for what sports the app supports and what
benchmarks each sport collects. Used by the prompt builder, the API
schemas, and the frontend (via /api/settings/sports).

V1 supports running, strength, calisthenics. Cycling and swimming
are out until we have primitives for them — see plan.json caveat.
"""

from __future__ import annotations

from typing import Any

# Order matters — drives the order of sport tiles in the UI.
SPORTS: list[str] = ["running", "strength", "calisthenics"]


# Empty per-sport benchmark templates. UI-driven editing fills these in.
EMPTY_BENCHMARKS: dict[str, dict[str, Any]] = {
    "running": {
        # list of {distance_km: number, seconds: int}
        "race_times": [],
    },
    "strength": {
        # all kg; any field may be omitted
        "lifts_1rm": {
            "squat_kg": None,
            "bench_kg": None,
            "deadlift_kg": None,
            "ohp_kg": None,
        },
        "training_age_years": None,
    },
    "calisthenics": {
        "max_reps": {
            "pullups": None,
            "dips": None,
            "pushups": None,
            "squats": None,
            "pistol_squats": None,
        },
        "max_holds": {
            "l_sit_seconds": None,
            "handstand_seconds": None,
        },
    },
}


def empty_for(sport: str) -> dict[str, Any]:
    """Return a fresh empty benchmark dict for `sport`."""
    import copy

    return copy.deepcopy(EMPTY_BENCHMARKS.get(sport, {}))
