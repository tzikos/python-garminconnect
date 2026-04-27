"""Pace and HR zones from a recent 5k time / threshold HR.

Approximation note: we use Daniels-style pace ratios off 5k pace rather
than the full VDOT lookup table. Accurate enough for V1; if a user reports
their threshold work feels off we can swap in the table.

Conventions:
- All "seconds" are int (whole seconds).
- "min_per_km" / "max_per_km" are seconds-per-km bounds; the *min* is the
  faster end of the range (smaller seconds), *max* is the slower end.
"""

from __future__ import annotations

from typing import TypedDict

# Multipliers on 5k pace (seconds/km) for each training zone.
# faster end -> slower end. Larger value = slower pace.
_PACE_MULTIPLIERS = {
    "easy":       (1.25, 1.40),
    "marathon":   (1.07, 1.10),
    "threshold":  (1.04, 1.07),
    "interval":   (0.96, 1.00),
    "repetition": (0.88, 0.92),
}


class PaceRange(TypedDict):
    min_per_km: int  # faster bound (sec/km)
    max_per_km: int  # slower bound (sec/km)


class HRRange(TypedDict):
    min_bpm: int
    max_bpm: int


def compute_pace_zones(recent_5k_seconds: int) -> dict[str, PaceRange]:
    """Return training pace ranges (sec/km) from a recent 5k time."""
    if recent_5k_seconds <= 0:
        raise ValueError("recent_5k_seconds must be > 0")
    pace_5k_per_km = recent_5k_seconds / 5.0  # seconds per km
    zones: dict[str, PaceRange] = {}
    for name, (fast_mul, slow_mul) in _PACE_MULTIPLIERS.items():
        zones[name] = PaceRange(
            min_per_km=int(round(pace_5k_per_km * fast_mul)),
            max_per_km=int(round(pace_5k_per_km * slow_mul)),
        )
    return zones


# Joe Friel-style HR zones as %LTHR (anchored to lactate threshold HR).
# Each entry is (low_pct, high_pct).
_HR_ZONES_LTHR = {
    "Z1": (0.65, 0.81),
    "Z2": (0.81, 0.89),
    "Z3": (0.90, 0.93),
    "Z4": (0.94, 0.99),
    "Z5": (1.00, 1.06),
}

# Fallback: %max HR if only max_hr is known.
_HR_ZONES_MAX = {
    "Z1": (0.50, 0.60),
    "Z2": (0.60, 0.70),
    "Z3": (0.70, 0.80),
    "Z4": (0.80, 0.90),
    "Z5": (0.90, 1.00),
}


def compute_hr_zones(
    threshold_hr: int | None = None,
    max_hr: int | None = None,
) -> dict[str, HRRange]:
    """Return 5 HR zones in bpm.

    Prefers threshold-anchored zones when threshold_hr is given. Falls back
    to max-HR-anchored zones otherwise. Raises if neither is provided.
    """
    if threshold_hr is None and max_hr is None:
        raise ValueError("provide threshold_hr or max_hr")

    if threshold_hr is not None:
        anchor, table = threshold_hr, _HR_ZONES_LTHR
    else:
        anchor, table = max_hr, _HR_ZONES_MAX

    return {
        zone: HRRange(
            min_bpm=int(round(anchor * lo)),
            max_bpm=int(round(anchor * hi)),
        )
        for zone, (lo, hi) in table.items()
    }


def format_pace(seconds_per_km: int) -> str:
    """'5:42' representation of a sec/km pace, for descriptions."""
    m, s = divmod(int(seconds_per_km), 60)
    return f"{m}:{s:02d}"
