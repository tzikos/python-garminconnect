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
from datetime import date, timedelta
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
    intake: dict[str, Any] | None = None,
) -> GenerateResult:
    """Generate a plan and persist it. Returns the new plan_id and warnings.

    `chat_fn` is injectable for tests; defaults to the real OpenRouter call.
    `intake` carries the answers (and race course research) from a chat
    intake, when the plan came from one.
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
        "enabled_sports": prof.enabled_sports or [],
        "sport_profiles": prof.sport_profiles or {},
    }

    # Anchor the plan to the Monday of the week containing start_date so the
    # LLM can design clean Mon-Sun weeks. Workouts before the user's actual
    # start_date are filtered out after generation, leaving a partial first
    # week if needed.
    anchor_monday = start_date - timedelta(days=start_date.weekday())

    user_msg = build_user_prompt(
        goal_text=goal_text,
        start_date=anchor_monday,
        end_date=end_date,
        profile=profile_dict,
        start_volume_km=start_volume_km,
        peak_volume_km=peak_volume_km,
        taper_weeks=taper_weeks,
        intake=intake,
    )

    result = chat_fn([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    parsed = _parse_plan_json(result.content)
    if start_date != anchor_monday:
        _drop_workouts_before(parsed, start_date)
    _drop_incomplete_workouts(parsed)
    # If repair dropped a partial trailing week, prune empty weeks so
    # validation doesn't reject the plan.
    parsed["weekly_structure"] = [
        w for w in parsed.get("weekly_structure", [])
        if w.get("workouts")
    ]
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


# ---------------------------------------------------------------- filtering


def _drop_workouts_before(plan: dict[str, Any], cutoff: date) -> None:
    """Remove workouts dated before `cutoff` from every week. In place."""
    for week in plan.get("weekly_structure", []):
        week["workouts"] = [
            w for w in week.get("workouts", [])
            if date.fromisoformat(w["date"]) >= cutoff
        ]


_REQUIRED_WORKOUT_KEYS = ("date", "sport", "primitive_type", "title")


def _drop_incomplete_workouts(plan: dict[str, Any]) -> None:
    """Drop workouts missing required fields. Aggressive repair may leave
    a partial workout at the cut point; this prunes it instead of letting
    validation reject the whole plan.
    """
    for week in plan.get("weekly_structure", []):
        week["workouts"] = [
            w for w in week.get("workouts", [])
            if all(w.get(k) for k in _REQUIRED_WORKOUT_KEYS)
        ]


# ----------------------------------------------------------------- parsing


_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_plan_json(content: str) -> dict[str, Any]:
    """Tolerant JSON extraction.

    Handles bare JSON, markdown-fenced JSON, and leading/trailing prose.
    On parse failure, attempts to repair a truncated JSON response (very
    common when a free LLM hits its output token cap mid-stream).
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

    # Pre-process: strip trailing commas (common LLM JSON mistake).
    text = _strip_trailing_commas(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as first_err:
        # Aggressive repair: walk every "after a close-bracket" position from
        # the end of the text backward, balancing brackets and attempting a
        # parse. Returns the longest prefix that parses.
        recovered = _aggressive_repair(text)
        if recovered is not None:
            return recovered
        raise ValueError(
            f"Could not parse plan JSON: {first_err}\n--- raw ---\n{content[:600]}"
        ) from first_err


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before `}` or `]`, respecting string literals."""
    out: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            out.append(c)
            i += 1
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == ",":
            # Peek past whitespace; if next non-ws char closes a struct, drop.
            j = i + 1
            while j < len(text) and text[j] in " \t\n\r":
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1  # skip the comma
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _aggressive_repair(text: str) -> dict[str, Any] | None:
    """Walk close-bracket positions from latest to earliest; for each, balance
    open brackets and attempt to parse. Return the first successfully parsed
    dict, or None if nothing parses.

    Aggressively tolerant — handles arbitrary truncation as long as some
    prefix of `text` represents a structurally-complete-after-balancing
    object.
    """
    cut_points = _close_bracket_positions(text)
    for cut in reversed(cut_points):
        prefix = _strip_trailing_commas(text[:cut].rstrip())
        if prefix.endswith(","):
            prefix = prefix[:-1]
        stack = _open_bracket_stack(prefix)
        closing = "".join("]" if c == "[" else "}" for c in reversed(stack))
        candidate = prefix + closing
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _close_bracket_positions(text: str) -> list[int]:
    """Return positions immediately AFTER each `}` or `]` outside of strings."""
    positions: list[int] = []
    in_string = False
    escape = False
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c in "}]":
            positions.append(i + 1)
    return positions


def _open_bracket_stack(text: str) -> list[str]:
    """Return the unclosed `{`/`[` stack at end of `text`, ignoring strings."""
    stack: list[str] = []
    in_string = False
    escape = False
    for c in text:
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c in "{[":
            stack.append(c)
        elif c in "}]" and stack:
            stack.pop()
    return stack


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
