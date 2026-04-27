"""Sanity checks: per-workout validation and weekly interference detection.

Both return a list of `Warning`. The LLM (or a UI layer) can decide what
to surface to the user vs. silently fix. Severities:
- "info":  worth knowing, not necessarily wrong
- "warn":  likely a problem, recommend revising
- "error": almost certainly wrong, do not push
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Default hardness per primitive_type. Override per-workout in the
# week_schedule entries when needed (e.g. a deload tempo).
HARDNESS = {
    "easy_run": "easy",
    "long_run": "moderate",
    "tempo_run": "hard",
    "interval_session": "hard",
    "strength_session": "moderate",
}


@dataclass
class Warning:
    severity: str
    message: str
    dates: list[date] = field(default_factory=list)


# ---------------------------------------------------------- per-workout


def validate_workout(
    primitive_type: str,
    params: dict[str, Any],
) -> list[Warning]:
    """Bounds-checks on a single workout's parameters."""
    warnings: list[Warning] = []

    if primitive_type in {"easy_run", "long_run"}:
        d = params.get("duration_min", 0)
        if d > 240:
            warnings.append(Warning("warn", f"{primitive_type} > 4hrs ({d}min)"))
        elif d < 15:
            warnings.append(
                Warning("info", f"{primitive_type} only {d}min — very short")
            )

    if primitive_type == "tempo_run":
        t = params.get("tempo_min", 0)
        if t > 60:
            warnings.append(Warning("warn", f"{t}min tempo block is unusually long"))
        if params.get("warmup_min", 15) < 10:
            warnings.append(
                Warning("warn", "tempo with <10min warmup risks early-effort spike")
            )

    if primitive_type == "interval_session":
        reps = params.get("reps", 0)
        work = params.get("work_min", 0)
        if reps > 15:
            warnings.append(Warning("warn", f"{reps} reps is very high"))
        if work > 10:
            warnings.append(Warning("warn", f"{work}min interval work is very long"))
        if work > 0 and params.get("recovery_min", 0) > work * 2:
            warnings.append(
                Warning("info", "recovery longer than 2x work — confirm this is intended")
            )

    if primitive_type == "strength_session":
        ex = params.get("exercises", [])
        if len(ex) > 12:
            warnings.append(Warning("warn", f"{len(ex)} exercises is a lot"))
        for e in ex:
            sets = e.get("sets", 0)
            if sets > 8:
                warnings.append(
                    Warning("info", f"{e.get('name', '?')}: {sets} sets is high")
                )

    return warnings


# ---------------------------------------------------------- weekly check


def interference_check(
    week_schedule: list[dict[str, Any]],
) -> list[Warning]:
    """Check a placed week for poor sequencing.

    Each entry: {"date": date, "sport": str, "primitive_type": str,
    "hardness": str | None}. If hardness is omitted we default from
    HARDNESS using primitive_type.
    """
    sched = sorted(
        ({**w, "hardness": w.get("hardness") or HARDNESS.get(w["primitive_type"], "moderate")}
         for w in week_schedule),
        key=lambda x: x["date"],
    )
    warnings: list[Warning] = []

    # Adjacent-day issues.
    for a, b in zip(sched, sched[1:]):
        if (b["date"] - a["date"]).days != 1:
            continue

        if a["hardness"] == "hard" and b["hardness"] == "hard":
            warnings.append(
                Warning(
                    "warn",
                    f"Two hard sessions back-to-back ({a['sport']} -> {b['sport']})",
                    [a["date"], b["date"]],
                )
            )
        if a["hardness"] == "hard" and b["primitive_type"] == "long_run":
            warnings.append(
                Warning(
                    "warn",
                    f"Hard {a['sport']} the day before long run",
                    [a["date"], b["date"]],
                )
            )
        if (
            a["primitive_type"] == "strength_session"
            and a["hardness"] == "hard"
            and b["primitive_type"] == "long_run"
        ):
            warnings.append(
                Warning(
                    "warn",
                    "Heavy strength immediately before long run",
                    [a["date"], b["date"]],
                )
            )

    # Weekly load.
    hard = [w for w in sched if w["hardness"] == "hard"]
    if len(hard) > 3:
        warnings.append(
            Warning(
                "warn",
                f"{len(hard)} hard sessions this week (recommended: <= 3)",
                [w["date"] for w in hard],
            )
        )

    return warnings
