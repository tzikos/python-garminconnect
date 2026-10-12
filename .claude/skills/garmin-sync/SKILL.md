---
name: garmin-sync
description: Getting workouts onto and off the Garmin watch — what push and unpush actually do, workout status transitions, dry runs, authentication, and the failure modes worth recognising. Use before or while running `coach sync push` / `sync unpush`, and when an upload partly fails or a workout does not appear on the watch.
---

# Pushing to Garmin

These two commands change what the athlete sees on their watch.
`coach review fetch` also contacts Garmin, but only reads activity evidence.

```bash
uv run coach sync push --plan-id 3 --dry-run   # list what would upload, no API calls
uv run coach sync push --plan-id 3 --yes       # upload + schedule
uv run coach sync unpush --plan-id 3 --yes     # remove from Garmin
```

For `/refine`, use `--from-date YYYY-MM-DD` on both push and unpush to limit
operations to the future period. Unpush also supports `--dry-run`. It removes
all uploaded sessions on/after that cutoff, including unchanged ones that will
need re-uploading. Never use an unbounded sync to apply a future-only revision.

`--yes` exists because the plain command asks for confirmation on a TTY,
which aborts when a tool runs it. **Ask the athlete before passing `--yes`** —
you are taking their confirmation, not skipping it.

## What push does

For each workout with `status=planned`, in date order:

1. Builds the Garmin workout from `primitive_type` + `primitive_params`.
2. Uploads it, storing the returned `garmin_workout_id`.
3. Schedules it on its date, storing `garmin_schedule_id`.
4. Flips the row to `status=uploaded`.

So push is **resumable and idempotent**: already-uploaded workouts are
skipped, and re-running after a partial failure uploads only what is left.
The result line reports `Uploaded / Skipped / Failed`, and each failure names
its workout id. Report failures individually — a plan is not "pushed" because
the command exited 0 with three failures in the output.

`unpush` is the mirror: it deletes the scheduled occurrence and the workout
from Garmin, clears both ids, and returns the row to `status=planned`.

## Status transitions

```
planned ──push──> uploaded ──unpush──> planned
```

- `coach plan import --plan-id N` **refuses** to overwrite a plan holding
  uploaded workouts. Unpush first, edit, push again.
- `coach plan delete` only removes the local rows — it does **not** clean up
  Garmin. Always unpush before deleting, or the workouts are orphaned on the
  watch with nothing left locally to remove them with.

## Authentication

The Garmin client reads the email from the stored profile and the password
from the OS keychain, caching session tokens in `~/.garmin-coach/garth` (or
`$GARMIN_COACH_HOME/garth` when configured).

```bash
uv run coach secrets set-garmin-password    # prompts; never pass on argv
```

Auth failures usually mean expired tokens or a changed password; re-running
`set-garmin-password` and retrying fixes most of them. Garmin also rate-limits
and occasionally requires MFA — if a push fails with an auth error mid-way,
the already-uploaded workouts stay uploaded, so just re-run it.

## Before you push

1. `coach plan show <id>` and read the weeks back to the athlete.
2. `--dry-run` for anything large or unfamiliar.
3. Check the dates — a plan whose first week is in the past schedules
   workouts on days that have already gone.
4. Then ask, then `--yes`.

## When a workout does not appear on the watch

Check in this order: it uploaded (`Uploaded:` count and `garmin_workout_id`
set), it was scheduled on the date you expect, the watch has synced with
Garmin Connect at all since, and the date is inside the window the watch
displays. Scheduling is what puts a workout on the calendar — an uploaded but
unscheduled workout exists in Garmin Connect and never reaches the watch.
