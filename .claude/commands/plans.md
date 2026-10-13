# /plans - List plans, or show one

`$ARGUMENTS` = a plan id to show in full. Empty lists them all.

```bash
uv run coach plan list                # id, name, dates, status, workout count
uv run coach plan show <id>           # every workout, by date
```

When showing a plan, don't just dump the table — read it back the way a coach
would: weeks with their themes and volumes, where the hard sessions fall, how
the taper lands relative to race day. Call out anything that looks wrong:
a week whose volume jumps more than ~10%, two hard sessions back to back, a
long run on a day the athlete said they can't train, or dates already in the
past.

Say which workouts are already `uploaded` and which are still `planned` —
that is the difference between what is on the watch and what is only local.

End by naming the next move: `/push`, `/adjust`, or nothing at all.
