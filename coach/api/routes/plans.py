"""Plan CRUD + generate + import/export."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from coach.api.schemas import (
    GenerateRequest,
    GenerateResponse,
    PlanCreate,
    PlanDetail,
    PlanSummary,
    WarningOut,
    WorkoutOut,
)
from coach.db import session
from coach.models import Plan, ScheduledWorkout
from coach.tools import interference_check

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _workout_to_out(w: ScheduledWorkout) -> WorkoutOut:
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


def _build_detail(plan: Plan, rows: list[ScheduledWorkout]) -> PlanDetail:
    # Run interference_check per week
    by_week: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_week.setdefault(r.week_number, []).append({
            "date": r.date,
            "sport": r.sport,
            "primitive_type": r.primitive_type,
        })
    warnings = []
    for entries in by_week.values():
        warnings.extend(interference_check(entries))

    return PlanDetail(
        id=plan.id,
        name=plan.name,
        goal_text=plan.goal_text,
        start_date=plan.start_date,
        end_date=plan.end_date,
        status=plan.status,
        version=plan.version,
        structure=plan.structure or {},
        workouts=[_workout_to_out(r) for r in rows],
        warnings=[
            WarningOut(severity=w.severity, message=w.message, dates=w.dates)
            for w in warnings
        ],
    )


@router.get("", response_model=list[PlanSummary])
def list_plans() -> list[PlanSummary]:
    with session() as s:
        plans = s.execute(select(Plan).order_by(Plan.created_at.desc())).scalars().all()
        out: list[PlanSummary] = []
        for p in plans:
            rows = s.execute(
                select(ScheduledWorkout).where(ScheduledWorkout.plan_id == p.id)
            ).scalars().all()
            out.append(PlanSummary(
                id=p.id,
                name=p.name,
                goal_text=p.goal_text,
                start_date=p.start_date,
                end_date=p.end_date,
                status=p.status,
                version=p.version,
                workout_count=len(rows),
                uploaded_count=sum(1 for r in rows if r.status == "uploaded"),
            ))
        return out


@router.post("", response_model=PlanDetail, status_code=201)
def create_plan(create: PlanCreate) -> PlanDetail:
    with session() as s:
        p = Plan(**create.model_dump())
        s.add(p)
        s.flush()
        return _build_detail(p, [])


@router.get("/{plan_id}", response_model=PlanDetail)
def get_plan(plan_id: int) -> PlanDetail:
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(404, f"Plan {plan_id} not found")
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()
        return _build_detail(plan, rows)


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int) -> None:
    with session() as s:
        plan = s.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(404, f"Plan {plan_id} not found")
        s.delete(plan)


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    from coach.llm import generate_plan

    try:
        result = generate_plan(
            goal_text=req.goal_text,
            start_date=req.start_date,
            end_date=req.end_date,
            start_volume_km=req.start_volume_km,
            peak_volume_km=req.peak_volume_km,
            taper_weeks=req.taper_weeks,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e)) from e

    with session() as s:
        plan = s.get(Plan, result.plan_id)
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == result.plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()
        return GenerateResponse(
            plan=_build_detail(plan, rows),
            model_used=result.model_used,
        )


@router.get("/{plan_id}/export")
def export(plan_id: int) -> dict:
    from coach.plan_io import export_plan

    try:
        return export_plan(plan_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/import", response_model=PlanDetail)
def import_(plan_dict: dict, plan_id: int | None = None) -> PlanDetail:
    from coach.plan_io import import_plan

    try:
        new_id, _ = import_plan(plan_dict, plan_id_to_overwrite=plan_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return get_plan(new_id)
