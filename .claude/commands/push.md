# /push - Send a plan to the Garmin watch

`$ARGUMENTS` = the plan id. Ask if it is missing and more than one plan exists.

Read the `garmin-sync` skill first.

## Steps

1. Show what is about to happen — this is the step that changes the watch:
   ```bash
   uv run coach sync push --plan-id <id> --dry-run
   ```
2. Read the list back: how many workouts, over what date range. Check the
   first date is not in the past.
3. **Ask the athlete to confirm.** Then, and only then:
   ```bash
   uv run coach sync push --plan-id <id> --yes
   ```
4. Report the real numbers: `Uploaded / Skipped / Failed`. If anything
   failed, name each workout and what it said — do not call a push with
   failures a success. Re-running is safe; it skips what already uploaded.

`Skipped` usually means those workouts were already on the watch. Say so
rather than leaving it looking like something went wrong.

Finish with: the plan is on the watch once Garmin Connect next syncs.
