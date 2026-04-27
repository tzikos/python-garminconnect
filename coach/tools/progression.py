"""Weekly volume progression with deloads and taper.

Used by the LLM (or a higher planner) to lay out per-week volume targets
across a plan. Returns one number per week; assigning that volume to
specific workouts is a separate concern.

Rules encoded:
- Build phase: monotonic-ish ramp from `start_km` toward `peak_km`.
- Every 4th week of the build is a deload at ~70% of the previous week.
- Last `taper_weeks` weeks taper from peak down to ~50%.
- The last build week (immediately before taper) is always a peak week,
  never a deload — protects the peak from being clipped by the deload rule.
"""

from __future__ import annotations


def _taper_schedule(taper_weeks: int) -> list[float]:
    """Fractions of peak for each taper week, in order."""
    if taper_weeks == 1:
        return [0.50]
    if taper_weeks == 2:
        return [0.70, 0.50]
    if taper_weeks == 3:
        return [0.80, 0.65, 0.50]
    # general: linear from 0.85 down to 0.50
    return [0.85 - (0.35 * i / (taper_weeks - 1)) for i in range(taper_weeks)]


def weekly_volume_progression(
    start_km: float,
    peak_km: float,
    weeks: int,
    taper_weeks: int = 2,
) -> list[float]:
    """Return planned weekly volumes (km), one per week."""
    if weeks < 3:
        raise ValueError("weeks must be >= 3")
    if taper_weeks < 1 or taper_weeks >= weeks:
        raise ValueError("taper_weeks must be >= 1 and < weeks")
    if peak_km < start_km:
        raise ValueError("peak_km must be >= start_km")

    build_n = weeks - taper_weeks

    def is_deload(w: int) -> bool:
        # 0-indexed week within build phase; deload every 4th week,
        # but never the first or last build week.
        return (w + 1) % 4 == 0 and 0 < w < build_n - 1

    progression_indices = [w for w in range(build_n) if not is_deload(w)]
    n_prog = len(progression_indices)

    volumes: list[float] = [0.0] * weeks
    for i, w in enumerate(progression_indices):
        if n_prog == 1:
            volumes[w] = peak_km
        else:
            t = i / (n_prog - 1)
            volumes[w] = start_km + t * (peak_km - start_km)

    # Fill deload weeks at 70% of the previous progression week.
    for w in range(build_n):
        if volumes[w] == 0:
            prev_v = next(
                (volumes[i] for i in range(w - 1, -1, -1) if volumes[i] > 0),
                start_km,
            )
            volumes[w] = prev_v * 0.70

    peak = max(volumes[:build_n])
    for i, frac in enumerate(_taper_schedule(taper_weeks)):
        volumes[build_n + i] = peak * frac

    return [round(v, 1) for v in volumes]
