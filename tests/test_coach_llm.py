"""Tests for the LLM planner with stubbed chat responses."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import coach.db as coach_db
from coach.llm.openrouter import ChatResult
from coach.llm.planner import _aggressive_repair, _parse_plan_json, generate_plan
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
            "enabled_sports": ["running"],
        },
    )
    assert "Sub-1:45 half marathon" in p
    assert "Tzikos" in p
    assert "easy " in p  # pace label
    assert "Z4" in p  # HR zones rendered
    assert "Week 1:" in p  # volume progression block
    assert "running=days" in p  # preferred days
    assert "ENABLED SPORTS: running" in p


def test_build_user_prompt_multisport_includes_each_block():
    p = build_user_prompt(
        goal_text="Hybrid: HM + calisthenics",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 7, 13),
        profile={
            "name": "Tzikos",
            "enabled_sports": ["running", "calisthenics", "strength"],
            "sport_profiles": {
                "running": {"race_times": [{"distance_km": 5, "seconds": 1350}]},
                "calisthenics": {
                    "max_reps": {"pullups": 12, "dips": 18, "pushups": 35},
                    "max_holds": {"l_sit_seconds": 30},
                },
                "strength": {
                    "lifts_1rm": {"squat_kg": 120, "bench_kg": 90, "deadlift_kg": 140},
                    "training_age_years": 5,
                },
            },
        },
    )
    assert "RUNNING (enabled)" in p
    assert "CALISTHENICS (enabled)" in p
    assert "STRENGTH (enabled)" in p
    assert "5km 22:30" in p  # race time formatted
    assert "pull-ups 12" in p
    assert "Squat 120kg" in p
    assert "Training age: 5 years" in p


def test_build_user_prompt_omits_volume_when_running_disabled():
    p = build_user_prompt(
        goal_text="Pure strength block",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 7, 13),
        profile={
            "name": "x",
            "enabled_sports": ["strength"],
            "sport_profiles": {"strength": {"lifts_1rm": {"squat_kg": 100}}},
        },
    )
    assert "PRE-COMPUTED RUNNING VOLUME" not in p
    assert "STRENGTH (enabled)" in p


def test_build_user_prompt_handles_missing_benchmarks():
    """Calisthenics enabled but no benchmarks recorded yet."""
    p = build_user_prompt(
        goal_text="x",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 7, 13),
        profile={"name": "x", "enabled_sports": ["calisthenics"]},
    )
    assert "CALISTHENICS (enabled)" in p
    assert "no benchmarks" in p


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


# ---------------------------------------------------- truncation repair


def test_aggressive_repair_already_valid_returns_none():
    """Caller doesn't invoke repair when initial parse succeeds."""
    # _aggressive_repair is only called on parse failure; if the input is
    # already valid, the function still works on it (will balance trivially).
    assert _aggressive_repair('{"a": 1}') == {"a": 1}


def test_aggressive_repair_mid_string():
    """Cut mid-string: roll back to last complete object boundary."""
    truncated = (
        '{"weekly_structure": ['
        '{"workouts": [{"a": 1}, {"b": "incomplete'
    )
    parsed = _aggressive_repair(truncated)
    assert parsed is not None
    assert parsed["weekly_structure"][0]["workouts"] == [{"a": 1}]


def test_aggressive_repair_after_complete_object():
    """Cut right after a complete inner object + dangling comma."""
    truncated = (
        '{"weekly_structure": [{"workouts": [{"a": 1}, {"b": 2}],'
    )
    parsed = _aggressive_repair(truncated)
    assert parsed is not None
    assert len(parsed["weekly_structure"][0]["workouts"]) == 2


def test_aggressive_repair_skips_unparseable_cuts():
    """When the latest cut produces invalid JSON, fall back to earlier ones."""
    # Truncation creates a candidate that fails to parse (close bracket
    # mismatch); repair should try earlier cut positions until one works.
    truncated = '{"a": 1, "b": [1, 2, 3], "c": "broken'
    parsed = _aggressive_repair(truncated)
    assert parsed == {"a": 1, "b": [1, 2, 3]}


def test_parse_plan_json_strips_trailing_commas_in_arrays():
    raw = '{"a": [1, 2, 3,]}'
    parsed = _parse_plan_json(raw)
    assert parsed == {"a": [1, 2, 3]}


def test_parse_plan_json_strips_trailing_commas_in_objects():
    raw = '{"a": 1, "b": 2,}'
    parsed = _parse_plan_json(raw)
    assert parsed == {"a": 1, "b": 2}


def test_parse_plan_json_preserves_commas_inside_strings():
    raw = '{"a": "value, with comma,"}'
    parsed = _parse_plan_json(raw)
    assert parsed["a"] == "value, with comma,"


