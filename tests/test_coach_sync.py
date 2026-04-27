"""Tests for coach.sync — uses an in-memory DB and a fake Garmin client."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import coach.db as coach_db
from coach.models import Base, Plan, ScheduledWorkout
from coach.sync import push_plan, unpush_plan


class FakeGarmin:
    """Minimal stand-in for garminconnect.Garmin used by sync."""

    def __init__(
        self,
        fail_on_upload_n: int | None = None,
        fail_on_delete_n: int | None = None,
    ):
        self._next_workout_id = 1000
        self._next_schedule_id = 5000
        self.uploads: list[dict[str, Any]] = []
        self.schedules: list[tuple[int, str]] = []
        self.deleted_workouts: list[int] = []
        self.unscheduled: list[int] = []
        self._fail_on_upload = fail_on_upload_n
        self._fail_on_delete = fail_on_delete_n

    def upload_workout(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.uploads.append(payload)
        if (
            self._fail_on_upload is not None
            and len(self.uploads) == self._fail_on_upload
        ):
            raise RuntimeError("simulated upload failure")
        wid = self._next_workout_id
        self._next_workout_id += 1
        return {"workoutId": wid}

    def schedule_workout(self, workout_id: int, date_str: str) -> dict[str, Any]:
        sid = self._next_schedule_id
        self._next_schedule_id += 1
        self.schedules.append((workout_id, date_str))
        return {"workoutScheduleId": sid}

    def unschedule_workout(self, schedule_id: int) -> dict[str, Any]:
        self.unscheduled.append(schedule_id)
        return {}

    def delete_workout(self, workout_id: int) -> dict[str, Any]:
        self.deleted_workouts.append(workout_id)
        if (
            self._fail_on_delete is not None
            and len(self.deleted_workouts) == self._fail_on_delete
        ):
            raise RuntimeError("simulated delete failure")
        return {}


@pytest.fixture
def memory_db(monkeypatch):
    """Wire coach.db to an in-memory SQLite for test isolation."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    monkeypatch.setattr(coach_db, "_engine", engine)
    monkeypatch.setattr(coach_db, "_SessionLocal", SessionLocal)
    yield SessionLocal


def _seed_plan(SessionLocal) -> int:
    with SessionLocal() as s:
        plan = Plan(
            name="Test plan",
            goal_text="test",
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 18),
        )
        s.add(plan)
        s.flush()
        s.add_all([
            ScheduledWorkout(
                plan_id=plan.id,
                date=date(2026, 5, 4),
                sport="running",
                title="Easy 30",
                primitive_type="easy_run",
                primitive_params={"duration_min": 30},
            ),
            ScheduledWorkout(
                plan_id=plan.id,
                date=date(2026, 5, 6),
                sport="running",
                title="Tempo",
                primitive_type="tempo_run",
                primitive_params={"tempo_min": 25},
            ),
            ScheduledWorkout(
                plan_id=plan.id,
                date=date(2026, 5, 8),
                sport="strength",
                title="Lift",
                primitive_type="strength_session",
                primitive_params={
                    "duration_min": 45,
                    "exercises": [{"name": "Squat", "sets": 3, "reps": "5"}],
                },
            ),
        ])
        s.commit()
        return plan.id


def test_push_plan_uploads_and_schedules_all(memory_db):
    plan_id = _seed_plan(memory_db)
    api = FakeGarmin()
    result = push_plan(plan_id, api)

    assert result.uploaded == 3
    assert result.skipped == 0
    assert result.failed == []
    assert len(api.uploads) == 3
    assert len(api.schedules) == 3

    # Every upload payload has the right shape
    assert api.uploads[0]["workoutName"] == "Easy 30"
    assert api.uploads[2]["sportType"]["sportTypeKey"] == "strength_training"

    # DB rows updated
    with memory_db() as s:
        rows = s.query(ScheduledWorkout).order_by(ScheduledWorkout.date).all()
        for r in rows:
            assert r.status == "uploaded"
            assert r.garmin_workout_id is not None
            assert r.garmin_schedule_id is not None


def test_push_plan_skips_already_uploaded(memory_db):
    plan_id = _seed_plan(memory_db)
    with memory_db() as s:
        first = s.query(ScheduledWorkout).first()
        first.status = "uploaded"
        first.garmin_workout_id = 999
        s.commit()

    api = FakeGarmin()
    result = push_plan(plan_id, api)

    assert result.uploaded == 2
    assert result.skipped == 1
    assert len(api.uploads) == 2  # the pre-uploaded one not re-sent


def test_push_plan_continues_after_individual_failure(memory_db):
    plan_id = _seed_plan(memory_db)
    api = FakeGarmin(fail_on_upload_n=2)  # 2nd upload throws
    result = push_plan(plan_id, api)

    assert result.uploaded == 2  # 1st and 3rd succeed
    assert len(result.failed) == 1
    assert "simulated" in result.failed[0][1]


def test_push_plan_unknown_plan_raises(memory_db):
    with pytest.raises(ValueError, match="not found"):
        push_plan(9999, FakeGarmin())


# ---------------------------------------------------------------- unpush


def test_unpush_plan_reverses_a_push(memory_db):
    plan_id = _seed_plan(memory_db)
    api = FakeGarmin()
    push_plan(plan_id, api)
    assert all(s == "uploaded" for s in _statuses(memory_db, plan_id))

    result = unpush_plan(plan_id, api)
    assert result.removed == 3
    assert result.skipped == 0
    assert result.failed == []

    # All workout templates deleted, all schedules removed.
    assert len(api.deleted_workouts) == 3
    assert len(api.unscheduled) == 3

    # DB rows reverted.
    with memory_db() as s:
        rows = s.query(ScheduledWorkout).all()
        for r in rows:
            assert r.status == "planned"
            assert r.garmin_workout_id is None
            assert r.garmin_schedule_id is None


def test_unpush_plan_skips_planned_rows(memory_db):
    plan_id = _seed_plan(memory_db)  # all "planned"
    api = FakeGarmin()
    result = unpush_plan(plan_id, api)
    assert result.removed == 0
    assert result.skipped == 3
    assert api.deleted_workouts == []


def test_unpush_plan_continues_after_failure(memory_db):
    plan_id = _seed_plan(memory_db)
    api = FakeGarmin(fail_on_delete_n=2)
    push_plan(plan_id, api)
    result = unpush_plan(plan_id, api)
    assert result.removed == 2
    assert len(result.failed) == 1


def test_unpush_then_push_again_works(memory_db):
    """Round-trip: push, unpush, push again — confirms re-push works."""
    plan_id = _seed_plan(memory_db)
    api = FakeGarmin()
    push_plan(plan_id, api)
    unpush_plan(plan_id, api)
    second = push_plan(plan_id, api)
    assert second.uploaded == 3
    assert len(api.uploads) == 6  # 3 + 3


def _statuses(SessionLocal, plan_id: int) -> list[str]:
    with SessionLocal() as s:
        rows = s.query(ScheduledWorkout).filter_by(plan_id=plan_id).all()
        return [r.status for r in rows]
