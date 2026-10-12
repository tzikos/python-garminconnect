---
name: refine
description: Refine the remaining training program using completed Garmin workouts and saved evaluations while retaining elapsed training history. Use for /refine or evidence-based progression and recovery adjustments to an existing program.
---

# Refine from completed training

Read `../workout-design/SKILL.md` and its aerobic-training reference. This
workflow adapts future sessions to execution; `/adjust` handles a changed
race, injury constraint, travel, or other explicit goal/calendar change.

## Ground the revision

Select the program following `../evaluate/SKILL.md`, then use that workflow
to collect and evaluate new activities. Read profile, plan, saved assessments
and athlete feedback. If Garmin is unavailable, use cached evidence only
when adequate and disclose its coverage. Fetch failure is not missed training.

Assess actual volume, consistency, quality execution, long-run durability,
and recovery. Use a rolling 10–14-day window for intensity coverage and several
weeks for trends when available. Count unscheduled work and other sports in
load. Separate fatigue from calendar constraints; ask only for missing facts
that change the decision. Weak evidence can justify leaving the plan alone.

| Evidence | Consider |
|---|---|
| Consistent completion, controlled effort, good recovery | Small progression in one load dimension, anchored to actual sustainable volume |
| Repeated failed reps, fatigue or deteriorating execution | Reduce quality/volume, add recovery and investigate context |
| Missed training or a long gap | Resume below the old ramp; never cram missed sessions into the next week |
| Missing intensity exposure over 10–14 days | Rotate a suitable session into a quality slot without sacrificing recovery |
| Long-run fade in comparable conditions | Review pacing/fueling first, then gradual durability work |
| One bad session or a watch VO2 fluctuation | Usually retain the plan and collect more evidence |

## Prepare and save a concrete revision

1. Export to `/tmp/refine-plan-<id>.json`; retain its `plan_id` and `version`.
2. Choose an effective date after today, normally tomorrow, inside the plan.
   Preserve earlier workouts, completed sessions, goals, dates and taper.
   Keep unchanged prescriptions exactly as exported to preserve their IDs
   and Garmin links. Do not use `plan import --plan-id`, which replaces every
   workout row.
3. Edit the full JSON with supported primitives. Add `refinement_reason` at
   the top level identifying activity IDs/findings behind the changes.
   Recalculate future targets and cross-sport interference. In a partially
   elapsed week, consider actual load without rewriting past prescriptions.
4. Preview:
   ```bash
   uv run coach plan refine /tmp/refine-plan-<id>.json --plan-id <id> --from-date YYYY-MM-DD --dry-run
   ```
   Show concrete before/after sessions, volume and reasoning. Dry-run lists
   changed uploaded workouts that block saving. A stale version needs a fresh
   export and preview, not manually changing the version number.
5. If no changed session is uploaded, save with the same command without
   `--dry-run`. Read the plan back. This archives the prior prescription and
   reasoning, preserves past/unchanged rows, and increments the version.
   An unchanged proposal creates no version.

## If the future schedule is already on Garmin

Prepare the revision before seeking authorization for Garmin changes. Read
`../garmin-sync/SKILL.md`. Use the same cutoff throughout:

```bash
uv run coach sync unpush --plan-id <id> --from-date YYYY-MM-DD --dry-run
# After removal and re-upload of this future period are authorized:
uv run coach sync unpush --plan-id <id> --from-date YYYY-MM-DD --yes
uv run coach plan refine /tmp/refine-plan-<id>.json --plan-id <id> --from-date YYYY-MM-DD
uv run coach sync push --plan-id <id> --from-date YYYY-MM-DD --dry-run
uv run coach sync push --plan-id <id> --from-date YYYY-MM-DD --yes
```

Unpush removes **all uploaded sessions in that future period**, including
unchanged ones, which are then re-uploaded. Show that scope in the preview.
Never use unbounded push/unpush for refinement or clear IDs/statuses to bypass
the guard. If removal fails, stop before applying; retain the draft and report
affected IDs for retry. If applying or re-uploading fails, state the exact
state reached and resume there. Existing authorization for this scope need
not be asked again. Evaluation alone authorizes no Garmin writes.

Report the evidence driving changes, upcoming sessions, the draft path if
awaiting authorization, and whether the watch was updated.
