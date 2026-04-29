"""Prompt builders for plan generation.

System prompt defines the LLM's role + the JSON schema we expect back +
per-sport coaching rules. User prompt carries the goal, profile, and
pre-computed numbers (so the LLM doesn't do pace/volume math).
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

SYSTEM_PROMPT = """You are a multi-sport training planner. You design week-by-week plans for athletes who train across multiple disciplines toward a specific goal.

You produce STRUCTURED JSON only. No prose, no markdown, no commentary outside the JSON object.

## Available workout primitives

`primitive_type` must be EXACTLY one of these strings — no others:
  "easy_run", "long_run", "tempo_run", "interval_session", "strength_session"

Do NOT invent new primitive names. Sport names ("calisthenics", "running",
"strength") are NOT primitive types — they go in the `sport` field.

Each primitive has a fixed parameter shape.
All pace values are integer **seconds per km** (smaller = faster). Prefer
setting pace targets when zones are provided so the watch prescribes the
exact range; omit them only when paces are genuinely open.

- easy_run(duration_min: number,
           target_pace_min_per_km?: int, target_pace_max_per_km?: int)
  Easy aerobic run. Use the "easy" zone for pace targets.

- long_run(duration_min: number,
           target_pace_min_per_km?: int, target_pace_max_per_km?: int)
  Long, steady run. Use "easy" or "marathon" zone.

- tempo_run(tempo_min: number, warmup_min: number = 15, cooldown_min: number = 10,
            tempo_pace_min_per_km?: int, tempo_pace_max_per_km?: int)
  Sustained block flanked by easy warmup/cooldown. Use the "threshold" zone.

- interval_session(reps: int, work_min: number, recovery_min: number,
                   warmup_min: number = 15, cooldown_min: number = 10,
                   work_pace_min_per_km?: int, work_pace_max_per_km?: int,
                   recovery_pace_min_per_km?: int, recovery_pace_max_per_km?: int)
  N x (work/recovery). "interval" zone for work_pace, "easy" zone for recovery.

- strength_session(duration_min: number, exercises: list[exercise])
  Strength OR calisthenics. Each exercise:
    {"name": "Back Squat", "sets": 4, "reps": "5", "weight": "100kg",
     "rest": "2min", "notes": "paused"}
  reps may be int, "8-10", "AMRAP". weight may be "60kg", "BW", "RPE 8",
  or omitted for bodyweight calisthenics.

## Per-sport coaching rules

Apply the rule set for the sport you're prescribing.

RUNNING
- Use the pre-computed pace zones from the profile.
- ≤10% weekly volume increase. Every 4th week is a deload (~70% of prior).
- Long run typically on weekend; quality (tempo/intervals) on Tue/Thu.
- Use easy_run between hard sessions; never two hard runs back-to-back.

STRENGTH (weights)
- 3 weeks build, 1 week deload (3:1 wave).
- Build: increase load OR reps each week, not both.
- Deload week: same lifts, ~60% load.
- Use the user's 1RM benchmarks: prescribe % 1RM or RPE 7-9 for primary work,
  RPE 5-6 for technique/skill.
- Drop max-effort lifts during the last week before a goal race.

CALISTHENICS
- Progress by adding reps when current sets are below ~70% of max,
  OR by progressing to a harder variation
  (assisted -> regular -> weighted; pushup -> pseudo-planche; etc.).
- Use pyramids, ladders, and EMOM formats. Keep total reps below ~3x max.
- Deload week: 70% of prior week's volume.
- Bodyweight movements use weight: "BW" or omit weight entirely.

CROSS-SPORT (always)
- Don't put heavy lower-body strength the day before a long run.
- Don't put hard intervals the day after heavy lower-body work.
- Race week (last 7 days before goal): drop volume 50-70%, no max-effort
  strength, keep skill-sharpening only.
- Max 3 hard sessions across all sports per week.

## What NOT to include

- Do NOT include rest days as workouts. Just leave those days off the schedule.
- Do NOT prescribe "active recovery" as a separate primitive — if it's a real
  workout (e.g. easy 30min run) use easy_run; otherwise omit the day entirely.
- Only emit workouts the user will actually do and want pushed to their watch.

## JSON output rules

