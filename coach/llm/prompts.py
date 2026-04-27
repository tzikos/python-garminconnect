"""Prompt builders for plan generation.

System prompt defines the LLM's role + the JSON schema we expect back.
User prompt carries the goal, profile, and pre-computed numbers so the
LLM doesn't have to do pace/volume math itself.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from coach.tools import (
    compute_hr_zones,
    compute_pace_zones,
    format_pace,
    weekly_volume_progression,
)

SYSTEM_PROMPT = """You are a multi-sport training planner. You design week-by-week plans for athletes who train across multiple disciplines (running, strength, cycling, etc.) toward a specific goal.

You produce STRUCTURED JSON only. No prose, no markdown, no commentary outside the JSON object.

## Available workout primitives

You can ONLY prescribe these primitives. Each has a fixed parameter shape.
All pace values are integer **seconds per km** (smaller = faster). When the
profile includes pace zones, prefer setting pace targets so the watch
prescribes the exact range; omit them only when paces are genuinely open.

- easy_run(duration_min: number,
           target_pace_min_per_km?: int, target_pace_max_per_km?: int)
  Easy aerobic run. Use the "easy" zone for pace targets.

- long_run(duration_min: number,
           target_pace_min_per_km?: int, target_pace_max_per_km?: int)
  Long, steady run. Use "easy" or "marathon" zone.

- tempo_run(tempo_min: number, warmup_min: number = 15, cooldown_min: number = 10,
            tempo_pace_min_per_km?: int, tempo_pace_max_per_km?: int)
  Sustained block flanked by easy warmup/cooldown. Use the "threshold" zone
  for tempo_pace.

- interval_session(reps: int, work_min: number, recovery_min: number,
                   warmup_min: number = 15, cooldown_min: number = 10,
                   work_pace_min_per_km?: int, work_pace_max_per_km?: int,
                   recovery_pace_min_per_km?: int, recovery_pace_max_per_km?: int)
  N x (work/recovery). Use the "interval" zone for work_pace and the "easy"
  zone for recovery_pace.

- strength_session(duration_min: number, exercises: list[exercise])
  Strength training. Each exercise:
    {
      "name": "Back Squat",
      "sets": 4,
      "reps": "5"        // can be int, "8-10", "AMRAP"
      "weight": "100kg", // optional, can be "BW", "RPE 8"
      "rest": "2min",    // optional
      "notes": "paused"  // optional
    }

## Coaching principles

- Honor the user's preferred days per sport.
- Build volume gradually; never spike >10% week-over-week.
- Every 4th week is a deload (~70% of the prior week's volume).
- Avoid two hard sessions back-to-back. Insert easy or rest in between.
- Avoid heavy lower-body strength the day before a long run.
- Max 3 hard sessions per week (tempo, intervals, heavy strength).
- Last 1-2 weeks before the goal date taper to 70% then 50% of peak.
- Multi-sport: place the most goal-relevant sessions on freshest days.

## Output schema

Return EXACTLY this shape:

{
  "name": "<short plan name, e.g. 'Sub-1:45 Half Marathon Build'>",
  "weekly_structure": [
    {
      "week_number": 1,
      "theme": "<e.g. 'Base building', 'Build', 'Peak', 'Deload', 'Taper'>",
      "target_volume_km": <number>,
      "workouts": [
        {
          "date": "YYYY-MM-DD",
          "sport": "running" | "strength" | "cycling",
          "primitive_type": "<one of the primitives above>",
          "primitive_params": { <kwargs for that primitive> },
          "title": "<short watch-display name, <=24 chars>",
          "description": "<short note shown on watch; for strength leave empty (auto-built)>",
          "why": "<1-2 line rationale for the user>"
        }
      ]
    }
  ]
}

Output the JSON object and NOTHING else."""


def _format_pace_zones(seconds_5k: int) -> str:
    z = compute_pace_zones(seconds_5k)
    return (
        f"easy {format_pace(z['easy']['min_per_km'])}-{format_pace(z['easy']['max_per_km'])}/km, "
        f"marathon {format_pace(z['marathon']['min_per_km'])}-{format_pace(z['marathon']['max_per_km'])}/km, "
        f"threshold {format_pace(z['threshold']['min_per_km'])}-{format_pace(z['threshold']['max_per_km'])}/km, "
        f"interval {format_pace(z['interval']['min_per_km'])}-{format_pace(z['interval']['max_per_km'])}/km, "
        f"repetition {format_pace(z['repetition']['min_per_km'])}-{format_pace(z['repetition']['max_per_km'])}/km"
    )


def _format_hr_zones(threshold_hr: int | None, max_hr: int | None) -> str:
    if threshold_hr is None and max_hr is None:
        return "(not provided)"
    z = compute_hr_zones(threshold_hr=threshold_hr, max_hr=max_hr)
    parts = [f"{name} {r['min_bpm']}-{r['max_bpm']}bpm" for name, r in z.items()]
    anchor = (
        f"LTHR={threshold_hr}" if threshold_hr is not None else f"HRmax={max_hr}"
    )
    return f"({anchor}) " + ", ".join(parts)


def _format_volume(start_km: float, peak_km: float, weeks: int, taper_weeks: int = 2) -> str:
    if weeks < 3:
        return "(plan too short for volume progression — design freely)"
    v = weekly_volume_progression(start_km, peak_km, weeks, taper_weeks)
    return "\n".join(f"  Week {i + 1}: {km} km" for i, km in enumerate(v))


def build_user_prompt(
    *,
    goal_text: str,
    start_date: date,
    end_date: date,
    profile: dict[str, Any],
    start_volume_km: float = 25,
    peak_volume_km: float | None = None,
    taper_weeks: int = 2,
) -> str:
    """Assemble the user-side prompt with profile + pre-computed numbers."""
    weeks = ((end_date - start_date).days // 7) + 1

    pace_zones = (
        _format_pace_zones(profile["recent_5k_seconds"])
        if profile.get("recent_5k_seconds")
        else "(no recent 5k — derive paces from RPE/feel)"
    )
    hr_zones = _format_hr_zones(profile.get("threshold_hr"), profile.get("max_hr"))

    weekly_hours = profile.get("weekly_hours_target")
    inferred_peak = peak_volume_km or (
        weekly_hours * 8 if weekly_hours else max(40.0, start_volume_km * 1.5)
    )
    volume_block = _format_volume(start_volume_km, inferred_peak, weeks, taper_weeks)

    preferred = profile.get("preferred_days") or {}
    pref_block = (
        ", ".join(f"{sport}=days {days}" for sport, days in preferred.items())
        if preferred
        else "(none specified — choose reasonably)"
    )

    return f"""GOAL: {goal_text}

DATE RANGE: {start_date.isoformat()} to {end_date.isoformat()} ({weeks} weeks, weeks start Monday)

USER PROFILE
- Name: {profile.get('name', 'athlete')}
- Recent 5k time: {_fmt_5k(profile.get('recent_5k_seconds'))}
- Pace zones (sec/km): {pace_zones}
- HR zones: {hr_zones}
- Preferred training days (0=Mon..6=Sun): {pref_block}
- Weekly hours target: {weekly_hours or '(not set)'}
- Notes: {profile.get('notes') or '(none)'}

PRE-COMPUTED VOLUME PROGRESSION (use as guidance for total running km/week):
{volume_block}

Generate the plan now as JSON only."""


def _fmt_5k(seconds: int | None) -> str:
    if seconds is None:
        return "(not provided)"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
