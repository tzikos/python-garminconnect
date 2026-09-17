# /unpush - Remove an uploaded plan from Garmin

`$ARGUMENTS` = the plan id.

Read the `garmin-sync` skill first. This deletes workouts from Garmin
Connect — it is the destructive direction.

## Steps

1. Show what is uploaded and will be removed:
   ```bash
   uv run coach plan show <id>
   ```
2. Say plainly what will disappear from the watch, and how many workouts.
3. **Ask the athlete to confirm.** Then:
   ```bash
   uv run coach sync unpush --plan-id <id> --yes
   ```
4. Report removed vs failed. The local plan is untouched — the rows go back
   to `status=planned` and can be pushed again.

Reach for this when: the plan needs editing (import refuses to overwrite an
uploaded plan), the athlete wants the watch cleared, or a plan is being
deleted — `coach plan delete` does **not** clean up Garmin, so unpush first
or the workouts are stranded on the watch.
