"""Tests for coach.plan_io export/import."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import coach.db as coach_db
from coach.models import Base, Plan, ScheduledWorkout
from coach.plan_io import export_plan, import_plan, validate_plan_dict


@pytest.fixture
def memory_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(coach_db, "_engine", engine)
    monkeypatch.setattr(coach_db, "_SessionLocal", SessionLocal)
    return SessionLocal


_PLAN = {
    "name": "Test plan",
    "goal_text": "build base",
    "start_date": "2026-05-04",
    "end_date": "2026-05-18",
    "weekly_structure": [
        {
            "week_number": 1,
            "theme": "Base",
            "target_volume_km": 30,
            "workouts": [
                {
                    "date": "2026-05-04",
                    "sport": "running",
                    "primitive_type": "easy_run",
                    "primitive_params": {"duration_min": 45},
                    "title": "Easy 45",
                    "description": "aerobic",
                },
                {
                    "date": "2026-05-06",
                    "sport": "running",
                    "primitive_type": "tempo_run",
                    "primitive_params": {"tempo_min": 20},
                    "title": "Tempo 20",
                    "description": "threshold",
                },
            ],
        },
        {
            "week_number": 2,
            "theme": "Build",
            "target_volume_km": 33,
            "workouts": [
                {
                    "date": "2026-05-11",
                    "sport": "running",
                    "primitive_type": "easy_run",
                    "primitive_params": {"duration_min": 50},
                    "title": "Easy 50",
                },
            ],
        },
    ],
}


# ----------------------------------------------------------------- import


def test_import_creates_plan(memory_db):
    pid, n = import_plan(_PLAN)
    assert n == 3
    with memory_db() as s:
        plan = s.get(Plan, pid)
        assert plan.name == "Test plan"
        assert plan.start_date == date(2026, 5, 4)
        assert plan.structure["weeks"][0]["theme"] == "Base"
        rows = s.query(ScheduledWorkout).filter_by(plan_id=pid).all()
        assert len(rows) == 3
        assert {r.week_number for r in rows} == {1, 2}


def test_import_overwrite_replaces_workouts(memory_db):
    pid, _ = import_plan(_PLAN)

    smaller = {
        **_PLAN,
        "name": "Smaller plan",
        "weekly_structure": [{
            "week_number": 1,
            "theme": "Base",
            "target_volume_km": 25,
            "workouts": [{
                "date": "2026-05-04",
                "sport": "running",
                "primitive_type": "easy_run",
                "primitive_params": {"duration_min": 30},
                "title": "Easy 30",
            }],
        }],
    }
    new_id, n = import_plan(smaller, plan_id_to_overwrite=pid)
    assert new_id == pid
    assert n == 1

    with memory_db() as s:
        plan = s.get(Plan, pid)
        assert plan.name == "Smaller plan"
        assert plan.version == 2
        rows = s.query(ScheduledWorkout).filter_by(plan_id=pid).all()
        assert len(rows) == 1


def test_import_overwrite_refuses_uploaded(memory_db):
    pid, _ = import_plan(_PLAN)
    with memory_db() as s:
        first = s.query(ScheduledWorkout).filter_by(plan_id=pid).first()
        first.status = "uploaded"
        first.garmin_workout_id = 123
        s.commit()

    with pytest.raises(ValueError, match="uploaded"):
        import_plan(_PLAN, plan_id_to_overwrite=pid)


def test_import_rejects_bad_primitive(memory_db):
    bad = {**_PLAN, "weekly_structure": [{
        "week_number": 1,
        "workouts": [{
            "date": "2026-05-04",
            "sport": "running",
            "primitive_type": "moonshot_run",
            "primitive_params": {},
            "title": "??",
        }],
    }]}
    with pytest.raises(ValueError, match="unknown primitive_type"):
        import_plan(bad)
    with memory_db() as s:
        assert s.query(Plan).count() == 0  # rolled back


def test_import_requires_top_level_keys(memory_db):
    bad = {k: v for k, v in _PLAN.items() if k != "goal_text"}
    with pytest.raises(ValueError, match="goal_text"):
        import_plan(bad)


# ----------------------------------------------------------------- export


def test_export_roundtrips(memory_db):
    """export(import(P)) should produce a structurally equivalent dict."""
    pid, _ = import_plan(_PLAN)
    out = export_plan(pid)

    assert out["name"] == _PLAN["name"]
    assert out["start_date"] == _PLAN["start_date"]
    assert len(out["weekly_structure"]) == 2

    # workouts preserved; ordering by date
    week1 = out["weekly_structure"][0]
    assert week1["theme"] == "Base"
    assert week1["target_volume_km"] == 30
    assert [w["primitive_type"] for w in week1["workouts"]] == [
        "easy_run", "tempo_run",
    ]


def test_export_then_reimport_overwrites_cleanly(memory_db):
    pid, _ = import_plan(_PLAN)
    dumped = export_plan(pid)
    new_id, n = import_plan(dumped, plan_id_to_overwrite=pid)
    assert new_id == pid
    assert n == 3


def test_export_unknown_plan_raises(memory_db):
    with pytest.raises(ValueError, match="not found"):
        export_plan(9999)


# ------------------------------------------------------------ validation


def test_validate_plan_dict_passes_valid():
    validate_plan_dict(_PLAN)


def test_validate_plan_dict_missing_keys():
    with pytest.raises(ValueError, match="name"):
        validate_plan_dict({"weekly_structure": []})


def test_validate_plan_dict_empty_structure():
    with pytest.raises(ValueError, match="non-empty"):
        validate_plan_dict({"name": "x", "weekly_structure": []})
