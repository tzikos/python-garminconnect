"""Tests for coach.tools."""

from __future__ import annotations

from datetime import date

import pytest

from coach.tools import (
    Warning,
    compute_hr_zones,
    compute_pace_zones,
    format_pace,
    interference_check,
    place_in_calendar,
    validate_workout,
    weekly_volume_progression,
)


# ---------------------------------------------------------------- pacing


def test_compute_pace_zones_basic_shape():
    # 22:30 5k = 1350s
    z = compute_pace_zones(1350)
    assert set(z) == {"easy", "marathon", "threshold", "interval", "repetition"}
    # Each zone has min < max (faster < slower in seconds)
    for zone in z.values():
        assert zone["min_per_km"] <= zone["max_per_km"]
    # Easy is slower than threshold which is slower than interval
    assert z["easy"]["min_per_km"] > z["threshold"]["min_per_km"]
    assert z["threshold"]["min_per_km"] > z["interval"]["min_per_km"]


def test_compute_pace_zones_22_30():
    z = compute_pace_zones(22 * 60 + 30)
    # 5k pace = 270 s/km. Easy ≈ 1.25-1.40 → 338-378 s/km (5:38 - 6:18).
    assert 330 <= z["easy"]["min_per_km"] <= 345
    assert 370 <= z["easy"]["max_per_km"] <= 385
    # Threshold ≈ 1.04-1.07 → 281-289 s/km
    assert 278 <= z["threshold"]["min_per_km"] <= 284
    assert 286 <= z["threshold"]["max_per_km"] <= 292


def test_compute_pace_zones_rejects_zero():
    with pytest.raises(ValueError):
        compute_pace_zones(0)


def test_format_pace():
    assert format_pace(330) == "5:30"
    assert format_pace(285) == "4:45"
    assert format_pace(60) == "1:00"


def test_compute_hr_zones_with_threshold():
    z = compute_hr_zones(threshold_hr=170)
    assert set(z) == {"Z1", "Z2", "Z3", "Z4", "Z5"}
    assert z["Z4"]["min_bpm"] == round(170 * 0.94)
    assert z["Z4"]["max_bpm"] == round(170 * 0.99)


def test_compute_hr_zones_with_max_only():
    z = compute_hr_zones(max_hr=190)
    assert z["Z2"]["min_bpm"] == round(190 * 0.60)


def test_compute_hr_zones_requires_input():
    with pytest.raises(ValueError):
        compute_hr_zones()


# ---------------------------------------------------------------- progression


def test_weekly_volume_progression_length():
    v = weekly_volume_progression(start_km=30, peak_km=60, weeks=12)
    assert len(v) == 12


def test_weekly_volume_progression_taper_descends_to_50pct():
    v = weekly_volume_progression(start_km=30, peak_km=60, weeks=12, taper_weeks=2)
    peak = max(v)
    # last week ~= 50% of peak
    assert v[-1] == round(peak * 0.5, 1)
    # second to last ~= 70% of peak
    assert v[-2] == round(peak * 0.7, 1)


def test_weekly_volume_progression_has_deload():
    v = weekly_volume_progression(start_km=30, peak_km=60, weeks=12, taper_weeks=2)
    # Build phase = first 10. Deload should appear at index 3 (week 4)
    # and 7 (week 8). Each is 70% of the previous progression week.
    assert v[3] < v[2]
    assert v[7] < v[6]
    # Pre-deload should be lower than post-deload comeback (ramp continues)
    assert v[6] > v[5]


def test_weekly_volume_progression_validates_inputs():
    with pytest.raises(ValueError):
        weekly_volume_progression(30, 60, weeks=2)
    with pytest.raises(ValueError):
        weekly_volume_progression(60, 30, weeks=8)
    with pytest.raises(ValueError):
        weekly_volume_progression(30, 60, weeks=8, taper_weeks=8)


# ---------------------------------------------------------------- scheduling


def test_place_in_calendar_respects_preferences():
    week = date(2026, 5, 4)  # Monday
    workouts = [
        {"sport": "running", "primitive_type": "easy_run"},
        {"sport": "strength", "primitive_type": "strength_session"},
        {"sport": "running", "primitive_type": "long_run"},
    ]
    placed = place_in_calendar(
        workouts=workouts,
        preferred_days={"running": [0, 2, 6], "strength": [1, 3]},
        week_start=week,
    )
    assert len(placed) == 3
    by_sport = {w["sport"]: d for d, w in placed}
    # Running workouts go to Mon (0) and Wed (2) or Sun (6); strength to Tue (1)
    assert by_sport["strength"].weekday() == 1


