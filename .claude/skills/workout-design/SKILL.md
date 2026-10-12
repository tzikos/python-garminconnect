---
name: workout-design
description: How to design a training plan this repo can actually save and upload — the five workout primitives and their exact parameters, the plan JSON schema, per-sport coaching rules, and the pace/volume maths. Use whenever writing, editing or reviewing a plan, adding workouts to one, or when `coach plan import` rejects a file.
---

# Designing a plan

A plan is a JSON file. You write it, `coach plan import` validates and stores
it, `coach sync push` turns each workout into a Garmin workout on the watch.

Everything the watch will show comes from `primitive_type` +
`primitive_params`. Get those right and the rest is bookkeeping.

Read [the aerobic training approach](references/aerobic-training.md) when
building, evaluating or refining endurance training. It captures the athlete's
preferred 10–14-day intensity rotation, progression, VO2 blocks, recovery and
durability, mapped to the supported primitives.

## The five primitives

`primitive_type` must be EXACTLY one of these. There are no others, and sport
names ("running", "calisthenics") are **not** primitive types — those go in
the `sport` field.

All paces are integer **seconds per km** (smaller = faster). Set pace targets
whenever you have zones, so the watch prescribes the range instead of leaving
it to feel.

```
easy_run(duration_min, target_pace_min_per_km?, target_pace_max_per_km?)
    Easy aerobic run. Pace from the "easy" zone.

long_run(duration_min, target_pace_min_per_km?, target_pace_max_per_km?)
    Long steady run. "easy" or "marathon" zone.

tempo_run(tempo_min, warmup_min=15, cooldown_min=10,
          tempo_pace_min_per_km?, tempo_pace_max_per_km?)
    Sustained block between easy warmup and cooldown. "threshold" zone.

interval_session(reps, work_min, recovery_min, warmup_min=15, cooldown_min=10,
                 work_pace_min_per_km?, work_pace_max_per_km?,
                 recovery_pace_min_per_km?, recovery_pace_max_per_km?)
    N x (work / recovery). Work zone follows the stimulus: threshold for
    threshold reps, interval for VO2, effort cues for short strides.
    Work/recovery minutes may be fractional; recovery is easy.

strength_session(duration_min, exercises)
    Strength OR calisthenics. Each exercise is:
      {"name": "Back Squat", "sets": 4, "reps": "5", "weight": "100kg",
       "rest": "2min", "notes": "paused"}
    reps may be 5, "8-10" or "AMRAP". weight may be "100kg", "BW", "RPE 8",
    or omitted entirely for bodyweight work.
```

Both `duration_min` and `exercises` are required for `strength_session`.

## Plan JSON schema

```json
{
  "name": "Sub-3:30 Athens + Hybrid Strength",
  "goal_text": "Race Athens Classic Marathon on 2026-11-08 (42.2km)",
  "start_date": "2026-09-21",
  "end_date": "2026-11-08",
  "weekly_structure": [
    {
      "week_number": 1,
      "theme": "Base building",
      "target_volume_km": 42,
      "workouts": [
        {
          "date": "2026-09-22",
          "sport": "running",
          "title": "Easy 50min",
          "description": "Conversational. Nose-breathing pace.",
          "primitive_type": "easy_run",
          "primitive_params": {
            "duration_min": 50,
            "target_pace_min_per_km": 330,
            "target_pace_max_per_km": 350
          }
        }
      ]
    }
  ]
}
```

`date`, `sport`, `title`, `primitive_type` are required on every workout.
`end_date` is race day when there is a race.

## Coaching rules

### Running
- ≤10% weekly volume increase as a ceiling, anchored to actual tolerated load.
  Every 4th week normally deloads to ~70% of the previous; recovery may require
  earlier reductions. Progression is earned, not automatic.
- Weekend long run and Tue/Thu quality are defaults; respect the calendar.
  Use up to two quality days with variety across 10–14 days as described in
  the aerobic reference. Most running stays easy.
- Easy runs between hard sessions. Never two hard runs back to back.

### Strength (weights)
- 3 weeks build, 1 week deload.
- Build by adding load **or** reps, never both in the same week.
- Deload: same lifts at ~60% load.
- Prescribe % 1RM or RPE 7-9 for primary work, RPE 5-6 for technique.
- No max-effort lifts in the last week before a goal race.

### Calisthenics
- Progress by adding reps while sets sit below ~70% of max, or by moving to a
  harder variation (assisted → regular → weighted).
- Pyramids, ladders and EMOM formats. Total reps below ~3× max.
- `primitive_type` is `strength_session`; `sport` is `calisthenics`.

### Across sports
- No heavy lower-body strength the day before a long run.
- No hard intervals the day after heavy lower-body work.
- Race week: volume down 50-70%, no max-effort strength.
- At most 3 hard sessions per week across all sports.

### Never include
Rest days. "Active recovery" as its own thing — if it is a real 30-minute jog
it is an `easy_run`, otherwise leave the day out entirely. Only emit workouts
the athlete will actually do and want on their watch.

## Let the repo do the maths

Don't compute paces or progressions by hand — these functions are tested and
the plan should agree with them. Zones come back as dicts of seconds per km
(`min_per_km` / `max_per_km`), which is exactly what the primitives take:

```bash
uv run python -c "
from coach.tools import compute_pace_zones, compute_hr_zones, weekly_volume_progression, format_pace
z = compute_pace_zones(1350)                       # recent 5k in seconds
for name, r in z.items():
    print(name, r['min_per_km'], r['max_per_km'],
          format_pace(r['min_per_km']), format_pace(r['max_per_km']))
print(compute_hr_zones(threshold_hr=170, max_hr=190))
print(weekly_volume_progression(40, 70, 12, taper_weeks=2))
"
```

`coach.tools` also has `interference_check(week)` and
`validate_workout(type, params)` — run them over a week you are unsure about
before importing.

## Shaping the plan around the course

Course research is what makes the plan specific rather than generic. Apply it:

| Course fact | What changes in the plan |
|---|---|
| Sustained climb at km X | Hill reps and long runs with a climb at the same point in the run |
| Net downhill | Downhill running to condition quads; eccentric strength |
| Hot / humid on race day | Heat acclimation in the last 3 weeks |
| Altitude | Flag it, lower intensity expectations, more recovery |
| Trail / technical | Terrain-specific long runs, ankle and single-leg work |
| Early start | Some sessions at race time |

If research came back with `confidence: low`, say so in the plan's
`goal_text` and keep the plan conservative rather than inventing specificity.

## Saving it

```bash
uv run coach plan import /tmp/plan.json              # new plan
uv run coach plan import /tmp/plan.json --plan-id 3  # overwrite plan 3
```

Import validates every primitive and its params before writing anything. When
it rejects a workout, fix that workout — do not simplify the plan to get past
the validator. Overwriting refuses if the plan has already been uploaded;
`/unpush` first.
