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
    intake: dict[str, Any] | None = None,
) -> str:
    """Assemble the user-side prompt with profile + pre-computed numbers.

    `intake` is the fact dict from a chat intake, if one was run. It is
    rendered ahead of the generation instruction so the athlete's own
    answers and the race course research outrank the defaults above.
    """
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

{volume_section}{render_intake_facts(intake or {})}
Generate the plan now as JSON only. Only include sports listed in ENABLED SPORTS."""


# ============================================================ chat intake
#
# The intake is a one-question-at-a-time interview that fills a `facts`
# dict. The LLM sees the facts it has so far plus the stored profile, and
# returns the single most valuable next question. When the facts are good
# enough to plan from it sets `ready`, and `build_user_prompt` renders them
# into the normal generation prompt.


# What a good coach would want to know before writing a block. The model
# picks from this rather than inventing its own agenda, which keeps the
# interview from wandering or re-asking things the profile already answers.
INTAKE_CHECKLIST = """
1.  goal_type — "race", "fitness", "body_composition", "return_from_injury",
    or "strength_goal". Ask this FIRST if unknown.
2.  If goal_type is "race": race_name, race_date, race_distance_km,
    race_target_seconds (or null for "just finish"), race_been_before.
    Ask for the race BY NAME — the name unlocks course research.
3.  tune_up_races — earlier races to build into the plan as workouts.
4.  current_weekly_km and longest_recent_run_km — where the ramp starts.
    Never guess these; an over-ambitious week 1 is the main way plans fail.
5.  years_training — training age, for how fast to progress.
6.  days_per_week and available_days (0=Mon..6=Sun) — the actual calendar.
7.  session_cap_min — longest single session on a weekday, and on a weekend.
8.  secondary_sports and sport_priority — what else they keep doing, and
    what gives way when time is short.
9.  injuries, niggles, avoid_movements — past injuries and current aches.
10. equipment — gym, treadmill, track, pool, hills nearby, bike.
11. terrain_access — what they can actually train on (flat city, trails,
    hills). Matters most when it mismatches the race course.
12. blackout_dates — travel, work crunch, holidays: weeks to keep easy.
13. recovery — sleep hours, stress level, whether they fuel long efforts.
14. aggressiveness — "conservative", "moderate" or "aggressive" progression.
15. dealbreakers — hard rules ("never Sundays", "no 5am", "no treadmill").
"""


INTAKE_SYSTEM_PROMPT = f"""You are a head coach doing an intake interview before writing a training plan. You ask ONE question at a time, like a person would, and you build up a structured picture of the athlete.

You output STRUCTURED JSON only. No prose, no markdown, no commentary outside the JSON object.

## What you are trying to learn

{INTAKE_CHECKLIST}

## How to interview

- ONE question per turn. Never batch.
- Ask the highest-value unknown next. Order matters: goal first, then the
  race identity, then the athlete's current load, then the calendar, then
  the constraints, then the nice-to-haves.
- NEVER ask for something already present in KNOWN FACTS or in the stored
  PROFILE. If the profile has their 5k time, you know their fitness anchor.
- If an answer implies other facts, record them. "I run 4 times a week,
  usually Tue Thu Sat Sun" fills days_per_week AND available_days.
- If an answer is vague ("a decent amount"), ask one sharpening follow-up,
  then accept whatever you get and move on.
- Every answer arrives as free text, in the athlete's own words. Converting
  it to the standardized value is YOUR job, not theirs.
- Acknowledge briefly in `note` — one short line reacting to their last
  answer. This is the only text the athlete reads from you per turn.
- Once RACE COURSE RESEARCH appears in your context, use it: ask about the
  specific demands it reveals (a hilly course -> do they have hills to
  train on; a hot race -> heat acclimation; an early start -> morning runs).
- Stop when you can write a responsible plan. Perfect information is not
  the goal — a plan that fits their week is. Set "ready": true then.
- Set "ready": true immediately if the athlete asks you to stop asking.

## Reading free-text answers

The athlete types in their own words. Normalise what they say into the
standardized fact value:

