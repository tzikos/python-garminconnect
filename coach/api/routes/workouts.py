"""Workout CRUD within a plan."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coach.api.schemas import WorkoutCreate, WorkoutOut, WorkoutUpdate
from coach.db import session
from coach.models import Plan, ScheduledWorkout
from coach.primitives import PRIMITIVES

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


def _to_out(w: ScheduledWorkout) -> WorkoutOut:
    return WorkoutOut(
        id=w.id,
        plan_id=w.plan_id,
        date=w.date,
        week_number=w.week_number,
        sport=w.sport,
        title=w.title,
        description=w.description,
        primitive_type=w.primitive_type,
        primitive_params=w.primitive_params or {},
        garmin_workout_id=w.garmin_workout_id,
        garmin_schedule_id=w.garmin_schedule_id,
        status=w.status,
    )


def _validate_primitive(ptype: str, params: dict) -> str:
    """Build the workout to validate; return its default name."""
    if ptype not in PRIMITIVES:
        raise HTTPException(400, f"Unknown primitive: {ptype}")
    try:
        built = PRIMITIVES[ptype](**(params or {}))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Primitive rejected params: {e}") from e
    return built.workoutName


@router.post("", response_model=WorkoutOut, status_code=201)
def create_workout(create: WorkoutCreate) -> WorkoutOut:
    default_title = _validate_primitive(create.primitive_type, create.primitive_params)

    with session() as s:
        if s.get(Plan, create.plan_id) is None:
            raise HTTPException(404, f"Plan {create.plan_id} not found")
        w = ScheduledWorkout(
            plan_id=create.plan_id,
            date=create.date,
            week_number=create.week_number,
            sport=create.sport,
            title=create.title or default_title,
            description=create.description,
            primitive_type=create.primitive_type,
            primitive_params=create.primitive_params,
        )
        s.add(w)
        s.flush()
        return _to_out(w)


@router.patch("/{workout_id}", response_model=WorkoutOut)
def update_workout(workout_id: int, update: WorkoutUpdate) -> WorkoutOut:
    with session() as s:
        w = s.get(ScheduledWorkout, workout_id)
        if w is None:
            raise HTTPException(404, f"Workout {workout_id} not found")
        if w.status == "uploaded":
            raise HTTPException(
                409,
                "Workout is uploaded to Garmin. Unpush the plan first to edit.",
            )

        data = update.model_dump(exclude_unset=True)
        new_ptype = data.get("primitive_type", w.primitive_type)
        new_params = data.get("primitive_params", w.primitive_params)
        if "primitive_type" in data or "primitive_params" in data:
            _validate_primitive(new_ptype, new_params)

        for field, value in data.items():
            setattr(w, field, value)
        s.flush()
        return _to_out(w)


@router.delete("/{workout_id}", status_code=204)
def delete_workout(workout_id: int) -> None:
    with session() as s:
        w = s.get(ScheduledWorkout, workout_id)
        if w is None:
            raise HTTPException(404, f"Workout {workout_id} not found")
        if w.status == "uploaded":
            raise HTTPException(
                409,
                "Workout is uploaded to Garmin. Unpush the plan first to delete.",
            )
        s.delete(w)
