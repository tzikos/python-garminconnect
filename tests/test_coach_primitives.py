"""Tests for coach.primitives — verify primitives produce well-formed
Garmin workout JSON the existing client can consume."""

from __future__ import annotations

import pytest

from coach.primitives import (
    build,
    easy_run,
    interval_session,
    long_run,
    strength_session,
    tempo_run,
)
from garminconnect.workout import BaseWorkout, RunningWorkout


# ---------------------------------------------------------------- easy_run


def test_easy_run_returns_running_workout():
    w = easy_run(duration_min=30)
    assert isinstance(w, RunningWorkout)
    assert w.estimatedDurationInSecs == 1800
    assert w.workoutName == "Easy 30min"
    assert len(w.workoutSegments) == 1
    seg = w.workoutSegments[0]
    assert seg.sportType["sportTypeKey"] == "running"
    assert len(seg.workoutSteps) == 1


def test_easy_run_no_pace_target_by_default():
    step = easy_run(duration_min=30).workoutSegments[0].workoutSteps[0]
    # No-target marker is set by the existing helper; pace.zone shouldn't be
    assert step.targetType.get("workoutTargetTypeKey") != "pace.zone"


def test_easy_run_with_pace_target_sets_pace_zone():
    """5:30-6:00/km == 330-360 sec/km. m/s: 1000/330=3.0303, 1000/360=2.7778."""
    payload = easy_run(
        duration_min=45,
        target_pace_min_per_km=330,  # faster
        target_pace_max_per_km=360,  # slower
    ).to_dict()
    step = payload["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    # one = high speed (fast end), two = low speed (slow end)
    assert abs(step["targetValueOne"] - 3.0303) < 0.001
    assert abs(step["targetValueTwo"] - 2.7778) < 0.001


def test_pace_target_with_only_one_value_widens_range():
    """Single-value target is broadened by ±5s so the watch doesn't constantly beep."""
    step = easy_run(
        duration_min=30, target_pace_min_per_km=330
    ).workoutSegments[0].workoutSteps[0]
    # one = fast end (~325s/km), two = slow end (~335s/km)
    assert step.targetValueOne == round(1000 / 325, 4)
    assert step.targetValueTwo == round(1000 / 335, 4)


def test_tempo_run_pace_only_on_tempo_block():
    w = tempo_run(
        tempo_min=20,
        tempo_pace_min_per_km=270,
        tempo_pace_max_per_km=285,
    )
    steps = w.workoutSegments[0].workoutSteps
    assert steps[0].targetType.get("workoutTargetTypeKey") != "pace.zone"  # warmup
    assert steps[1].targetType["workoutTargetTypeKey"] == "pace.zone"      # tempo
    assert steps[2].targetType.get("workoutTargetTypeKey") != "pace.zone"  # cooldown


def test_interval_session_separate_paces_for_work_and_recovery():
    w = interval_session(
        reps=5, work_min=3, recovery_min=2,
        work_pace_min_per_km=240, work_pace_max_per_km=255,
        recovery_pace_min_per_km=350, recovery_pace_max_per_km=380,
    )
    steps = w.workoutSegments[0].workoutSteps
    repeat = steps[1]
    work, recovery = repeat.workoutSteps
    assert work.targetType["workoutTargetTypeKey"] == "pace.zone"
    assert recovery.targetType["workoutTargetTypeKey"] == "pace.zone"
    # work is faster -> higher speed (targetValueOne is the fast-end bound)
    assert work.targetValueOne > recovery.targetValueOne


def test_easy_run_to_dict_is_upload_ready():
    payload = easy_run(duration_min=45, description="zone 2 only").to_dict()
    assert payload["workoutName"] == "Easy 45min"
    assert payload["description"] == "zone 2 only"
    assert payload["sportType"]["sportTypeKey"] == "running"
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["endConditionValue"] == 45 * 60


# ---------------------------------------------------------------- long_run


def test_long_run_default_name_distinguishes_from_easy():
    assert long_run(duration_min=90).workoutName == "Long 90min"


# ---------------------------------------------------------------- tempo_run


def test_tempo_run_has_three_steps_in_order():
    w = tempo_run(tempo_min=30, warmup_min=15, cooldown_min=10)
    steps = w.workoutSegments[0].workoutSteps
    assert len(steps) == 3
    assert steps[0].stepType["stepTypeKey"] == "warmup"
    assert steps[1].stepType["stepTypeKey"] == "interval"
    assert steps[2].stepType["stepTypeKey"] == "cooldown"
    assert w.estimatedDurationInSecs == (15 + 30 + 10) * 60


# ---------------------------------------------------------------- intervals


def test_interval_session_uses_repeat_group():
    w = interval_session(reps=5, work_min=3, recovery_min=2)
    steps = w.workoutSegments[0].workoutSteps
    assert len(steps) == 3  # warmup, repeat, cooldown
    repeat = steps[1]
    assert repeat.stepType["stepTypeKey"] == "repeat"
    assert repeat.numberOfIterations == 5
    inner = repeat.workoutSteps
    assert inner[0].stepType["stepTypeKey"] == "interval"
    assert inner[1].stepType["stepTypeKey"] == "recovery"


def test_interval_session_total_duration_correct():
    w = interval_session(
        reps=4, work_min=4, recovery_min=2, warmup_min=15, cooldown_min=10
    )
    expected = (15 + 4 * (4 + 2) + 10) * 60
    assert w.estimatedDurationInSecs == expected


def test_interval_session_rejects_zero_reps():
    with pytest.raises(ValueError):
        interval_session(reps=0, work_min=3, recovery_min=2)


# ---------------------------------------------------------------- strength


def test_strength_session_renders_exercises_in_description():
    w = strength_session(
        duration_min=60,
        exercises=[
            {"name": "Back Squat", "sets": 4, "reps": "5", "weight": "100kg"},
            {"name": "Bench Press", "sets": 4, "reps": "6-8", "weight": "RPE 8"},
            {"name": "Pull-ups", "sets": 3, "reps": "AMRAP", "notes": "strict"},
        ],
        why="Heavy lower + upper push/pull. Focus on bar speed.",
    )
    assert isinstance(w, BaseWorkout)
    assert w.sportType["sportTypeKey"] == "strength_training"
    desc = w.description
    assert "Heavy lower" in desc
    assert "A) Back Squat - 4x5 @ 100kg" in desc
    assert "B) Bench Press - 4x6-8 @ RPE 8" in desc
    assert "C) Pull-ups - 3xAMRAP" in desc
    assert "(strict)" in desc


def test_strength_session_rejects_empty_exercises():
    with pytest.raises(ValueError):
        strength_session(duration_min=60, exercises=[])


def test_strength_session_to_dict_has_single_timer_step():
    payload = strength_session(
        duration_min=45,
        exercises=[{"name": "Deadlift", "sets": 3, "reps": "5"}],
    ).to_dict()
    assert payload["sportType"]["sportTypeKey"] == "strength_training"
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1
    assert steps[0]["endConditionValue"] == 45 * 60


# ---------------------------------------------------------------- registry


def test_registry_includes_all_primitives():
    from coach.primitives import PRIMITIVES

    assert set(PRIMITIVES) == {
        "easy_run",
        "long_run",
        "tempo_run",
        "interval_session",
        "strength_session",
    }


def test_registry_build_matches_direct_call():
    direct = easy_run(duration_min=20).to_dict()
    via_registry = build("easy_run", {"duration_min": 20}).to_dict()
    assert direct == via_registry


def test_registry_build_strength():
    via_registry = build(
        "strength_session",
        {
            "duration_min": 45,
            "exercises": [{"name": "Squat", "sets": 3, "reps": "5"}],
        },
    )
    assert via_registry.sportType["sportTypeKey"] == "strength_training"


def test_registry_unknown_primitive_raises():
    with pytest.raises(KeyError):
        build("does_not_exist", {})
