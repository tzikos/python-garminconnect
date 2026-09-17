"""Plan CRUD + generate + import/export."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from coach.api.schemas import (
    GenerateFromChatRequest,
    GenerateRequest,
    GenerateResponse,
    IntakeQuestion,
    IntakeRequest,
    IntakeResponse,
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


# ------------------------------------------------------------ chat intake


def _profile_dict() -> dict[str, Any]:
    """The stored profile as a plain dict, or {} if there isn't one yet."""
    from coach.models import UserProfile

    with session() as s:
        prof = s.get(UserProfile, 1)
        if prof is None:
            return {}
        return {
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


@router.post("/chat", response_model=IntakeResponse)
def intake_turn(req: IntakeRequest) -> IntakeResponse:
    """Advance the intake interview by one question."""
    from coach.llm.intake import next_turn

    try:
        turn = next_turn(
            history=[m.model_dump() for m in req.history],
            facts=req.facts,
            profile=_profile_dict(),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e)) from e

    return IntakeResponse(
        note=turn.note,
        facts=turn.facts,
        question=IntakeQuestion(**turn.question) if turn.question else None,
        ready=turn.ready,
        summary=turn.summary,
        model_used=turn.model_used,
        researched=turn.researched,
        warnings=turn.warnings,
    )


def _goal_text_from(facts: dict[str, Any]) -> str:
    """Build the one-line goal the generator plans against."""
    race = facts.get("race_name")
    research = facts.get("race_research") or {}
    if race:
        goal = f"Race {research.get('race_official_name') or race}"
        if facts.get("race_date"):
            goal += f" on {facts['race_date']}"
        if facts.get("race_distance_km"):
            goal += f" ({facts['race_distance_km']}km)"
        target = facts.get("race_target_seconds")
        if target:
            goal += f", target {timedelta(seconds=int(target))}"
        return goal
    return str(facts.get("goal_text") or facts.get("goal_type") or "General fitness")


def _end_date_from(facts: dict[str, Any], start: date) -> date:
    """Race day if the interview found one, else a 12-week block."""
    raw = facts.get("race_date")
    if raw:
        try:
            parsed = date.fromisoformat(str(raw)[:10])
        except ValueError:
            parsed = start + timedelta(weeks=12)
        # A race already behind us is a typo, not a plan — fall back.
        return parsed if parsed > start else start + timedelta(weeks=12)
    return start + timedelta(weeks=12)


@router.post("/chat/generate", response_model=GenerateResponse)
def generate_from_chat(req: GenerateFromChatRequest) -> GenerateResponse:
    """Turn a finished intake interview into a plan."""
    from coach.llm import generate_plan

    end_date = req.end_date or _end_date_from(req.facts, req.start_date)
    if end_date <= req.start_date:
        raise HTTPException(400, "End date must be after the start date.")

    current_km = req.start_volume_km or req.facts.get("current_weekly_km")

    try:
        result = generate_plan(
            goal_text=req.goal_text or _goal_text_from(req.facts),
            start_date=req.start_date,
            end_date=end_date,
            start_volume_km=float(current_km) if current_km else 25.0,
            peak_volume_km=req.peak_volume_km,
            taper_weeks=req.taper_weeks,
            intake=req.facts,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e)) from e

    with session() as s:
        plan = s.get(Plan, result.plan_id)
        # Keep the interview with the plan so a later edit knows why the
        # plan looks the way it does.
        plan.structure = {**(plan.structure or {}), "intake": req.facts}
        rows = s.execute(
            select(ScheduledWorkout)
            .where(ScheduledWorkout.plan_id == result.plan_id)
            .order_by(ScheduledWorkout.date)
        ).scalars().all()
        return GenerateResponse(
            plan=_build_detail(plan, rows),
            model_used=result.model_used,
        )