- dates -> "YYYY-MM-DD" ("second Sunday of November" -> resolve it against
  today's date; "next spring" is NOT a date, ask which month)
- distances -> a number in km ("a half" -> 21.1, "10 miles" -> 16.1)
- times and durations -> seconds ("sub 3:30" -> 12600)
- days of the week -> integers, 0=Mon..6=Sun ("Tue Thu Sat" -> [1, 3, 5])
- counts -> plain numbers ("four or five" -> 4, and say so in `note`)
- one-of fields (goal_type, aggressiveness, sport_priority) -> exactly one
  of the values listed in the checklist, never a paraphrase

When the answer offers a choice, name the options inside the question text
("race, general fitness, coming back from injury, or something else?") —
the athlete answers in words either way.

If you cannot convert an answer confidently, ASK AGAIN. Say what was
ambiguous and what you need ("Which November — 2026?"). Never invent a
value to fill the field, and never record a fact you had to guess: a
missing fact is recoverable, a wrong one silently shapes the whole plan.
If they refuse or genuinely do not know after one retry, leave the fact
out and move on.

## Output schema

Return EXACTLY this shape:

{{
  "note": "<one short line reacting to their last answer, or a greeting on turn 1>",
  "facts": {{ <the FULL merged fact dict: everything known so far plus
              whatever the last answer just taught you> }},
  "question": {{
    "id": "<snake_case key this answer fills, e.g. 'race_name'>",
    "text": "<the question, one sentence, conversational. Include the
              units you want and any choices you have in mind.>"
  }},
  "ready": false,
  "summary": "<when ready=true: 2-4 sentences briefing yourself on this
               athlete and this goal. Otherwise empty string.>"
}}

`facts` is always the complete merged dict — never a partial patch.
When "ready" is true, set "question" to null.

Output the JSON object and NOTHING else."""


RACE_RESEARCH_SYSTEM_PROMPT = """You research race courses. You are given a race name and date, and web search results about it.

Extract what changes how an athlete should TRAIN for it. Be concrete and numeric where the sources are; use null where they are not. Do not invent numbers — a null is more useful than a guess.

Return EXACTLY this JSON shape and nothing else:

{
  "race_official_name": "<full name, or the name as given if unconfirmed>",
  "distance_km": <number or null>,
  "elevation_gain_m": <number or null>,
  "profile": "<'flat' | 'rolling' | 'hilly' | 'mountainous' | 'net downhill' | 'unknown'>",
  "surface": "<'road' | 'trail' | 'track' | 'mixed' | 'unknown'>",
  "course_notes": "<2-4 sentences: where the climbs and descents fall, the
                    hardest section and at what km, any technical footing,
                    laps vs point-to-point, altitude>",
  "climate_notes": "<typical conditions on that date: temperature, humidity,
                     wind, sun exposure, start time if known>",
  "training_implications": ["<short imperative, e.g. 'Practise sustained 4-6% climbs at km 12-18'>", ...],
  "confidence": "<'high' if sources clearly describe this race, 'low' if
                  results were thin or ambiguous>",
  "sources": ["<url>", ...]
}

If the search results do not actually describe this race, set confidence to "low", leave the numeric fields null, and say so in course_notes. Output the JSON object and NOTHING else."""


def build_intake_prompt(
    *,
    history: list[dict[str, str]],
    facts: dict[str, Any],
    profile: dict[str, Any],
    questions_asked: int,
    max_questions: int,
) -> str:
    """Assemble the intake turn prompt: profile + facts so far + transcript."""
    import json as _json

    known = {k: v for k, v in facts.items() if v not in (None, "", [], {})}
    research = known.pop("race_research", None)

    lines = [
        f"TODAY: {date.today().isoformat()}",
        "",
        "STORED PROFILE (already known — do NOT ask for any of this)",
        _json.dumps(_profile_digest(profile), indent=2),
        "",
        "KNOWN FACTS SO FAR",
        _json.dumps(known, indent=2) if known else "(nothing yet — this is turn 1)",
    ]

    if research:
        lines += [
            "",
            "RACE COURSE RESEARCH (from web search — use it to sharpen your "
            "remaining questions)",
            _json.dumps(research, indent=2),
        ]

    if history:
        lines += ["", "TRANSCRIPT"]
        lines += [f"{m['role'].upper()}: {m['content']}" for m in history]

    remaining = max_questions - questions_asked
    lines += [
        "",
        f"You have asked {questions_asked} question(s). At most {remaining} remain.",
    ]
    if remaining <= 2:
        lines.append(
            "You are nearly out of questions. Ask only something you cannot "
            "write a safe plan without, otherwise set ready=true now."
        )
    lines.append("Return the next turn as JSON.")
    return "\n".join(lines)


def build_race_research_prompt(
    race_name: str, race_date: str | None, sources: str = ""
) -> str:
    """Prompt for the course research call.

    `sources` is text fetched locally (see coach.llm.websearch) — the
    model does no searching of its own, so anything absent from here it
    must report as unknown rather than recall.
    """
    when = f" taking place on {race_date}" if race_date else ""
    found = (
        f"SEARCH RESULTS:\n{sources}\n\n"
        if sources
        else "SEARCH RESULTS: none were retrieved.\n\n"
    )
    return (
        f"{found}"
        f"Research the race '{race_name}'{when} using ONLY the search "
        "results above.\n\n"
        "Find its course profile: total elevation gain, where the climbs and "
        "descents fall, the surface, altitude, and the typical weather on "
        "that date. Then return the JSON object."
    )


def _profile_digest(profile: dict[str, Any]) -> dict[str, Any]:
    """The parts of the stored profile the interviewer must not re-ask."""
    return {
        "name": profile.get("name"),
        "recent_5k": _fmt_5k(profile.get("recent_5k_seconds")),
        "threshold_hr": profile.get("threshold_hr"),
        "max_hr": profile.get("max_hr"),
        "enabled_sports": profile.get("enabled_sports") or [],
        "sport_profiles": profile.get("sport_profiles") or {},
        "preferred_days": profile.get("preferred_days") or {},
        "weekly_hours_target": profile.get("weekly_hours_target"),
        "notes": profile.get("notes"),
    }


def render_intake_facts(facts: dict[str, Any]) -> str:
    """Render intake facts as a prompt block for plan generation.

    Course research gets its own section because it is the one input that
    should visibly change the workouts (hill reps for a hilly race, heat
    work for a hot one) — burying it in a JSON dump gets it ignored.
    """
    import json as _json

    facts = dict(facts)
    research = facts.pop("race_research", None)
    summary = facts.pop("_summary", None)

    known = {k: v for k, v in facts.items() if v not in (None, "", [], {})}
    if not known and not research:
        return ""

    out = ["INTAKE INTERVIEW FINDINGS", "These came from the athlete directly. They override defaults.", ""]
    if summary:
        out += [f"Coach's brief: {summary}", ""]
    if known:
        out += [_json.dumps(known, indent=2), ""]

    if research:
        out += [
            "RACE COURSE RESEARCH",
            "Shape the plan around this course. Prescribe the specific demands "
            "it names — do not write a generic flat-road plan for a hilly race.",
            _json.dumps(research, indent=2),
            "",
        ]
    return "\n".join(out)