def test_place_in_calendar_falls_back_when_preferred_full():
    week = date(2026, 5, 4)
    workouts = [
        {"sport": "running"},
        {"sport": "running"},
        {"sport": "running"},  # 3 runs but only 2 preferred days
    ]
    placed = place_in_calendar(
        workouts=workouts,
        preferred_days={"running": [0, 2]},
        week_start=week,
    )
    dates = [d for d, _ in placed]
    assert len(dates) == 3
    assert len(set(dates)) == 3  # all unique


def test_place_in_calendar_honors_blackouts():
    week = date(2026, 5, 4)
    workouts = [{"sport": "running"}]
    placed = place_in_calendar(
        workouts=workouts,
        preferred_days={"running": [0]},  # Monday
        week_start=week,
        blackout_dates=[date(2026, 5, 4)],  # block that Monday
    )
    assert placed[0][0] != date(2026, 5, 4)


def test_place_in_calendar_rejects_overflow():
    week = date(2026, 5, 4)
    too_many = [{"sport": "running"} for _ in range(8)]
    with pytest.raises(ValueError):
        place_in_calendar(too_many, {"running": list(range(7))}, week)


def test_place_in_calendar_requires_monday_start():
    with pytest.raises(ValueError):
        place_in_calendar([], {}, date(2026, 5, 6))  # Wednesday


# ---------------------------------------------------------------- checks


def test_validate_workout_easy_run_too_long():
    w = validate_workout("easy_run", {"duration_min": 300})
    assert any(x.severity == "warn" for x in w)


def test_validate_workout_high_rep_intervals():
    w = validate_workout(
        "interval_session", {"reps": 20, "work_min": 3, "recovery_min": 2}
    )
    assert any("20 reps" in x.message for x in w)


def test_validate_workout_strength_too_many():
    exercises = [{"name": f"ex{i}", "sets": 3, "reps": 5} for i in range(15)]
    w = validate_workout("strength_session", {"exercises": exercises})
    assert any(x.severity == "warn" for x in w)


def test_validate_workout_clean_returns_empty():
    assert validate_workout("easy_run", {"duration_min": 45}) == []


def test_interference_check_back_to_back_hard():
    sched = [
        {"date": date(2026, 5, 4), "sport": "running", "primitive_type": "tempo_run"},
        {"date": date(2026, 5, 5), "sport": "running", "primitive_type": "interval_session"},
    ]
    warns = interference_check(sched)
    assert any("back-to-back" in w.message for w in warns)


def test_interference_check_hard_before_long_run():
    sched = [
        {"date": date(2026, 5, 8), "sport": "running", "primitive_type": "interval_session"},
        {"date": date(2026, 5, 9), "sport": "running", "primitive_type": "long_run"},
    ]
    warns = interference_check(sched)
    assert any("long run" in w.message for w in warns)


def test_interference_check_too_many_hard_sessions():
    sched = [
        {"date": date(2026, 5, 4), "sport": "running", "primitive_type": "tempo_run"},
        {"date": date(2026, 5, 6), "sport": "running", "primitive_type": "interval_session"},
        {"date": date(2026, 5, 8), "sport": "running", "primitive_type": "tempo_run"},
        {"date": date(2026, 5, 10), "sport": "running", "primitive_type": "interval_session"},
    ]
    warns = interference_check(sched)
    assert any("hard sessions this week" in w.message for w in warns)


def test_interference_check_clean_week():
    sched = [
        {"date": date(2026, 5, 4), "sport": "running", "primitive_type": "easy_run"},
        {"date": date(2026, 5, 6), "sport": "running", "primitive_type": "tempo_run"},
        {"date": date(2026, 5, 8), "sport": "strength", "primitive_type": "strength_session"},
        {"date": date(2026, 5, 10), "sport": "running", "primitive_type": "long_run"},
    ]
    warns = interference_check(sched)
    assert warns == []


def test_warning_dataclass_default_dates():
    w = Warning("info", "hi")
    assert w.dates == []
