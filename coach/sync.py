"""Push planned workouts from the local DB to Garmin Connect.

Flow per ScheduledWorkout (status="planned"):
  1. Build the typed workout via primitives.build()
  2. Upload via Garmin.upload_workout -> get workoutId
  3. Schedule via Garmin.schedule_workout(workoutId, date)
  4. Persist garmin_workout_id + garmin_schedule_id, set status="uploaded"

Rows outside an optional from_date cutoff and rows not at status="planned"
are skipped. Refinement uses the cutoff to leave elapsed training alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select

from coach.db import session
from coach.models import Plan, ScheduledWorkout
from coach.primitives import build

if TYPE_CHECKING:
    from garminconnect import Garmin


@dataclass
class SyncResult:
    plan_id: int
    uploaded: int
    skipped: int
    failed: list[tuple[int, str]]  # (workout_id, error_message)


@dataclass
class UnpushResult:
    plan_id: int
    removed: int
    skipped: int
    failed: list[tuple[int, str]]


def push_plan(plan_id: int, api: Garmin, *, from_date: date | None = None) -> SyncResult:
    """Upload + schedule every "planned" workout in `plan_id`."""
    uploaded = 0
    skipped = 0
    failed: list[tuple[int, str]] = []

    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")

        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()

        for row in rows:
            if row.status != "planned" or (from_date is not None and row.date < from_date):
                skipped += 1
                continue

            try:
                workout = build(row.primitive_type, row.primitive_params)
                # Override name/description from the DB row when set.
                if row.title:
                    workout.workoutName = row.title
                if row.description and not workout.description:
                    workout.description = row.description

                upload_resp = api.upload_workout(workout.to_dict())
                workout_id = _extract_workout_id(upload_resp)

                schedule_resp = api.schedule_workout(
                    workout_id, row.date.isoformat()
                )
                schedule_id = _extract_schedule_id(schedule_resp)

                row.garmin_workout_id = workout_id
                row.garmin_schedule_id = schedule_id
                row.status = "uploaded"
                uploaded += 1

            except Exception as e:  # noqa: BLE001 - report and continue
                failed.append((row.id, str(e)))

    return SyncResult(
        plan_id=plan_id, uploaded=uploaded, skipped=skipped, failed=failed
    )


def unpush_plan(plan_id: int, api: Garmin, *, from_date: date | None = None) -> UnpushResult:
    """Reverse a push: unschedule + delete every uploaded workout in the plan.

    For each row at status="uploaded":
      1. unschedule_workout(garmin_schedule_id) if known (removes from calendar)
      2. delete_workout(garmin_workout_id) (removes from library)
      3. Clear garmin ids, set status back to "planned"

    Rows already at "planned" (or missing IDs) are skipped. Per-row failures
    don't abort the batch.
    """
    removed = 0
    skipped = 0
    failed: list[tuple[int, str]] = []

    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id} not found")

        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()

        for row in rows:
            if (
                row.status != "uploaded"
                or row.garmin_workout_id is None
                or (from_date is not None and row.date < from_date)
            ):
                skipped += 1
                continue
            try:
                if row.garmin_schedule_id is not None:
                    api.unschedule_workout(row.garmin_schedule_id)
                api.delete_workout(row.garmin_workout_id)
                row.garmin_workout_id = None
                row.garmin_schedule_id = None
                row.status = "planned"
                removed += 1
            except Exception as e:  # noqa: BLE001
                failed.append((row.id, str(e)))

    return UnpushResult(
        plan_id=plan_id, removed=removed, skipped=skipped, failed=failed
    )


def _extract_workout_id(resp: object) -> int:
    """Pluck the workoutId from an upload response (shape varies a bit)."""
    if isinstance(resp, dict):
        for key in ("workoutId", "id"):
            if key in resp:
                return int(resp[key])
        # Some endpoints nest it under "workout"
        if "workout" in resp and isinstance(resp["workout"], dict):
            wid = resp["workout"].get("workoutId") or resp["workout"].get("id")
            if wid:
                return int(wid)
    raise ValueError(f"Could not find workoutId in upload response: {resp!r}")


def _extract_schedule_id(resp: object) -> int | None:
    """Pluck the schedule id from a schedule response (best-effort)."""
    if isinstance(resp, dict):
        for key in ("workoutScheduleId", "scheduleId", "id"):
            if key in resp:
                return int(resp[key])
    return None
