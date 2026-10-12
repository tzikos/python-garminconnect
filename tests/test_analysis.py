"""Offline checks for derived activity metrics."""

from coach.analysis import compute_metrics

T0 = 1_790_000_000_000  # ms epoch; 2026-09-21T14:13:20Z
KEYS = [
    "sumDuration",
    "directTimestamp",
    "directHeartRate",
    "directSpeed",
    "directGradeAdjustedSpeed",
    "directGroundContactTime",
    "sumDistance",
]


def _details(hr, speed, gct):
    rows = [
        {"metrics": [t, T0 + t * 1000, hr(t), speed(t), speed(t), gct(t), speed(t) * t]}
        for t in range(1, 3601)
    ]
    return {
        "metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(KEYS)],
        "activityDetailMetrics": rows,
    }


SUMMARY = {"activityType": {"typeKey": "running"}, "distance": 10800}


def test_steady_run_has_no_drift():
    m = compute_metrics(SUMMARY, None, None, _details(lambda t: 140, lambda t: 3.0, lambda t: 260))
    assert abs(m["decoupling_pct"]) < 1e-9
    assert m["drift_onset_min"] is None and m["drift_checked_minutes"] == 60
    assert abs(m["ef"] - 3.0 / 140) < 1e-9
    assert m["gct_delta_ms"] == 0


def test_hr_creep_shows_decoupling_and_onset():
    # HR flat at 140 for 30 min, then +1 bpm/min at constant pace; GCT creeps too.
    hr = lambda t: 140 if t < 1800 else 140 + (t - 1800) / 60
    gct = lambda t: 260 + t / 360
    m = compute_metrics(SUMMARY, None, None, _details(hr, lambda t: 3.0, gct))
    assert m["decoupling_pct"] > 5
    assert m["hr_drift_bpm"] > 10
    # 3% EF drop over a 5-min window needs a mean HR ~144.3 -> ~minute 37,
    # and the drop persists from there.
    assert 35 <= m["drift_onset_min"] <= 39
    assert abs(m["gct_delta_ms"] - 35 / 6) < 0.1  # min 15-25 vs last 10


def _lap(start_s, duration, speed, kind="INTERVAL"):
    from datetime import datetime, timezone

    t = datetime.fromtimestamp(T0 / 1000 + start_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0")
    return {"intensityType": kind, "startTimeGMT": t, "duration": duration, "averageSpeed": speed}


def test_manual_lap_intervals_detected_with_hr_recovery():
    # 10 min warm-up, then 3 x (2 min fast / 2 min jog), all labelled INTERVAL.
    work = [(600 + i * 240, 600 + i * 240 + 120) for i in range(3)]
    hr = lambda t: 175 if any(a <= t < b for a, b in work) else 140
    laps = {"lapDTOs": [_lap(0, 600, 2.8)]}
    for a, _ in work:
        laps["lapDTOs"] += [_lap(a - 0, 120, 4.2), _lap(a + 120, 120, 2.6)]
    m = compute_metrics(SUMMARY, laps, None, _details(hr, lambda t: 3.0, lambda t: 260))
    assert m["intervals"] is True and m["interval_reps"] == 3 and m["workout"] is False
    assert m["hrr60"] == [35, 35, 35]


def test_autolaps_and_tempo_are_not_intervals():
    # A stray 3 s lap press after the warm-up is not a recovery.
    stray = {"lapDTOs": [_lap(0, 600, 2.8), _lap(600, 3, 1.5)]}
    assert compute_metrics(SUMMARY, stray, None, None)["interval_reps"] == 0
    easy = {"lapDTOs": [_lap(i * 360, 360, 2.8 + (i % 2) * 0.2) for i in range(8)]}
    tempo = {"lapDTOs": [_lap(0, 600, 2.8, "WARMUP")] + [_lap(600 + i * 290, 290, 3.5, "ACTIVE") for i in range(4)] + [_lap(1760, 400, 2.7, "COOLDOWN")]}
    for laps in (easy, tempo):
        m = compute_metrics(SUMMARY, laps, None, None)
        assert m["intervals"] is False
    assert compute_metrics(SUMMARY, tempo, None, None)["workout"] is True


def test_warmup_excluded_and_short_runs_get_no_ef():
    # Low HR in the first 15 min must not flatter efficiency.
    hr = lambda t: 110 if t < 900 else 150
    m = compute_metrics(SUMMARY, None, None, _details(hr, lambda t: 3.0, lambda t: 260))
    assert abs(m["ef"] - 3.0 / 150) < 1e-9

    def short(hr, speed):
        d = _details(hr, speed, lambda t: 260)
        d["activityDetailMetrics"] = d["activityDetailMetrics"][:20 * 60]
        return d

    m = compute_metrics(SUMMARY, None, None, short(lambda t: 140, lambda t: 3.0))
    assert "ef" not in m and m["moving_minutes_analyzed"] == 5
