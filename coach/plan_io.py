"""Export / import plans as JSON for manual editing.

The on-disk JSON shape is the same as what the LLM produces, plus
plan-level metadata (name, goal, dates). This lets the same validation
+ materialization logic serve both LLM output and hand-edited files.

Workflow for editing an LLM-generated plan:
    coach plan export 1 --out plan.json
    # edit plan.json in your IDE
    coach plan import plan.json --plan-id 1   # overwrites plan 1
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from coach.db import session
from coach.models import Plan, ScheduledWorkout
from coach.primitives import PRIMITIVES


# ----------------------------------------------------------- validation


def validate_plan_dict(plan: dict[str, Any]) -> None:
    """Surface clear errors before any DB writes. Used by both planner + import."""
    if "name" not in plan or "weekly_structure" not in plan:
        raise ValueError("Plan must have 'name' and 'weekly_structure' keys")
    if not isinstance(plan["weekly_structure"], list) or not plan["weekly_structure"]:
        raise ValueError("'weekly_structure' must be a non-empty list")

    for wi, week in enumerate(plan["weekly_structure"]):
        for wj, w in enumerate(week.get("workouts", [])):
            ptype = w.get("primitive_type")
            if ptype not in PRIMITIVES:
                raise ValueError(
                    f"Week {wi + 1} workout {wj + 1}: "
                    f"unknown primitive_type {ptype!r}. "
                    f"Valid: {sorted(PRIMITIVES)}"
                )
            try:
                PRIMITIVES[ptype](**(w.get("primitive_params") or {}))
            except Exception as e:  # noqa: BLE001
                raise ValueError(
                    f"Week {wi + 1} workout {wj + 1} ({ptype}): "
                    f"primitive rejected params: {e}"
                ) from e
            for required in ("date", "sport", "title"):
                if not w.get(required):
                    raise ValueError(
                        f"Week {wi + 1} workout {wj + 1}: missing {required!r}"
                    )


# ---------------------------------------------------------------- export


def export_plan(plan_id: int) -> dict[str, Any]:
    """Dump a plan + workouts as a JSON-serializable dict."""
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()

        # Group by week_number, preserving theme/target volume from plan.structure
        weeks_meta = {
            int(w.get("week_number", i + 1)): w
            for i, w in enumerate(plan.structure.get("weeks", []) or [])
        }
        by_week: dict[int, list[dict[str, Any]]] = {}
        for r in rows:
            by_week.setdefault(r.week_number, []).append({
                "date": r.date.isoformat(),
                "sport": r.sport,
                "primitive_type": r.primitive_type,
                "primitive_params": r.primitive_params,
                "title": r.title,
                "description": r.description,
            })

        weekly_structure = []
        for week_num in sorted(by_week):
            meta = weeks_meta.get(week_num, {})
            weekly_structure.append({
                "week_number": week_num,
                "theme": meta.get("theme"),
                "target_volume_km": meta.get("target_volume_km"),
                "workouts": by_week[week_num],
            })

        return {
            "name": plan.name,
            "goal_text": plan.goal_text,
            "start_date": plan.start_date.isoformat(),
            "end_date": plan.end_date.isoformat(),
            "status": plan.status,
            "weekly_structure": weekly_structure,
        }


# ---------------------------------------------------------------- import


def import_plan(
    plan_dict: dict[str, Any],
    plan_id_to_overwrite: int | None = None,
) -> tuple[int, int]:
    """Validate `plan_dict` and write it to the DB.

    If `plan_id_to_overwrite` is given, the existing plan's workouts are
    deleted and replaced. Refuses if any of those workouts have already
    been uploaded — unpush them first.

    Returns (plan_id, n_workouts).
    """
    validate_plan_dict(plan_dict)

    for required in ("name", "goal_text", "start_date", "end_date"):
        if not plan_dict.get(required):
            raise ValueError(f"Plan dict missing top-level {required!r}")

    start = date.fromisoformat(plan_dict["start_date"])
    end = date.fromisoformat(plan_dict["end_date"])

    n = 0
    with session() as s:
        if plan_id_to_overwrite is not None:
            plan = s.get(Plan, plan_id_to_overwrite)
            if plan is None:
                raise ValueError(f"Plan {plan_id_to_overwrite} not found")
            uploaded = [w for w in plan.workouts if w.status == "uploaded"]
            if uploaded:
                raise ValueError(
                    f"Plan {plan_id_to_overwrite} has {len(uploaded)} uploaded "
                    "workout(s). Run `coach sync unpush` first."
                )
            for w in list(plan.workouts):
                s.delete(w)
            plan.name = plan_dict["name"]
            plan.goal_text = plan_dict["goal_text"]
            plan.start_date = start
            plan.end_date = end
            plan.version += 1
        else:
            plan = Plan(
                name=plan_dict["name"],
                goal_text=plan_dict["goal_text"],
                start_date=start,
                end_date=end,
            )
            s.add(plan)

        plan.structure = {"weeks": [
            {k: v for k, v in week.items() if k != "workouts"}
            for week in plan_dict["weekly_structure"]
        ]}
        s.flush()

        for week in plan_dict["weekly_structure"]:
            for w in week.get("workouts", []):
                s.add(ScheduledWorkout(
                    plan_id=plan.id,
                    date=date.fromisoformat(w["date"]),
                    week_number=int(week.get("week_number", 1)),
                    sport=w["sport"],
                    title=w["title"],
                    description=w.get("description"),
                    primitive_type=w["primitive_type"],
                    primitive_params=w.get("primitive_params") or {},
                ))
                n += 1
        s.flush()
        return plan.id, n
