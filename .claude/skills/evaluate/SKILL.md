---
name: evaluate
description: Evaluate completed Garmin activities during a training plan, compare execution with the prescription, and persist assessments so repeated evaluations skip already reviewed activities. Use for /evaluate or reviewing training completed in a program.
---

# Evaluate completed training

This workflow writes local evaluations and reads Garmin activities. It does
not modify the plan or Garmin calendar. Read `../workout-design/SKILL.md`
and its aerobic-training reference to interpret the intended stimulus.

## Select the program and collect evidence

1. Read `uv run coach profile show` and `uv run coach plan list`. Use the
   requested plan ID. Otherwise select the sole plan containing today's
   local date. If several qualify, or none does, ask which program to review.
   Do not silently choose the newest draft. An explicit past plan is valid.
2. Export with `uv run coach plan export <id> --out /tmp/evaluate-plan-<id>.json`.
   Exports include local workout IDs for matching.
3. Read saved history with `uv run coach review list --plan-id <id>`.
4. Run `uv run coach review fetch --plan-id <id>`. This fetches all sports from
   plan start through the earlier of today or plan end (inclusive, Garmin
   activity-local dates), including unscheduled sessions and late uploads.
   The library paginates; evaluated IDs are skipped before detail/split calls.
   Do not replace this with a latest-N activities query.
5. Inspect top-level `errors` and each activity's `evidence.errors`. Missing
   splits may permit a qualified summary assessment; insufficient evidence
   means leave the activity pending. Failed fetching is not proof that no
   training occurred. Future plans and empty periods have nothing to evaluate.

## Assess pending activities

- Match using sport, date, duration, session structure and available workout
  references. Garmin activity IDs and workout IDs are distinct. Same date
  alone is insufficient, especially with doubles or multisport. A moved
  session can match another date when evidence or athlete feedback confirms
  it. Leave ambiguous matches null and assess as unscheduled training.
- Compare prescribed and actual duration, distance, interval completion,
  lap pacing, recoveries, and HR/RPE where available. Garmin summary distance
  is metres, duration seconds, and speed metres/second; convert explicitly.
  Missing data stays unknown. Do not judge intervals by whole-session pace
  or strength execution from HR alone.
- Assess easy aerobic, threshold, VO2, short speed, durability and strength
  stimuli as applicable. Interpret fade/HR drift only from suitable comparable
  segments, accounting for hills, heat, pauses and sensors. Do not equate a
  watch estimate with a lab VO2 test or diagnose fitness from one session.
- Separate observation, interpretation and uncertainty. Incorporate reported
  effort, soreness, recovery and fueling. Missing recordings are not confirmed
  missed workouts until sync completeness is known.
- Give a concrete coaching implication, including keeping the plan when
  justified. `/evaluate` itself makes no plan changes.

## Save and report

Write a JSON list of finished assessments:

```json
[
  {
    "activity_id": 123456789,
    "workout_id": null,
    "assessment": "Observed ... Compared with ... Interpretation ... Uncertainty ...",
    "recommendation": "Keep the next easy session conversational; no pace increase yet."
  }
]
```

Use the matched local ID from the export for `workout_id`, or null. Save via
`uv run coach review record /tmp/evaluations-<id>.json --plan-id <id>`.
SQLite retains evidence, prescription snapshot, plan version and timestamp.
Already saved evaluations are never overwritten. Fetching or discussing an
activity alone does not mark it reviewed. Save small batches on long reviews
so a later interruption does not lose finished work.

Read back with `review list`. Report newly evaluated, previously evaluated
and skipped, and still pending counts, with brief per-activity verdicts and
meaningful trends. When nothing is new, do not repeat old assessments.
Suggest `/refine <id>` when evidence warrants changing the program.
