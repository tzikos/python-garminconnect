"""Running workout primitives.

Each primitive is a pure function: (params) -> garminconnect RunningWorkout.
Same function used at planning time (LLM picks it + params, params stored
in DB) and sync time (DB row -> RunningWorkout -> upload).

Optional pace targets per segment are supported. Paces are in sec/km
(smaller = faster, matching the convention used by `coach.tools.pacing`).
On upload these become a Garmin `pace.zone` target — values are stored in
m/s but the watch displays them as min/km. If both min and max are
omitted, the step has no pace target (RPE only).
"""

from __future__ import annotations

from garminconnect.workout import (
    ExecutableStep,
    RunningWorkout,
    WorkoutSegment,
    create_cooldown_step,
    create_interval_step,
    create_recovery_step,
    create_repeat_group,
    create_warmup_step,
)

_RUNNING_SPORT = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

_PACE_ZONE_TARGET = {
    "workoutTargetTypeId": 6,
    "workoutTargetTypeKey": "pace.zone",
    "displayOrder": 6,
}


def _apply_pace_target(
    step: ExecutableStep,
    pace_min_per_km: int | float | None,
    pace_max_per_km: int | float | None,
) -> ExecutableStep:
    """Attach a pace.zone target to `step` based on a pace range.

    `pace_min_per_km` is the *fastest* (smallest seconds), `pace_max_per_km`
    the *slowest* (largest seconds). Either may be None: a single-value
    target is broadened by ±5 sec/km so the watch doesn't beep constantly.

    Garmin stores the bounds as m/s under the hood for both speed.zone and
    pace.zone targets; the targetType key controls how the watch *displays*
    the range (min/km for pace, km/h for speed). Returns the same step for
    chaining.
    """
    if pace_min_per_km is None and pace_max_per_km is None:
        return step

    fast = pace_min_per_km if pace_min_per_km is not None else pace_max_per_km
    slow = pace_max_per_km if pace_max_per_km is not None else pace_min_per_km
    if fast == slow:
        fast = max(1, fast - 5)
        slow = slow + 5

    # Convert sec/km -> m/s. Faster pace -> higher speed.
    speed_high = round(1000.0 / float(fast), 4)
    speed_low = round(1000.0 / float(slow), 4)

    step.targetType = _PACE_ZONE_TARGET
    # Garmin's pace.zone target expects targetValueOne = high speed (fast
    # end) and targetValueTwo = low speed (slow end), opposite of what the
    # numeric ordering would suggest.
    step.targetValueOne = speed_high
    step.targetValueTwo = speed_low
    return step


def _segment(steps: list) -> WorkoutSegment:
    return WorkoutSegment(
        segmentOrder=1, sportType=_RUNNING_SPORT, workoutSteps=steps
    )


# ----------------------------------------------------------------- easy


def easy_run(
    duration_min: float,
    target_pace_min_per_km: int | float | None = None,
    target_pace_max_per_km: int | float | None = None,
    name: str | None = None,
    description: str | None = None,
) -> RunningWorkout:
    """A single-step easy run of `duration_min` minutes."""
    duration_s = duration_min * 60
    step = create_interval_step(duration_seconds=duration_s, step_order=1)
    _apply_pace_target(step, target_pace_min_per_km, target_pace_max_per_km)
    return RunningWorkout(
        workoutName=name or f"Easy {int(duration_min)}min",
        estimatedDurationInSecs=int(duration_s),
        workoutSegments=[_segment([step])],
        description=description,
    )


# ----------------------------------------------------------------- long


def long_run(
    duration_min: float,
    target_pace_min_per_km: int | float | None = None,
    target_pace_max_per_km: int | float | None = None,
    name: str | None = None,
    description: str | None = None,
) -> RunningWorkout:
    """A long, conversational-pace run."""
    duration_s = duration_min * 60
    step = create_interval_step(duration_seconds=duration_s, step_order=1)
    _apply_pace_target(step, target_pace_min_per_km, target_pace_max_per_km)
    return RunningWorkout(
        workoutName=name or f"Long {int(duration_min)}min",
        estimatedDurationInSecs=int(duration_s),
        workoutSegments=[_segment([step])],
        description=description,
    )


# ----------------------------------------------------------------- tempo


def tempo_run(
    tempo_min: float,
    tempo_pace_min_per_km: int | float | None = None,
    tempo_pace_max_per_km: int | float | None = None,
    warmup_min: float = 15,
    cooldown_min: float = 10,
    name: str | None = None,
    description: str | None = None,
) -> RunningWorkout:
    """Warmup, sustained tempo block (with optional pace target), cooldown.

    Warmup and cooldown stay no-target — they're meant to be flexible.
    """
    wu_s = warmup_min * 60
    tempo_s = tempo_min * 60
    cd_s = cooldown_min * 60

    tempo_step = create_interval_step(duration_seconds=tempo_s, step_order=2)
    _apply_pace_target(tempo_step, tempo_pace_min_per_km, tempo_pace_max_per_km)

    steps = [
        create_warmup_step(duration_seconds=wu_s, step_order=1),
        tempo_step,
        create_cooldown_step(duration_seconds=cd_s, step_order=3),
    ]
    return RunningWorkout(
        workoutName=name or f"Tempo {int(tempo_min)}min",
        estimatedDurationInSecs=int(wu_s + tempo_s + cd_s),
        workoutSegments=[_segment(steps)],
        description=description,
    )


# --------------------------------------------------------------- intervals


def interval_session(
    reps: int,
    work_min: float,
    recovery_min: float,
    work_pace_min_per_km: int | float | None = None,
    work_pace_max_per_km: int | float | None = None,
    recovery_pace_min_per_km: int | float | None = None,
    recovery_pace_max_per_km: int | float | None = None,
    warmup_min: float = 15,
    cooldown_min: float = 10,
    name: str | None = None,
    description: str | None = None,
) -> RunningWorkout:
    """Warmup, N x (work / recovery), cooldown.

    Pace targets are applied to the work and recovery steps independently;
    warmup/cooldown remain open.
    """
    if reps < 1:
        raise ValueError("reps must be >= 1")

    wu_s = warmup_min * 60
    work_s = work_min * 60
    rec_s = recovery_min * 60
    cd_s = cooldown_min * 60

    work_step = create_interval_step(duration_seconds=work_s, step_order=1)
    _apply_pace_target(work_step, work_pace_min_per_km, work_pace_max_per_km)

    rec_step = create_recovery_step(duration_seconds=rec_s, step_order=2)
    _apply_pace_target(rec_step, recovery_pace_min_per_km, recovery_pace_max_per_km)

    repeat = create_repeat_group(
        iterations=reps,
        workout_steps=[work_step, rec_step],
        step_order=2,
    )

    steps = [
        create_warmup_step(duration_seconds=wu_s, step_order=1),
        repeat,
        create_cooldown_step(duration_seconds=cd_s, step_order=3),
    ]

    total_s = wu_s + reps * (work_s + rec_s) + cd_s
    return RunningWorkout(
        workoutName=name or f"{reps}x{work_min:g}min intervals",
        estimatedDurationInSecs=int(total_s),
        workoutSegments=[_segment(steps)],
        description=description,
    )
