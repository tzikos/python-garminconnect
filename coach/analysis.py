"""Longitudinal activity store and derived performance markers.

Garmin calls here are read-only. Every activity is stored with its full
sample streams; metrics are derived from what was stored, so changing a
formula only needs `coach analysis recompute`, never a refetch.

Stream metrics work on 60 s bins (time-weighted means). A bin counts as
"moving" when at least 80% of it was above walking speed, which removes
traffic-light stops on rides and standing breaks on runs. The first 15
moving minutes are warm-up (HR is still climbing, which would flatter
efficiency) and are excluded from every efficiency-based metric; sessions
with under 10 moving minutes left after that get no efficiency at all.
"""

from __future__ import annotations

import json
import zlib
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, pstdev
from typing import Any

from sqlalchemy import func, select

from coach.db import session
from coach.models import Activity, WellnessDay

METRICS_VERSION = 4
BIN_S = 60
WARMUP_BINS = 15  # moving minutes skipped before any efficiency measure
BASELINE_BINS = 10  # minutes 15-25: reference for drift onset and GCT creep
MIN_CORE_BINS = 10  # post-warm-up minutes needed to report efficiency
DRIFT_THRESHOLD = 0.03  # EF drop vs. baseline that marks drift onset
MOVING_SPEED = 0.5  # m/s
DRIFT_PERSIST = 5  # consecutive minutes below threshold before calling onset
WORKOUT_LAPS = {"WARMUP", "ACTIVE", "RECOVERY", "REST", "COOLDOWN"}
# Interval detection works on lap paces, so freestyle sessions with manual
# laps count too (Garmin labels those, and every auto-lap, "INTERVAL").
REP_SPEED_RATIO = 1.25  # work lap at least 25% faster than the lap after it
REP_WORK_S = (30, 600)
REP_RECOVERY_S = (20, 600)  # min skips stray lap presses; max lets a cool-down count
MIN_REPS = 3

RUN_TYPES = {"running", "trail_running", "treadmill_running", "track_running"}
RIDE_TYPES = {
    "cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
    "indoor_cycling",
    "virtual_ride",
    "e_bike_fitness",
    "e_bike_mountain",
}


def sport_group(type_key: str) -> str:
    """Collapse Garmin's activity subtypes into the sports we trend."""
    if type_key in RUN_TYPES:
        return "running"
    if type_key in RIDE_TYPES:
        return "cycling"
    return type_key


# ---------------------------------------------------------------- streams


def pack(details: dict[str, Any]) -> bytes:
    return zlib.compress(json.dumps(details).encode(), 6)


def unpack(blob: bytes | None) -> dict[str, Any] | None:
    return json.loads(zlib.decompress(blob)) if blob else None


def columns(details: dict[str, Any] | None) -> dict[str, list[Any]]:
    """Turn Garmin's row-per-sample payload into {metric key: values}."""
    if not details:
        return {}
    index = {d["key"]: d["metricsIndex"] for d in details.get("metricDescriptors", [])}
    rows = [r.get("metrics") or [] for r in details.get("activityDetailMetrics", [])]
    return {
        key: [row[i] if i < len(row) else None for row in rows]
        for key, i in index.items()
    }


_BIN_FIELDS = {
    "hr": "directHeartRate",
    "speed": "directSpeed",
    "gap": "directGradeAdjustedSpeed",
    "power": "directPower",
    "gct": "directGroundContactTime",
    "cadence": "directDoubleCadence",  # steps/min; directRunCadence is one leg
}


