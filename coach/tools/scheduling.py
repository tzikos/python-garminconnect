"""Place a list of workouts onto specific dates within a week.

Pure scheduling — no fitness logic. Given a user's preferred days per
sport, assign each workout to a date. Falls back to any free day if
preferred slots are full or blacked out.

Day numbering follows Python's `datetime.weekday()`: Monday = 0, Sunday = 6.

V1 limit: one workout per date. Same-day double sessions (e.g. AM run
+ PM strength) come later when we add a `time_of_day` field to workouts.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any


def place_in_calendar(
    workouts: list[dict[str, Any]],
    preferred_days: dict[str, list[int]],
    week_start: date,
    blackout_dates: Iterable[date] | None = None,
) -> list[tuple[date, dict[str, Any]]]:
    """Return [(date, workout), ...] sorted by date.

    Each workout dict must include a "sport" key; `preferred_days` maps
    sport -> list of weekday ints (0=Mon, 6=Sun).

    Raises if more workouts are passed than free days in the week.
    """
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")

    blackout = set(blackout_dates or [])
    free_days = [
        week_start + timedelta(days=i)
        for i in range(7)
        if (week_start + timedelta(days=i)) not in blackout
    ]
    if len(workouts) > len(free_days):
        raise ValueError(
            f"{len(workouts)} workouts requested but only {len(free_days)} "
            "non-blackout days available"
        )

    placed: list[tuple[date, dict[str, Any]]] = []
    used: set[date] = set()

    for workout in workouts:
        sport = workout.get("sport")
        prefs = preferred_days.get(sport, list(range(7)))

        chosen: date | None = None
        for offset in prefs:
            d = week_start + timedelta(days=offset)
            if d not in used and d not in blackout:
                chosen = d
                break

        if chosen is None:
            # Fall back to any remaining free day.
            for d in free_days:
                if d not in used:
                    chosen = d
                    break

        if chosen is None:
            raise ValueError(f"no slot available for workout: {workout}")

        used.add(chosen)
        placed.append((chosen, workout))

    placed.sort(key=lambda x: x[0])
    return placed