def test_parse_plan_json_handles_truncation_with_trailing_commas():
    """The real-world failure: response has trailing comma AND was cut off."""
    raw = (
        '{\n'
        '  "name": "Hybrid plan",\n'
        '  "weekly_structure": [\n'
        '    {"week_number": 1, "workouts": [\n'
        '      {"date": "2026-05-12", "sport": "calisthenics",\n'
        '       "primitive_type": "strength_session",\n'
        '       "primitive_params": {"duration_min": 45, "exercises": [\n'
        '         {"name": "Pull-Ups", "sets": 4, "reps": "6-8"},\n'
        '         {"name": "Dips", "sets": 4, "reps": "8-10"},\n'
        '         {"name": "Push-Ups", "sets": 3, "reps": "12-15"},\n'
        '       ]},\n'
        '       "title": "Cali A"},\n'
        '      {"date": "2026-05-14", "sport": "running",\n'
        '       "primitive_type": "easy_'
    )
    parsed = _parse_plan_json(raw)
    assert parsed["name"] == "Hybrid plan"
    workouts = parsed["weekly_structure"][0]["workouts"]
    assert len(workouts) == 1
    # exercises preserved despite the trailing comma in the source
    assert len(workouts[0]["primitive_params"]["exercises"]) == 3


def test_parse_plan_json_recovers_from_truncation():
    """The full _parse_plan_json path: truncation + repair + validate-able."""
    truncated = (
        '{\n'
        '  "name": "Half plan",\n'
        '  "weekly_structure": [\n'
        '    {"week_number": 1, "workouts": [\n'
        '      {"date": "2026-05-04", "sport": "running",\n'
        '       "primitive_type": "easy_run",\n'
        '       "primitive_params": {"duration_min": 30},\n'
        '       "title": "Easy 30"},\n'
        '      {"date": "2026-05-06", "sport": "running",\n'
        '       "primitive_type": "tem'
    )
    parsed = _parse_plan_json(truncated)
    assert parsed["name"] == "Half plan"
    assert len(parsed["weekly_structure"][0]["workouts"]) == 1
    assert parsed["weekly_structure"][0]["workouts"][0]["primitive_type"] == "easy_run"


def test_generate_plan_drops_incomplete_workouts_after_repair(memory_db):
    """Truncation lands inside a workout BEFORE its title is written.
    Repair recovers the prefix; the partial workout is dropped silently."""
    _seed_profile(memory_db)
    raw = (
        '{\n'
        '  "name": "Hybrid HM + cali",\n'
        '  "weekly_structure": [\n'
        '    {"week_number": 1, "workouts": [\n'
        '      {"date": "2026-05-04", "sport": "running",\n'
        '       "primitive_type": "easy_run",\n'
        '       "primitive_params": {"duration_min": 30},\n'
        '       "title": "Easy 30"},\n'
        '      {"date": "2026-05-05", "sport": "strength",\n'
        '       "primitive_type": "strength_session",\n'
        '       "primitive_params": {"duration_min": 45, "exercises": [\n'
        '         {"name": "Bench", "sets": 4, "reps": 5},\n'
        '         {"name": "Row", "sets": 4, "reps": 6},\n'
    )
    result = generate_plan(
        goal_text="x",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 5, 11),
        chat_fn=lambda _msgs: ChatResult(content=raw, model_used="stub"),
    )
    # Only the complete easy_run survives; the partial strength_session is
    # dropped because it lacks "title".
    assert result.workouts_created == 1


def test_generate_plan_recovers_from_truncated_response(memory_db):
    """End-to-end: truncated LLM output -> plan still materializes."""
    _seed_profile(memory_db)
    truncated_raw = (
        '{\n'
        '  "name": "Truncated plan",\n'
        '  "weekly_structure": [\n'
        '    {"week_number": 1, "theme": "Base", "workouts": [\n'
        '      {"date": "2026-05-04", "sport": "running",\n'
        '       "primitive_type": "easy_run",\n'
        '       "primitive_params": {"duration_min": 30},\n'
        '       "title": "Easy 30"},\n'
        '      {"date": "2026-05-06", "sport": "running",\n'
        '       "primitive_type": "tempo_run",\n'
        '       "primitive_params": {"tempo_min": 20},\n'
        '       "title": "Tempo"},\n'
        '      {"date": "2026-05-08", "sport": "running",\n'
        '       "primitive_type": "long_'
    )
    result = generate_plan(
        goal_text="x",
        start_date=date(2026, 5, 4),
        end_date=date(2026, 5, 11),
        chat_fn=lambda _msgs: ChatResult(content=truncated_raw, model_used="stub"),
    )
    assert result.workouts_created == 2  # only the two complete ones


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