def bins(cols: dict[str, list[Any]], width: int = BIN_S) -> list[dict[str, Any]]:
    """Time-weighted means per `width` seconds of timer time."""
    t = cols.get("sumDuration") or []
    if not t:
        return []
    n = len(t)
    series = {
        name: cols.get(key) or [None] * n
        for name, key in {
            **_BIN_FIELDS,
            "_speed": "directSpeed",
            "dist": "sumDistance",
            "elev": "directElevation",
        }.items()
    }
    out: dict[int, dict[str, Any]] = {}
    prev = 0.0
    for i, ti in enumerate(t):
        if ti is None:
            continue
        dt = min(max(ti - prev, 0.0), 10.0)  # a gap is a pause, not 10 min of data
        prev = ti
        if dt == 0:
            continue
        b = out.setdefault(
            int(ti // width),
            {"minute": int(ti // width) * width / 60, "secs": 0.0, "moving": 0.0, "_w": {}},
        )
        b["secs"] += dt
        speed = series["_speed"][i]
        if speed is not None and speed > MOVING_SPEED:
            b["moving"] += dt
        for name in _BIN_FIELDS:
            v = series[name][i]
            if v is not None:
                acc = b["_w"].setdefault(name, [0.0, 0.0])
                acc[0] += v * dt
                acc[1] += dt
        for name in ("dist", "elev"):
            if series[name][i] is not None:
                b[name] = series[name][i]
    result = []
    for k in sorted(out):
        b = out[k]
        for name, (total, w) in b.pop("_w").items():
            b[name] = total / w if w else None
        result.append(b)
    return result


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return fmean(vals) if vals else None


def _ratio(rows: list[dict[str, Any]], key: str) -> float | None:
    """Efficiency factor: mean output / mean HR over the same bins."""
    out, hr = _mean(rows, key), _mean(rows, "hr")
    return out / hr if out and hr else None


def stream_metrics(cols: dict[str, list[Any]], sport: str) -> dict[str, Any]:
    """Efficiency, decoupling, drift onset, steadiness and GCT creep."""
    full = [b for b in bins(cols) if b["secs"] >= BIN_S * 0.8]
    moving = [
        b for b in full if b["moving"] >= b["secs"] * 0.8 and b.get("hr") and b.get("speed")
    ]
    if not moving:
        return {}
    basis = "gap" if sport == "running" and _mean(moving, "gap") else "speed"
    core = moving[WARMUP_BINS:]
    m: dict[str, Any] = {"ef_basis": basis, "moving_minutes_analyzed": len(core)}
    if len(core) < MIN_CORE_BINS:
        return m  # too short to measure past the warm-up; no warm-up-biased EF
    m |= {
        "ef": _ratio(core, basis),
        "ef_power": _ratio(core, "power"),
    }
    speeds = [b[basis] for b in core if b.get(basis)]
    if len(speeds) >= 5:
        m["pace_cv"] = pstdev(speeds) / fmean(speeds)
    hrs = [b["hr"] for b in core]
    if len(hrs) >= 5:
        m["hr_cv"] = pstdev(hrs) / fmean(hrs)

    if len(core) >= 20:
        h1, h2 = core[: len(core) // 2], core[len(core) // 2 :]
        e1, e2 = _ratio(h1, basis), _ratio(h2, basis)
        if e1 and e2:
            m["decoupling_pct"] = (e1 - e2) / e1 * 100
        p1, p2 = _ratio(h1, "power"), _ratio(h2, "power")
        if p1 and p2:
            m["decoupling_power_pct"] = (p1 - p2) / p1 * 100
        m["hr_drift_bpm"] = _mean(h2, "hr") - _mean(h1, "hr")
        s1, s2 = _mean(h1, basis), _mean(h2, basis)
        m["speed_change_pct"] = (s2 - s1) / s1 * 100 if s1 and s2 else None

    # Drift onset: first minute whose 5-min rolling EF stays more than 3%
    # under the min 15-25 baseline for DRIFT_PERSIST minutes in a row.
    # ponytail: assumes a steady target; on intervals it is noise, which is
    # why pace_cv and intervals travel alongside it.
    base_end = WARMUP_BINS + BASELINE_BINS
    if len(moving) >= base_end + 10:
        base = _ratio(moving[WARMUP_BINS:base_end], basis)
        m["drift_checked_minutes"] = moving[-1]["minute"] + 1
        m["drift_onset_min"] = m["drift_onset_km"] = None
        below = [
            (ef := _ratio(moving[k - 4 : k + 1], basis)) is not None
            and base is not None
            and ef < base * (1 - DRIFT_THRESHOLD)
            for k in range(len(moving))
        ]
        # first window that lies wholly after the baseline
        for k in range(base_end + 4, len(moving) - DRIFT_PERSIST + 1):
            if all(below[k : k + DRIFT_PERSIST]):
                m["drift_onset_min"] = moving[k]["minute"] + 1
                d = moving[k].get("dist")
                m["drift_onset_km"] = d / 1000 if d is not None else None
                break

    if len(moving) >= base_end + 20:
        g1, g2 = _mean(moving[WARMUP_BINS:base_end], "gct"), _mean(moving[-10:], "gct")
        if g1 and g2:
            m.update(gct_start=g1, gct_end=g2, gct_delta_ms=g2 - g1)
    pc = [v for v in cols.get("directPerformanceCondition") or [] if v is not None]
    if pc:
        m.update(perf_condition_first=pc[0], perf_condition_last=pc[-1])
    return m


def _gmt_ms(text: str) -> float:
    return (
        datetime.fromisoformat(text.replace(" ", "T")).replace(tzinfo=timezone.utc).timestamp()
        * 1000
    )


def _lap_speed(lap: dict[str, Any]) -> float:
    # Raw speed: grade-adjusted speed is inflated on slow jog/standing laps,
    # which hides the work/recovery contrast.
    return lap.get("averageSpeed") or 0.0


def interval_reps(laps: dict[str, Any] | None) -> list[tuple[dict, dict]]:
    """(work lap, recovery lap) pairs: a short lap clearly faster than the next.

    ponytail: lap-based, so a fartlek with no lap presses is not detected.
    """
    lap_list = (laps or {}).get("lapDTOs") or []
    reps = []
    for work, rec in zip(lap_list, lap_list[1:]):
        work_s, rec_s = work.get("duration") or 0, rec.get("duration") or 0
        if (
            REP_WORK_S[0] <= work_s <= REP_WORK_S[1]
            and REP_RECOVERY_S[0] <= rec_s <= REP_RECOVERY_S[1]
            and _lap_speed(work) >= REP_SPEED_RATIO * max(_lap_speed(rec), 0.1)
        ):
            reps.append((work, rec))
    return reps


def hr_recovery(cols: dict[str, list[Any]], laps: dict[str, Any] | None) -> list[float]:
    """HR drop 60 s after each interval rep whose recovery lasts at least 55 s."""
    ts, hr = cols.get("directTimestamp") or [], cols.get("directHeartRate") or []
    pts = [(t, h) for t, h in zip(ts, hr) if t is not None and h is not None]
    reps = interval_reps(laps)
    if not pts or len(reps) < MIN_REPS:
        return []

    def hr_at(ms: float) -> float | None:
        t, h = min(pts, key=lambda p: abs(p[0] - ms))
        return h if abs(t - ms) <= 5000 else None

    drops = []
    for lap, nxt in reps:
        if (nxt.get("duration") or 0) >= 55 and lap.get("startTimeGMT"):
            end = _gmt_ms(lap["startTimeGMT"]) + lap["duration"] * 1000
            # Peak of the last 5 s: lap boundaries and HR lag blur the exact end.
            a = max((h for t, h in pts if end - 5000 <= t <= end), default=None)
            b = hr_at(end + 60_000)
            if a is not None and b is not None:
                drops.append(a - b)
    return drops


def _f_to_c(f: float | None) -> float | None:
    return (f - 32) * 5 / 9 if f is not None else None


def compute_metrics(
    summary: dict[str, Any],
    laps: dict[str, Any] | None,
    weather: dict[str, Any] | None,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    """Everything the analysis page plots, for one activity."""
    s = summary
    type_key = (s.get("activityType") or {}).get("typeKey", "other")
    sport = sport_group(type_key)
    dist = s.get("distance") or 0
    lap_list = (laps or {}).get("lapDTOs") or []
    m: dict[str, Any] = {
        "type": type_key,
        "duration_s": s.get("duration"),
        "moving_s": s.get("movingDuration"),
        "distance_m": dist or None,
        "avg_hr": s.get("averageHR"),
        "max_hr": s.get("maxHR"),
        "avg_speed": s.get("averageSpeed"),
        "avg_gap_speed": s.get("avgGradeAdjustedSpeed"),
        "elev_gain_m": s.get("elevationGain"),
        "elev_per_km": (s.get("elevationGain") or 0) / (dist / 1000) if dist > 500 else None,
        "avg_power": s.get("avgPower"),
        "norm_power": s.get("normPower"),
        "cadence": s.get("averageRunningCadenceInStepsPerMinute")
        or s.get("averageBikingCadenceInRevPerMinute"),
        "stride_cm": s.get("avgStrideLength"),
        "gct_ms": s.get("avgGroundContactTime"),
        "vert_ratio": s.get("avgVerticalRatio"),
        "vert_osc_cm": s.get("avgVerticalOscillation"),
        "vo2max": s.get("vO2MaxValue"),
        "load": s.get("activityTrainingLoad"),
        "aerobic_te": s.get("aerobicTrainingEffect"),
        "anaerobic_te": s.get("anaerobicTrainingEffect"),
        "te_label": s.get("trainingEffectLabel"),
        "hr_zones_s": [s.get(f"hrTimeInZone_{i}") or 0 for i in range(1, 6)],
        "body_battery_delta": s.get("differenceBodyBattery"),
        # Executed as a Garmin workout (easy runs from the plan included).
        "workout": any(lap.get("intensityType") in WORKOUT_LAPS for lap in lap_list),
        "interval_reps": len(reps := interval_reps(laps)),
        "intervals": len(reps) >= MIN_REPS,
        "laps": len(lap_list) or s.get("lapCount"),
    }
    if weather:
        # ponytail: Garmin's weather endpoint answers in °F and mph here;
        # convert if a payload ever arrives metric.
        m["temp_c"] = _f_to_c(weather.get("temp"))
        m["dew_point_c"] = _f_to_c(weather.get("dewPoint"))
        m["humidity"] = weather.get("relativeHumidity")
        m["wind_kph"] = (
            weather["windSpeed"] * 1.609 if weather.get("windSpeed") is not None else None
        )
    cols = columns(details)
    m.update(stream_metrics(cols, sport))
    drops = hr_recovery(cols, laps)
    if drops:
        m.update(hrr60_mean=fmean(drops), hrr60_n=len(drops), hrr60=drops)
    return m


def _rebuild(row: Activity) -> None:
    row.metrics = compute_metrics(row.summary, row.laps, row.weather, unpack(row.details))
    row.metrics_version = METRICS_VERSION


# ------------------------------------------------------------------- sync


def ingest(api: Any, summary: dict[str, Any]) -> Activity:
    """Fetch splits, weather and full-resolution streams for one activity."""
    activity_id = int(summary["activityId"])
    errors: list[str] = []
    fetched: dict[str, Any] = {}
    for key, call in (
        ("laps", lambda: api.get_activity_splits(str(activity_id))),
        ("weather", lambda: api.get_activity_weather(str(activity_id))),
        # maxpoly=0: lat/lon already sit in the sample streams.
        ("details", lambda: api.get_activity_details(str(activity_id), 100_000, 0)),
    ):
        try:
            fetched[key] = call()
        except Exception as exc:  # noqa: BLE001 - keep what we have, retry next sync
            if type(exc).__name__ == "GarminConnectTooManyRequestsError":
                raise
            errors.append(f"{key}: {exc}")
            fetched[key] = None
    with session() as s:
        row = s.get(Activity, activity_id) or Activity(activity_id=activity_id)
        row.date = date.fromisoformat(summary["startTimeLocal"][:10])
        row.sport = sport_group((summary.get("activityType") or {}).get("typeKey", "other"))
        row.name = summary.get("activityName") or ""
        row.summary = summary
        row.laps = fetched["laps"]
        row.weather = fetched["weather"]
        row.details = pack(fetched["details"]) if fetched["details"] else None
        row.errors = errors
        row.fetched_at = datetime.now(timezone.utc)
        _rebuild(row)
        s.add(row)
    return row


def _wellness_metrics(us: dict | None, hrv: dict | None, sleep: dict | None) -> dict:
    us, hs = us or {}, (hrv or {}).get("hrvSummary") or {}
    dto = (sleep or {}).get("dailySleepDTO") or {}
    baseline = hs.get("baseline") or {}
    return {
        "resting_hr": us.get("restingHeartRate"),
        "resting_hr_7d": us.get("lastSevenDaysAvgRestingHeartRate"),
        "hrv_night": hs.get("lastNightAvg"),
        "hrv_week": hs.get("weeklyAvg"),
        "hrv_status": hs.get("status"),
        "hrv_baseline_low": baseline.get("balancedLow"),
        "hrv_baseline_high": baseline.get("balancedUpper"),
        "sleep_score": ((dto.get("sleepScores") or {}).get("overall") or {}).get("value"),
        "sleep_h": dto["sleepTimeSeconds"] / 3600 if dto.get("sleepTimeSeconds") else None,
        "stress_avg": us.get("averageStressLevel"),
        "bb_high": us.get("bodyBatteryHighestValue"),
        "bb_low": us.get("bodyBatteryLowestValue"),
        "bb_wake": us.get("bodyBatteryAtWakeTime"),
    }


def ingest_wellness(api: Any, day: date) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key, method in (
        ("summary", "get_user_summary"),
        ("hrv", "get_hrv_data"),
        ("sleep", "get_sleep_data"),
    ):
        try:
            raw[key] = getattr(api, method)(day.isoformat())
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "GarminConnectTooManyRequestsError":
                raise
            raw[key] = None
            raw.setdefault("errors", []).append(f"{key}: {exc}")
    metrics = _wellness_metrics(raw["summary"], raw["hrv"], raw["sleep"])
    with session() as s:
        row = s.get(WellnessDay, day) or WellnessDay(date=day)
        row.metrics, row.raw = metrics, raw
        row.fetched_at = datetime.now(timezone.utc)
        s.add(row)
    return metrics


def sync(
    api: Any,
    *,
    since: date | None = None,
    today: date | None = None,
    force: bool = False,
    wellness: bool = True,
) -> dict[str, Any]:
    """Store every activity and wellness day not yet held locally.

    Default window: everything on the first run, then from a week before
    the newest stored activity so late uploads and edits are caught.
    """
    today = today or date.today()
    with session() as s:
        last_act = s.scalar(select(func.max(Activity.date)))
        last_day = s.scalar(select(func.max(WellnessDay.date)))
        first_act = s.scalar(select(func.min(Activity.date)))
        # Rows with fetch errors are retried; clean ones are never refetched.
        complete = {a for a, err in s.execute(select(Activity.activity_id, Activity.errors)) if not err}
    start = since or (last_act - timedelta(days=7) if last_act else date(2000, 1, 1))
    result: dict[str, Any] = {"from": start.isoformat(), "stored": [], "skipped": 0, "errors": []}
    try:
        acts = api.get_activities_by_date(start.isoformat(), today.isoformat(), sortorder="asc")
        for summary in acts:
            if int(summary["activityId"]) in complete and not force:
                result["skipped"] += 1
                continue
            row = ingest(api, summary)
            result["stored"].append(
                {"activity_id": row.activity_id, "date": row.date.isoformat(), "sport": row.sport}
            )
            result["errors"] += [f"{row.activity_id} {e}" for e in row.errors]

        if wellness:
            first = since or (
                last_day - timedelta(days=1) if last_day else first_act or start
            )
            if first == date(2000, 1, 1):  # first run: start at the oldest activity
                first = min((date.fromisoformat(a["startTimeLocal"][:10]) for a in acts), default=today)
            day, n = first, 0
            while day <= today:
                ingest_wellness(api, day)
                day += timedelta(days=1)
                n += 1
            result["wellness_days"] = n
    except Exception as exc:  # noqa: BLE001 - progress so far is already committed
        result["errors"].append(f"stopped early: {exc}")
    return result


def recompute() -> int:
    """Rebuild metrics from stored data after a formula change."""
    with session() as s:
        rows = s.scalars(select(Activity)).all()
        for row in rows:
            _rebuild(row)
        return len(rows)


# ------------------------------------------------------------------ query


def list_activities(start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    q = select(Activity).order_by(Activity.date, Activity.activity_id)
    if start:
        q = q.where(Activity.date >= start)
    if end:
        q = q.where(Activity.date <= end)
    with session() as s:
        return [
            {
                "activity_id": r.activity_id,
                "date": r.date.isoformat(),
                "start_local": r.summary.get("startTimeLocal"),
                "sport": r.sport,
                "name": r.name,
                "has_streams": r.details is not None,
                "metrics": r.metrics,
            }
            for r in s.scalars(q)
        ]


def list_wellness(start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    q = select(WellnessDay).order_by(WellnessDay.date)
    if start:
        q = q.where(WellnessDay.date >= start)
    if end:
        q = q.where(WellnessDay.date <= end)
    with session() as s:
        return [{"date": r.date.isoformat(), **r.metrics} for r in s.scalars(q)]


def activity_streams(activity_id: int, width: int = 15) -> dict[str, Any] | None:
    """Binned streams for the drill-down chart."""
    with session() as s:
        row = s.get(Activity, activity_id)
        if row is None:
            return None
        cols = columns(unpack(row.details))
        return {
            "activity_id": activity_id,
            "name": row.name,
            "date": row.date.isoformat(),
            "sport": row.sport,
            "metrics": row.metrics,
            "points": [
                {k: v for k, v in b.items() if k not in ("secs", "moving")}
                for b in bins(cols, width)
            ],
        }
