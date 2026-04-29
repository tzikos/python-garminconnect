"""Tests for the LLM planner with stubbed chat responses."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import coach.db as coach_db
from coach.llm.openrouter import ChatResult
from coach.llm.planner import _parse_plan_json, generate_plan
from coach.llm.prompts import build_user_prompt
from coach.models import Base, Plan, ScheduledWorkout, UserProfile


@pytest.fixture
def memory_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(coach_db, "_engine", engine)
    monkeypatch.setattr(coach_db, "_SessionLocal", SessionLocal)
    return SessionLocal


def _seed_profile(SessionLocal):
    with SessionLocal() as s:
        s.add(UserProfile(
            id=1,
            name="Tzikos",
            recent_5k_seconds=22 * 60 + 30,
            threshold_hr=170,
            preferred_days={"running": [0, 2, 5], "strength": [3]},
            weekly_hours_target=6.0,
            notes="No injuries.",
        ))
        s.commit()


# ----------------------------------------------------------- prompt builder


def test_build_user_prompt_includes_paces_and_volume():
    p = build_user_prompt(
        goal_text="Sub-1:45 half marathon",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 7, 13),
        profile={
            "name": "Tzikos",
            "recent_5k_seconds": 22 * 60 + 30,
            "threshold_hr": 170,
            "preferred_days": {"running": [0, 2, 5]},
            "weekly_hours_target": 6.0,
        },
    )
    assert "Sub-1:45 half marathon" in p
    assert "Tzikos" in p
    assert "easy " in p  # pace label
    assert "Z4" in p  # HR zones rendered
    assert "Week 1:" in p  # volume progression block
    assert "running=days" in p  # preferred days


# --------------------------------------------------------------- json parsing


def test_parse_plan_json_bare():
    plan = _parse_plan_json('{"name": "x", "weekly_structure": []}')
    assert plan["name"] == "x"


def test_parse_plan_json_fenced():
    raw = "Sure, here's the plan:\n\n```json\n{\"name\": \"x\", \"weekly_structure\": []}\n```"
    plan = _parse_plan_json(raw)
    assert plan["name"] == "x"


def test_parse_plan_json_with_prose():
    raw = 'Here you go: {"name": "x", "weekly_structure": []} hope this helps!'
    plan = _parse_plan_json(raw)
    assert plan["name"] == "x"


def test_parse_plan_json_rejects_garbage():
    with pytest.raises(ValueError):
        _parse_plan_json("no json here at all")


# ------------------------------------------------------------ generate_plan


def _stub_response(payload: dict) -> ChatResult:
    return ChatResult(content=json.dumps(payload), model_used="stub")


_VALID_PLAN = {
    "name": "Sub-1:45 HM Build",
    "weekly_structure": [
        {
            "week_number": 1,
            "theme": "Base",
            "target_volume_km": 35,
            "workouts": [
                {
                    "date": "2026-05-04",
                    "sport": "running",
                    "primitive_type": "easy_run",
                    "primitive_params": {"duration_min": 45},
                    "title": "Easy 45min",
                    "description": "Aerobic base",
                    "why": "Build aerobic capacity",
                },
                {
                    "date": "2026-05-06",
                    "sport": "running",
                    "primitive_type": "tempo_run",
                    "primitive_params": {"tempo_min": 20},
                    "title": "Tempo 20",
                    "description": "",
                    "why": "Threshold work",
                },
                {
                    "date": "2026-05-07",
                    "sport": "strength",
                    "primitive_type": "strength_session",
                    "primitive_params": {
                        "duration_min": 45,
                        "exercises": [
                            {"name": "Squat", "sets": 4, "reps": "5"},
                            {"name": "Bench", "sets": 4, "reps": "5"},
                        ],
                    },
                    "title": "Lift A",
                    "description": "",
                    "why": "Heavy lower + upper",
                },
            ],
        }
    ],
}


def test_generate_plan_creates_plan_and_workouts(memory_db):
    _seed_profile(memory_db)
    result = generate_plan(
        goal_text="Sub-1:45 HM",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 5, 11),
        chat_fn=lambda _msgs: _stub_response(_VALID_PLAN),
    )
    assert result.workouts_created == 3
    assert result.plan_name == "Sub-1:45 HM Build"
    assert result.model_used == "stub"

    with memory_db() as s:
        plans = s.query(Plan).all()
        assert len(plans) == 1
        rows = s.query(ScheduledWorkout).order_by(ScheduledWorkout.date).all()
        assert [r.primitive_type for r in rows] == [
            "easy_run", "tempo_run", "strength_session"
        ]
        assert all(r.status == "planned" for r in rows)


def test_generate_plan_rolls_back_on_invalid_primitive(memory_db):
    _seed_profile(memory_db)
    bad = {
        "name": "Bad plan",
        "weekly_structure": [
            {
                "week_number": 1,
                "workouts": [
                    {
                        "date": "2026-05-04",
                        "sport": "running",
                        "primitive_type": "moonshot_run",
                        "primitive_params": {},
                        "title": "??",
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="unknown primitive_type"):
        generate_plan(
            goal_text="x",
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 11),
            chat_fn=lambda _msgs: _stub_response(bad),
        )

    with memory_db() as s:
        assert s.query(Plan).count() == 0
        assert s.query(ScheduledWorkout).count() == 0


def test_generate_plan_rolls_back_on_invalid_params(memory_db):
    _seed_profile(memory_db)
    bad = {
        "name": "Bad plan",
        "weekly_structure": [
            {
                "week_number": 1,
                "workouts": [
                    {
                        "date": "2026-05-04",
                        "sport": "running",
                        "primitive_type": "interval_session",
                        "primitive_params": {
                            "reps": 0,  # primitive raises ValueError
                            "work_min": 3,
                            "recovery_min": 2,
                        },
                        "title": "Bad intervals",
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="primitive rejected params"):
        generate_plan(
            goal_text="x",
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 11),
            chat_fn=lambda _msgs: _stub_response(bad),
        )

    with memory_db() as s:
        assert s.query(Plan).count() == 0


def test_generate_plan_collects_interference_warnings(memory_db):
    _seed_profile(memory_db)
    risky = {
        "name": "Risky plan",
        "weekly_structure": [
            {
                "week_number": 1,
                "workouts": [
                    {
                        "date": "2026-05-04",
                        "sport": "running",
                        "primitive_type": "tempo_run",
                        "primitive_params": {"tempo_min": 20},
                        "title": "Tempo",
                    },
                    {
                        "date": "2026-05-05",
                        "sport": "running",
                        "primitive_type": "interval_session",
                        "primitive_params": {
                            "reps": 5, "work_min": 3, "recovery_min": 2,
                        },
                        "title": "Intervals",
                    },
                ],
            }
        ],
    }
    result = generate_plan(
        goal_text="x",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 5, 11),
        chat_fn=lambda _msgs: _stub_response(risky),
    )
    assert any("back-to-back" in w.message for w in result.warnings)


def test_generate_plan_drops_workouts_before_actual_start(memory_db):
    """Mid-week start: LLM plans Mon->Sun; we drop workouts < actual start."""
    _seed_profile(memory_db)
    full_week_plan = {
        "name": "Mid-week test",
        "weekly_structure": [
            {
                "week_number": 1,
                "theme": "Base",
                "workouts": [
                    # These two should be dropped (before Wed 2026-04-29)
                    {
                        "date": "2026-04-27", "sport": "running",
                        "primitive_type": "easy_run",
                        "primitive_params": {"duration_min": 30},
                        "title": "Mon easy",
                    },
                    {
                        "date": "2026-04-28", "sport": "strength",
                        "primitive_type": "strength_session",
                        "primitive_params": {
                            "duration_min": 45,
                            "exercises": [{"name": "Squat", "sets": 3, "reps": "5"}],
                        },
                        "title": "Tue lift",
                    },
                    # These three should be kept
                    {
                        "date": "2026-04-29", "sport": "running",
                        "primitive_type": "tempo_run",
                        "primitive_params": {"tempo_min": 20},
                        "title": "Wed tempo",
                    },
                    {
                        "date": "2026-05-01", "sport": "running",
                        "primitive_type": "easy_run",
                        "primitive_params": {"duration_min": 40},
                        "title": "Fri easy",
                    },
                    {
                        "date": "2026-05-03", "sport": "running",
                        "primitive_type": "long_run",
                        "primitive_params": {"duration_min": 75},
                        "title": "Sun long",
                    },
                ],
            }
        ],
    }
    result = generate_plan(
        goal_text="x",
        start_date=date(2026, 4, 29),  # Wednesday
        end_date=date(2026, 5, 3),
        chat_fn=lambda _msgs: _stub_response(full_week_plan),
    )
    assert result.workouts_created == 3

    with memory_db() as s:
        rows = s.query(ScheduledWorkout).order_by(ScheduledWorkout.date).all()
        assert [r.date for r in rows] == [
            date(2026, 4, 29), date(2026, 5, 1), date(2026, 5, 3),
        ]


def test_generate_plan_requires_profile(memory_db):
    # No profile seeded.
    with pytest.raises(RuntimeError, match="No profile"):
        generate_plan(
            goal_text="x",
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 11),
            chat_fn=lambda _msgs: _stub_response(_VALID_PLAN),
        )
