"""Collect completed activities and persist agent-written evaluations.

Garmin calls here are read-only. Fetching evidence never marks it evaluated.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from coach.db import session
from coach.models import ActivityReview, Plan, ScheduledWorkout


def workout_snapshot(workout: ScheduledWorkout) -> dict[str, Any]:
    """Capture the prescribed session independently of its mutable DB row."""
    return {
        "workout_id": workout.id,
        "date": workout.date.isoformat(),
        "week_number": workout.week_number,
        "sport": workout.sport,
        "title": workout.title,
        "description": workout.description,
        "primitive_type": workout.primitive_type,
        "primitive_params": workout.primitive_params,
    }


def fetch_pending(
    plan_id: int, api: Any, *, today: date | None = None
) -> dict[str, Any]:
    """Fetch the inclusive elapsed plan period; skip evaluated activity IDs."""
    today = today or date.today()
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")
        start, end = plan.start_date, min(plan.end_date, today)
    result: dict[str, Any] = {"pending": [], "skipped": 0, "errors": []}
    if end < start:
        return result

    # The library paginates this endpoint. Do not use a latest-N shortcut:
    # late uploads and activities on rest days still belong in the review.
    activities = api.get_activities_by_date(start.isoformat(), end.isoformat())
    seen = set()
    for activity in activities:
        try:
            activity_id = int(activity["activityId"])
            activity_date = date.fromisoformat(activity["startTimeLocal"][:10])
        except (KeyError, TypeError, ValueError) as exc:
            result["errors"].append(f"Activity missing a valid ID/local date: {exc}")
            continue
        if activity_id in seen or not start <= activity_date <= end:
            continue
        seen.add(activity_id)
        with session() as s:
            row = s.get(ActivityReview, (plan_id, activity_id))
            if row is not None and row.evaluation is not None:
                result["skipped"] += 1
                continue
            evidence: dict[str, Any] = {"summary": activity, "errors": []}
            for key, method in (
                ("details", "get_activity"),
                ("splits", "get_activity_splits"),
            ):
                try:
                    evidence[key] = getattr(api, method)(str(activity_id))
                except Exception as exc:  # noqa: BLE001 - retain summary for review
                    evidence["errors"].append(f"{key}: {exc}")
            if row is None:
                row = ActivityReview(
                    plan_id=plan_id,
                    activity_id=activity_id,
                    activity_date=activity_date,
                    evidence=evidence,
                )
                s.add(row)
            else:
                row.activity_date = activity_date
                row.evidence = evidence
            result["pending"].append(
                {
                    "activity_id": activity_id,
                    "activity_date": activity_date.isoformat(),
                    "evidence": evidence,
                }
            )
    return result


def list_reviews(plan_id: int) -> list[dict[str, Any]]:
    """Return both pending evidence and saved evaluations, without network IO."""
    with session() as s:
        if s.get(Plan, plan_id) is None:
            raise ValueError(f"Plan {plan_id} not found")
        rows = s.scalars(
            select(ActivityReview)
            .where(
                ActivityReview.plan_id == plan_id,
            )
            .order_by(ActivityReview.activity_date, ActivityReview.activity_id)
        ).all()
        return [
            {
                "activity_id": row.activity_id,
                "activity_date": row.activity_date.isoformat(),
                "evidence": row.evidence,
                "evaluation": row.evaluation,
                "evaluated_at": (
                    row.evaluated_at.isoformat() if row.evaluated_at else None
                ),
            }
            for row in rows
        ]


def save_evaluations(plan_id: int, evaluations: list[dict[str, Any]]) -> dict[str, int]:
    """Atomically save completed assessments; existing evaluations are immutable."""
    if not isinstance(evaluations, list):
        raise ValueError("Evaluations must be a JSON list")
    saved = skipped = 0
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")
        for item in evaluations:
            if not isinstance(item, dict) or type(item.get("activity_id")) is not int:
                raise ValueError("Each evaluation needs an integer activity_id")
            row = s.get(ActivityReview, (plan_id, item["activity_id"]))
            if row is None:
                raise ValueError(
                    f"Activity {item['activity_id']} has not been fetched for this plan"
                )
            if row.evaluation is not None:
                skipped += 1
                continue
            for key in ("assessment", "recommendation"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    raise ValueError(f"Evaluation needs a non-empty {key}")
            snapshot = None
            workout_id = item.get("workout_id")
            if workout_id is not None:
                if type(workout_id) is not int:
                    raise ValueError("workout_id must be an integer or null")
                workout = s.get(ScheduledWorkout, workout_id)
                if workout is None or workout.plan_id != plan_id:
                    raise ValueError("Matched workout must belong to this plan")
                snapshot = workout_snapshot(workout)
            row.evaluation = {
                "assessment": item["assessment"],
                "recommendation": item["recommendation"],
                "planned_workout": snapshot,
                "plan_version": plan.version,
            }
            row.evaluated_at = datetime.now(timezone.utc)
            saved += 1
    return {"saved": saved, "skipped": skipped}