- Output VALID JSON only. No trailing commas. No comments (// or /* */).
- For calisthenics workouts, primitive_type is "strength_session" (NOT
  "calisthenics"); the sport field is "calisthenics".
- strength_session ALWAYS requires both `duration_min` and `exercises`.
- Keep `description` short (≤120 chars) and `why` short (≤200 chars). Long
  prose burns output tokens and may truncate the JSON.

## Output schema

Return EXACTLY this shape:

{
  "name": "<short plan name, e.g. 'Sub-1:45 HM + Hybrid Strength'>",
  "weekly_structure": [
    {
      "week_number": 1,
      "theme": "<e.g. 'Base building', 'Build', 'Peak', 'Deload', 'Taper'>",
      "target_volume_km": <number, running km this week if running enabled>,
      "workouts": [
        {
          "date": "YYYY-MM-DD",
          "sport": "running" | "strength" | "calisthenics",
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


# ----------------------------------------------------------- helpers


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


def _fmt_5k(seconds: int | None) -> str:
    if seconds is None:
        return "(not provided)"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _fmt_secs_to_pace(distance_km: float, seconds: int) -> str:
    """Compact 'distance: time (X:YY/km)' format."""
    m, s = divmod(seconds, 60)
    pace_per_km = seconds / distance_km if distance_km > 0 else 0
    pm, ps = divmod(int(pace_per_km), 60)
    return f"{distance_km}km {m}:{s:02d} ({pm}:{ps:02d}/km)"


# ------------------------------------------------- per-sport blocks


def _running_block(profile: dict[str, Any], sport_data: dict[str, Any]) -> str:
    lines = ["RUNNING (enabled)"]

    race_times = sport_data.get("race_times") or []
    if race_times:
        lines.append("- Race times:")
        for rt in race_times:
            try:
                lines.append(f"    {_fmt_secs_to_pace(rt['distance_km'], rt['seconds'])}")
            except (KeyError, TypeError):
                continue

    # Fallback: pace zones from recent_5k_seconds (legacy field).
    seconds_5k = profile.get("recent_5k_seconds")
    if not seconds_5k and race_times:
        for rt in race_times:
            if rt.get("distance_km") == 5:
                seconds_5k = rt.get("seconds")
                break
    if seconds_5k:
        lines.append(f"- Pace zones (sec/km): {_format_pace_zones(seconds_5k)}")
    else:
        lines.append("- Pace zones: (no benchmark — use RPE/feel)")

    threshold_hr = profile.get("threshold_hr")
    max_hr = profile.get("max_hr")
    if threshold_hr or max_hr:
        lines.append(f"- HR zones: {_format_hr_zones(threshold_hr, max_hr)}")

    return "\n".join(lines)


def _strength_block(sport_data: dict[str, Any]) -> str:
    lines = ["STRENGTH (enabled)"]
    lifts = sport_data.get("lifts_1rm") or {}
    set_lifts = {k: v for k, v in lifts.items() if v}
    if set_lifts:
        names = {
            "squat_kg": "Squat", "bench_kg": "Bench", "deadlift_kg": "Deadlift",
            "ohp_kg": "OHP",
        }
        line = ", ".join(f"{names.get(k, k)} {v}kg" for k, v in set_lifts.items())
        lines.append(f"- 1RM: {line}")
    else:
        lines.append("- 1RM: (not provided — use RPE only)")

    age = sport_data.get("training_age_years")
    if age:
        lines.append(f"- Training age: {age} years")
    return "\n".join(lines)


def _calisthenics_block(sport_data: dict[str, Any]) -> str:
    lines = ["CALISTHENICS (enabled)"]
    reps = sport_data.get("max_reps") or {}
    set_reps = {k: v for k, v in reps.items() if v}
    if set_reps:
        names = {
            "pullups": "pull-ups", "dips": "dips", "pushups": "push-ups",
            "squats": "squats", "pistol_squats": "pistol squats",
        }
        line = ", ".join(f"{names.get(k, k)} {v}" for k, v in set_reps.items())
        lines.append(f"- Max reps: {line}")

    holds = sport_data.get("max_holds") or {}
    set_holds = {k: v for k, v in holds.items() if v}
    if set_holds:
        names = {
            "l_sit_seconds": "L-sit", "handstand_seconds": "handstand",
        }
        line = ", ".join(f"{names.get(k, k)} {v}s" for k, v in set_holds.items())
        lines.append(f"- Max holds: {line}")

    if not set_reps and not set_holds:
        lines.append("- (no benchmarks provided — use RPE/feel)")
    return "\n".join(lines)


_SPORT_FORMATTERS = {
    "running": _running_block,
    "strength": lambda profile, data: _strength_block(data),
    "calisthenics": lambda profile, data: _calisthenics_block(data),
}


# ------------------------------------------------- top-level builder


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

    # Active sports: prefer enabled_sports list; fall back to "running" only
    # when the user hasn't picked anything yet (legacy profiles).
    enabled = list(profile.get("enabled_sports") or [])
    if not enabled:
        enabled = ["running"]
    sport_profiles = profile.get("sport_profiles") or {}

    # Per-sport benchmark blocks
    sport_blocks: list[str] = []
    for sport in enabled:
        formatter = _SPORT_FORMATTERS.get(sport)
        if formatter is None:
            sport_blocks.append(f"{sport.upper()} (enabled, no benchmark schema)")
            continue
        sport_blocks.append(formatter(profile, sport_profiles.get(sport, {})))

    # Running volume block — only if running is enabled
    weekly_hours = profile.get("weekly_hours_target")
    inferred_peak = peak_volume_km or (
        weekly_hours * 8 if weekly_hours else max(40.0, start_volume_km * 1.5)
    )
    if "running" in enabled:
        volume_block = _format_volume(start_volume_km, inferred_peak, weeks, taper_weeks)
        volume_section = (
            "PRE-COMPUTED RUNNING VOLUME (use as guidance for total km/week):\n"
            f"{volume_block}\n\n"
        )
    else:
        volume_section = ""

    preferred = profile.get("preferred_days") or {}
    if preferred:
        pref_block = ", ".join(f"{sport}=days {days}" for sport, days in preferred.items())
    else:
        pref_block = "(none specified — choose reasonably)"

    return f"""GOAL: {goal_text}

DATE RANGE: {start_date.isoformat()} to {end_date.isoformat()} ({weeks} weeks, weeks start Monday)

ENABLED SPORTS: {', '.join(enabled)}

USER PROFILE
- Name: {profile.get('name', 'athlete')}
- Preferred training days (0=Mon..6=Sun): {pref_block}
- Weekly hours target: {weekly_hours or '(not set)'}
- Notes: {profile.get('notes') or '(none)'}

PER-SPORT BENCHMARKS

{chr(10).join(sport_blocks)}

{volume_section}Generate the plan now as JSON only. Only include sports listed in ENABLED SPORTS."""
