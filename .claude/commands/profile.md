# /profile - View or update the athlete profile

`$ARGUMENTS` = what to change ("5k is now 21:40", "max HR 192"). Empty just
shows the profile.

```bash
uv run coach profile show
uv run coach profile set --name "..." --recent-5k 22:30 \
    --threshold-hr 170 --max-hr 190 --weekly-hours 6 --notes "..."
```

`--recent-5k` takes `mm:ss` or seconds. Only the flags you pass are changed.

The profile holds what is true **across** plans: name, Garmin email, recent
5k, HR anchors, weekly hours, enabled sports and per-sport benchmarks.
Race-specific facts belong in a plan, not here.

When the 5k time changes, say what it does to the training paces — that is
the number every run in every future plan is derived from:

```bash
uv run python -c "
from coach.tools import compute_pace_zones, format_pace
for name, r in compute_pace_zones(1300).items():
    print(name, format_pace(r['min_per_km']), '-', format_pace(r['max_per_km']))
"
```

Existing plans keep their old paces. Offer `/adjust` if a meaningful fitness
change should propagate into a plan already in flight.
