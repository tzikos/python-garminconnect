"""End-to-end plan generation: profile + goal -> DB rows.

Flow:
  1. Load UserProfile from DB.
  2. Build the prompt (system + user with pre-computed paces + volume).
  3. Call the LLM (OpenRouter), get JSON back.
  4. Parse + validate every workout against the primitive registry.
  5. In one transaction: create the Plan row + ScheduledWorkout rows.
  6. Run interference_check on every week, return warnings to the caller.

If anything fails between steps 3 and 5 we don't write a partial plan to
the DB.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from coach.db import session
from coach.llm.openrouter import ChatResult, chat
from coach.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from coach.models import Plan, ScheduledWorkout, UserProfile
from coach.plan_io import validate_plan_dict
from coach.tools import Warning, interference_check


@dataclass
class GenerateResult:
    plan_id: int
    plan_name: str
    workouts_created: int
    warnings: list[Warning]
    model_used: str
    raw_response: str


def generate_plan(
    *,
    goal_text: str,
    start_date: date,
    end_date: date,
    chat_fn: Callable[[list[dict[str, str]]], ChatResult] | None = None,
    start_volume_km: float = 25,
    peak_volume_km: float | None = None,
    taper_weeks: int = 2,
) -> GenerateResult:
    """Generate a plan and persist it. Returns the new plan_id and warnings.

    `chat_fn` is injectable for tests; defaults to the real OpenRouter call.
    """
    chat_fn = chat_fn or chat

    with session() as s:
        prof = s.get(UserProfile, 1)
    if prof is None:
        raise RuntimeError("No profile. Run `coach profile set --name ...` first.")

    profile_dict = {
        "name": prof.name,
        "recent_5k_seconds": prof.recent_5k_seconds,
        "threshold_hr": prof.threshold_hr,
        "max_hr": prof.max_hr,
        "preferred_days": prof.preferred_days,
        "weekly_hours_target": prof.weekly_hours_target,
        "notes": prof.notes,
    }

    user_msg = build_user_prompt(
        goal_text=goal_text,
        start_date=start_date,
        end_date=end_date,
        profile=profile_dict,
        start_volume_km=start_volume_km,
        peak_volume_km=peak_volume_km,
        taper_weeks=taper_weeks,
    )

    result = chat_fn([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    parsed = _parse_plan_json(result.content)
    validate_plan_dict(parsed)

    plan_id, n_workouts = _materialize(parsed, goal_text, start_date, end_date)
    warnings = _collect_warnings(parsed)

    return GenerateResult(
        plan_id=plan_id,
        plan_name=parsed["name"],
        workouts_created=n_workouts,
        warnings=warnings,
        model_used=result.model_used,
        raw_response=result.content,
    )


# ----------------------------------------------------------------- parsing


_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_plan_json(content: str) -> dict[str, Any]:
    """Tolerant JSON extraction.

    Handles bare JSON, markdown-fenced JSON, and leading/trailing prose.
    """
    text = content.strip()

    m = _FENCED_JSON.search(text)
    if m:
        text = m.group(1).strip()

    # Find the outermost {...} if there's still surrounding prose.
    if not text.startswith("{"):
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            raise ValueError(f"No JSON object found in response:\n{content[:400]}")
        text = text[first : last + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse plan JSON: {e}\n--- raw ---\n{content[:600]}"
        ) from e


# -------------------------------------------------------------- persistence


def _materialize(
    plan: dict[str, Any],
    goal_text: str,
    start_date: date,
    end_date: date,
) -> tuple[int, int]:
    """Insert Plan + ScheduledWorkout rows in a single transaction."""
    n = 0
    with session() as s:
        plan_row = Plan(
            name=plan["name"],
            goal_text=goal_text,
            start_date=start_date,
            end_date=end_date,
            structure={"weeks": [
                {k: v for k, v in week.items() if k != "workouts"}
                for week in plan["weekly_structure"]
            ]},
        )
        s.add(plan_row)
        s.flush()

        for week in plan["weekly_structure"]:
            for w in week.get("workouts", []):
                s.add(ScheduledWorkout(
                    plan_id=plan_row.id,
                    date=date.fromisoformat(w["date"]),
                    week_number=int(week.get("week_number", 1)),
                    sport=w["sport"],
                    title=w["title"],
                    description=(w.get("description") or w.get("why") or None),
                    primitive_type=w["primitive_type"],
                    primitive_params=w.get("primitive_params") or {},
                ))
                n += 1
        s.flush()
        return plan_row.id, n


def _collect_warnings(plan: dict[str, Any]) -> list[Warning]:
    """Run interference_check on every week's placed workouts."""
    out: list[Warning] = []
    for week in plan["weekly_structure"]:
        sched = [
            {
                "date": date.fromisoformat(w["date"]),
                "sport": w["sport"],
                "primitive_type": w["primitive_type"],
            }
            for w in week.get("workouts", [])
        ]
        out.extend(interference_check(sched))
    return out
