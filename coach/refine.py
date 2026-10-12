"""Apply a reviewed plan revision while preserving elapsed training history."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any

from coach.db import session
from coach.models import Plan, ScheduledWorkout
from coach.plan_io import validate_plan_dict
from coach.review import workout_snapshot


def _signature(workout: dict[str, Any]) -> str:
    # IDs and sync state are not editable plan content.
    fields = (
        "date",
        "week_number",
        "sport",
        "title",
        "description",
        "primitive_type",
        "primitive_params",
    )
    return json.dumps({key: workout.get(key) for key in fields}, sort_keys=True)


def refine_plan(
    plan_id: int,
    proposed: dict[str, Any],
    from_date: date,
    *,
    dry_run: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Preview/apply future changes. Uploads must be removed before applying."""
    today = today or date.today()
    if from_date <= today:
        raise ValueError(
            "Refinement must start after today to preserve completed training"
        )
    if not isinstance(proposed, dict):
        raise ValueError("Proposed plan must be a JSON object")
    validate_plan_dict(proposed)
    reason = proposed.get("refinement_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            "Add refinement_reason explaining the evidence for these changes"
        )
    candidates = []
    for week in proposed["weekly_structure"]:
        for workout in week.get("workouts", []):
            item = {**workout, "week_number": int(week.get("week_number", 1))}
            item["primitive_params"] = item.get("primitive_params") or {}
            date.fromisoformat(item["date"])
            candidates.append(item)

    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")
        if (
            proposed.get("plan_id") != plan_id
            or proposed.get("version") != plan.version
        ):
            raise ValueError(
                "Stale or wrong plan export; export the plan again before refining"
            )
        for key in ("name", "goal_text", "start_date", "end_date"):
            current = getattr(plan, key)
            if proposed.get(key) != (
                current.isoformat() if isinstance(current, date) else current
            ):
                raise ValueError(
                    f"Refinement must preserve {key}; use /adjust for a changed goal"
                )
        if not plan.start_date <= from_date <= plan.end_date:
            raise ValueError("Refinement start must be inside the plan period")
        if any(
            not plan.start_date <= date.fromisoformat(w["date"]) <= plan.end_date
            for w in candidates
        ):
            raise ValueError("Workout dates must be inside the plan period")

        rows = list(plan.workouts)
        snapshots = [workout_snapshot(row) for row in rows]
        old_past = Counter(
            _signature(w) for w in snapshots if w["date"] < from_date.isoformat()
        )
        new_past = Counter(
            _signature(w) for w in candidates if w["date"] < from_date.isoformat()
        )
        if old_past != new_past:
            raise ValueError("Refinement cannot change workouts before from_date")

        available: dict[str, list[ScheduledWorkout]] = defaultdict(list)
        for row in rows:
            if row.date >= from_date:
                available[_signature(workout_snapshot(row))].append(row)
        additions = []
        for item in candidates:
            if item["date"] < from_date.isoformat():
                continue
            matches = available[_signature(item)]
            if matches:
                matches.pop()
            else:
                additions.append(item)
        removals = [row for group in available.values() for row in group]
        if any(row.status == "completed" for row in removals):
            raise ValueError("Refinement cannot change completed workouts")
        blocked = [
            row.id
            for row in removals
            if row.status == "uploaded"
            or row.garmin_workout_id is not None
            or row.garmin_schedule_id is not None
        ]
        result = {
            "plan_id": plan_id,
            "from_date": from_date.isoformat(),
            "remove": [workout_snapshot(row) for row in removals],
            "add": additions,
            "uploaded_workout_ids": blocked,
            "applied": False,
        }
        if dry_run:
            return result
        if blocked:
            raise ValueError(
                f"Changed workouts still exist on Garmin: {blocked}. Preview and unpush the future period first."
            )
        if not removals and not additions:
            return result

        # Archive the prior prescription before changing any row. Past rows and
        # unchanged future rows keep their identities and Garmin associations.
        structure = dict(plan.structure or {})
        history = list(structure.get("refinements", []))
        history.append(
            {
                "previous_version": plan.version,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "from_date": from_date.isoformat(),
                "reason": reason,
                "before": snapshots,
                "previous_weeks": structure.get("weeks", []),
                "changes": result,
            }
        )
        old_weeks = {
            int(w.get("week_number", i + 1)): w
            for i, w in enumerate(structure.get("weeks", []))
        }
        future_weeks = {
            w["week_number"] for w in candidates if w["date"] >= from_date.isoformat()
        }
        future_weeks.update(row.week_number for row in removals)
        for i, week in enumerate(proposed["weekly_structure"]):
            number = int(week.get("week_number", i + 1))
            if number in future_weeks:
                old_weeks[number] = {k: v for k, v in week.items() if k != "workouts"}
        plan.structure = {
            **structure,
            "weeks": [old_weeks[k] for k in sorted(old_weeks)],
            "refinements": history,
        }
        for row in removals:
            s.delete(row)
        for item in additions:
            s.add(
                ScheduledWorkout(
                    plan_id=plan_id,
                    date=date.fromisoformat(item["date"]),
                    week_number=item["week_number"],
                    sport=item["sport"],
                    title=item["title"],
                    description=item.get("description"),
                    primitive_type=item["primitive_type"],
                    primitive_params=item["primitive_params"],
                )
            )
        plan.version += 1
        result = {**result, "applied": True, "version": plan.version}
        return result
