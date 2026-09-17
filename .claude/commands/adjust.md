# /adjust - Change an existing plan

`$ARGUMENTS` = the plan id and what changed ("3, injured my calf",
"2, travelling weeks 5 and 6", "1, missed the last two weeks").

Read the `workout-design` skill before editing.

## Steps

1. Read the plan as it stands:
   ```bash
   uv run coach plan show <id>
   uv run coach plan export <id> --out /tmp/plan.json
   ```
2. Understand what actually changed. Ask if it is vague — "injured" needs to
   become which body part, how bad, and whether running hurts at all.
3. Edit `/tmp/plan.json`. Change as little as the situation demands:

   | Situation | The usual response |
   |---|---|
   | Missed weeks | Re-anchor from current fitness, not the original ramp. Do not compress the plan to catch up. |
   | Injury | Drop the aggravating movement, keep the aerobic base where it is safe, rebuild volume from below. |
   | Travel / blackout | Make those weeks easy or bodyweight-only and shift the build around them. |
   | Race moved | Re-time the taper to the new date; stretch or trim the build, never the taper. |
   | Feeling flat | One extra deload beats pushing through. |

4. If the plan has uploaded workouts, `unpush` first — import refuses to
   overwrite them.
5. Re-import over the same plan so the id and history survive:
   ```bash
   uv run coach plan import /tmp/plan.json --plan-id <id>
   ```
6. Say exactly what changed, week by week, and what you deliberately left
   alone. If it was pushed before, remind them it needs `/push` again.
