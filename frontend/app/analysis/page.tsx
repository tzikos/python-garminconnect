"use client";

import { useEffect, useMemo, useState } from "react";
import { format, parseISO, startOfYear, subDays, subMonths, subWeeks, differenceInCalendarDays } from "date-fns";
import { ArrowDownRight, ArrowUpRight, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type ActivityStreams,
  type AnalysisActivity,
  type WellnessDay,
} from "@/lib/api";
import {
  DEFAULT_QUALIFIER,
  INK,
  SPORTS,
  SPORT_COLORS,
  ZONE_COLORS,
  bucketKey,
  bucketKeys,
  bucketLabel,
  disqualify,
  fmtDuration,
  fmtNum,
  fmtPace,
  loadModel,
  mean,
  median,
  speedAtHr,
  sportKey,
  type Granularity,
  type Qualifier,
} from "@/lib/analysis";
import {
  CalendarHeat,
  ChartCard,
  InfoButton,
  Legend,
  SeriesChart,
  StackedBars,
  StreamPanel,
  TrendScatter,
  type TrendPoint,
} from "@/components/analysis-charts";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PRESETS = [
  ["4w", "4 wk"],
  ["12w", "12 wk"],
  ["6m", "6 mo"],
  ["ytd", "YTD"],
  ["1y", "1 yr"],
  ["all", "All"],
] as const;
type Preset = (typeof PRESETS)[number][0] | "custom";

const RAMP = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"];
const COLOR_BY = {
  none: { label: "Sport", get: () => null, fmt: () => "" },
  temp: { label: "Temperature", get: (a: AnalysisActivity) => a.metrics.temp_c ?? null, fmt: (v: number) => `${v.toFixed(0)}°C` },
  hills: { label: "Hilliness", get: (a: AnalysisActivity) => a.metrics.elev_per_km ?? null, fmt: (v: number) => `${v.toFixed(0)} m/km` },
  duration: { label: "Duration", get: (a: AnalysisActivity) => (a.metrics.moving_s ?? 0) / 60, fmt: (v: number) => `${v.toFixed(0)} min` },
  hr: { label: "Avg HR", get: (a: AnalysisActivity) => a.metrics.avg_hr, fmt: (v: number) => `${v.toFixed(0)} bpm` },
} as const;
type ColorBy = keyof typeof COLOR_BY;

const iso = (d: Date) => format(d, "yyyy-MM-dd");
const ms = (d: string) => parseISO(d).getTime();

function Seg<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-md border bg-card p-0.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            "px-2.5 py-1 text-xs rounded-[5px] transition-colors",
            v === value ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Kpi({
  label,
  value,
  delta,
  goodWhenUp = true,
  sub,
}: {
  label: string;
  value: string;
  delta?: number | null;
  goodWhenUp?: boolean;
  sub?: string;
}) {
  const show = delta != null && isFinite(delta) && Math.abs(delta) >= 0.5;
  const good = show && (delta! > 0) === goodWhenUp;
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold tabular-nums mt-1">{value}</p>
        <p className="text-xs mt-1 h-4 flex items-center gap-1 text-muted-foreground">
          {show && (
            <span className={cn("flex items-center gap-0.5 tabular-nums", good ? "text-[#0ca30c]" : "text-[#ec835a]")}>
              {delta! > 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {Math.abs(delta!).toFixed(0)}%
            </span>
          )}
          {show ? "vs prev." : sub}
        </p>
      </CardContent>
    </Card>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  fmt,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  fmt: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground min-w-[150px]">
      <span className="flex justify-between">
        {label} <span className="text-foreground tabular-nums">{fmt(value)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-[#3987e5]"
      />
    </label>
  );
}

export default function AnalysisPage() {
  const [acts, setActs] = useState<AnalysisActivity[] | null>(null);
  const [wellness, setWellness] = useState<WellnessDay[]>([]);
  const [gran, setGran] = useState<Granularity>("week");
  const [preset, setPreset] = useState<Preset>("12w");
  const [custom, setCustom] = useState({ from: "", to: "" });
  const [sports, setSports] = useState<Set<string>>(new Set(SPORTS));
  const [effSport, setEffSport] = useState<"running" | "cycling">("running");
  const [q, setQ] = useState<Qualifier>(DEFAULT_QUALIFIER);
  const [refHr, setRefHr] = useState(145);
  const [colorBy, setColorBy] = useState<ColorBy>("temp");
  const [pickedDay, setPickedDay] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [streams, setStreams] = useState<ActivityStreams | null>(null);

  useEffect(() => {
    Promise.all([api.analysis.activities(), api.analysis.wellness()])
      .then(([a, w]) => {
        setActs(a);
        setWellness(w);
      })
      .catch((e) => {
        toast.error(`Failed to load analysis: ${e.detail ?? e.message}`);
        setActs([]);
      });
  }, []);

  useEffect(() => {
    if (selected == null) return setStreams(null);
    setStreams(null);
    api.analysis
      .streams(selected)
      .then(setStreams)
      .catch((e) => toast.error(`Could not load streams: ${e.detail ?? e.message}`));
  }, [selected]);

  const today = iso(new Date());
  const { from, to } = useMemo(() => {
    const now = new Date();
    const first = acts?.[0]?.date ?? today;
    switch (preset) {
      case "4w": return { from: iso(subWeeks(now, 4)), to: today };
      case "12w": return { from: iso(subWeeks(now, 12)), to: today };
      case "6m": return { from: iso(subMonths(now, 6)), to: today };
      case "ytd": return { from: iso(startOfYear(now)), to: today };
      case "1y": return { from: iso(subMonths(now, 12)), to: today };
      case "all": return { from: first, to: today };
      default: return { from: custom.from || first, to: custom.to || today };
    }
  }, [preset, custom, acts, today]);

  const v = useMemo(() => {
    if (!acts) return null;
    const bySport = acts.filter((a) => sports.has(sportKey(a.sport)));
    const inRange = bySport.filter((a) => a.date >= from && a.date <= to);
    const span = differenceInCalendarDays(parseISO(to), parseISO(from)) + 1;
    const prevFrom = iso(subDays(parseISO(from), span));
    const prevTo = iso(subDays(parseISO(from), 1));
    const prev = bySport.filter((a) => a.date >= prevFrom && a.date <= prevTo);
    const keys = bucketKeys(from, to, gran);

    // Volume & intensity per bucket
    const blank = () => Object.fromEntries(SPORTS.map((s) => [s, 0]));
    const vol = new Map(keys.map((k) => [k, { label: bucketLabel(k, gran), ...blank() } as Record<string, any>]));
    const zones = new Map(keys.map((k) => [k, { label: bucketLabel(k, gran), low: 0, moderate: 0, high: 0 } as Record<string, any>]));
    for (const a of inRange) {
      const k = bucketKey(a.date, gran);
      const row = vol.get(k);
      if (row) row[sportKey(a.sport)] += (a.metrics.duration_s ?? 0) / 3600;
      const z = a.metrics.hr_zones_s ?? [];
      const zr = zones.get(k);
      if (zr && z.length) {
        zr.low += (z[0] + z[1]) / 3600;
        zr.moderate += z[2] / 3600;
        zr.high += (z[3] + z[4]) / 3600;
      }
    }

    // Efficiency family: one sport, qualifier decides trend vs. ghost.
    const eff = inRange.filter((a) => a.sport === effSport && a.metrics.ef);
    const effPrev = prev.filter((a) => a.sport === effSport && a.metrics.ef && !disqualify(a, q));
    const cb = COLOR_BY[colorBy];
    const cvals = eff.map((a) => cb.get(a)).filter((x): x is number => x != null);
    const [cmin, cmax] = [Math.min(...cvals), Math.max(...cvals)];
    const colorOf = (a: AnalysisActivity) => {
      const val = cb.get(a);
      if (colorBy === "none" || val == null || !isFinite(cmin)) return SPORT_COLORS[sportKey(a.sport)];
      const t = cmax > cmin ? (val - cmin) / (cmax - cmin) : 0.5;
      return RAMP[Math.min(RAMP.length - 1, Math.floor(t * RAMP.length))];
    };
    const speedFmt = (s: number) => (effSport === "running" ? `${fmtPace(1000 / s)}/km` : `${(s * 3.6).toFixed(1)} km/h`);
    const tipFor = (a: AnalysisActivity): [string, string][] => {
      const m = a.metrics;
      const speed = m.ef_basis === "gap" ? m.avg_gap_speed : m.avg_speed;
      return [
        ["Duration", fmtDuration(m.moving_s)],
        ["Distance", fmtNum((m.distance_m ?? 0) / 1000, 1, " km")],
        [effSport === "running" ? "Pace (GAP)" : "Speed", speed ? speedFmt(speed) : "—"],
        ["Avg HR", fmtNum(m.avg_hr, 0, " bpm")],
        [`At ${refHr} bpm`, m.ef ? speedFmt(m.ef * refHr) : "—"],
        ["Decoupling", fmtNum(m.decoupling_pct, 1, "%")],
        ["Drift onset", m.drift_onset_min ? `${m.drift_onset_min} min` : m.drift_checked_minutes ? `none in ${m.drift_checked_minutes} min` : "—"],
        ["Temp", fmtNum(m.temp_c, 0, "°C")],
        ["Elevation", fmtNum(m.elev_per_km, 1, " m/km")],
        ["Pace variability", fmtNum((m.pace_cv ?? NaN) * 100, 0, "%")],
      ];
    };
    const point = (a: AnalysisActivity, y: number, extra: Partial<TrendPoint> = {}): TrendPoint => ({
      x: ms(a.date),
      y,
      ghost: !!disqualify(a, q),
      color: colorOf(a),
      id: a.activity_id,
      title: `${format(parseISO(a.date), "EEE d MMM yyyy")} · ${a.name}`,
      tip: tipFor(a),
      ...extra,
    });
    const trendOf = (pts: TrendPoint[]) => {
      const groups = new Map<string, number[]>();
      for (const p of pts.filter((p) => !p.ghost)) {
        const k = bucketKey(iso(new Date(p.x)), gran);
        groups.set(k, [...(groups.get(k) ?? []), p.y]);
      }
      return [...groups.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, ys]) => ({ x: ms(gran === "month" ? k + "-01" : gran === "year" ? k + "-01-01" : k), y: median(ys)! }));
    };
    const effPts = eff.map((a) =>
      point(a, effSport === "running" ? 1000 / speedAtHr(a, refHr)! : speedAtHr(a, refHr)! * 3.6),
    );
    const decPts = eff.filter((a) => a.metrics.decoupling_pct != null).map((a) => point(a, a.metrics.decoupling_pct!));
    const driftPts = eff
      .filter((a) => a.metrics.drift_checked_minutes)
      .map((a) =>
        a.metrics.drift_onset_min
          ? point(a, a.metrics.drift_onset_min)
          : point(a, a.metrics.drift_checked_minutes!, { hollow: true }),
      );
    const gctPts = eff.filter((a) => a.metrics.gct_delta_ms != null).map((a) => point(a, a.metrics.gct_delta_ms!));
    const hrrPts = inRange
      .filter((a) => a.metrics.hrr60_mean != null)
      .map((a) => ({ ...point(a, a.metrics.hrr60_mean!), ghost: false, color: SPORT_COLORS[sportKey(a.sport)] }));

    // Load model uses every sport: fatigue does not care which sport caused it.
    const load = loadModel(acts, to).filter((p) => p.date >= from);
    const wRange = wellness
      .filter((w) => w.date >= from && w.date <= to)
      .map((w) => ({
        ...w,
        hrv_band: w.hrv_baseline_low && w.hrv_baseline_high ? [w.hrv_baseline_low, w.hrv_baseline_high] : null,
      }));
    const wPrev = wellness.filter((w) => w.date >= prevFrom && w.date <= prevTo);

    const dailyLoad = new Map<string, { load: number; names: string[] }>();
    for (const a of inRange) {
      const d = dailyLoad.get(a.date) ?? { load: 0, names: [] };
      d.load += a.metrics.load ?? 0;
      d.names.push(a.name);
      dailyLoad.set(a.date, d);
    }
    const days = bucketKeys(from, to, "day").map((d) => {
      const x = dailyLoad.get(d);
      return {
        date: d,
        load: x?.load ?? 0,
        label: `${format(parseISO(d), "EEE d MMM")}: ${x ? `${x.names.join(", ")} · load ${x.load.toFixed(0)}` : "rest"}`,
      };
    });

    const sum = (xs: AnalysisActivity[], f: (a: AnalysisActivity) => number) => xs.reduce((s, a) => s + f(a), 0);
    const pct = (a: number | null, b: number | null) => (a != null && b ? ((a - b) / Math.abs(b)) * 100 : null);
    const lowShare = (xs: AnalysisActivity[]) => {
      const z = xs.reduce((s, a) => s.map((v, i) => v + (a.metrics.hr_zones_s?.[i] ?? 0)), [0, 0, 0, 0, 0]);
      const t = z.reduce((a, b) => a + b, 0);
      return t ? ((z[0] + z[1]) / t) * 100 : null;
    };
    const effNow = median(effPts.filter((p) => !p.ghost).map((p) => speedAtHr(eff.find((a) => a.activity_id === p.id)!, refHr)!));
    const effThen = median(effPrev.map((a) => speedAtHr(a, refHr)!));
    const hours = sum(inRange, (a) => (a.metrics.duration_s ?? 0) / 3600);
    const kpis = {
      hours,
      hoursD: pct(hours, sum(prev, (a) => (a.metrics.duration_s ?? 0) / 3600)),
      km: sum(inRange, (a) => (a.metrics.distance_m ?? 0) / 1000),
      kmD: pct(sum(inRange, (a) => (a.metrics.distance_m ?? 0) / 1000), sum(prev, (a) => (a.metrics.distance_m ?? 0) / 1000)),
      sessions: inRange.length,
      low: lowShare(inRange),
      effNow,
      effD: pct(effNow, effThen),
      dec: median(decPts.filter((p) => !p.ghost).map((p) => p.y)),
      rhr: mean(wRange.map((w) => w.resting_hr).filter((x): x is number => x != null)),
      rhrD: pct(
        mean(wRange.map((w) => w.resting_hr).filter((x): x is number => x != null)),
        mean(wPrev.map((w) => w.resting_hr).filter((x): x is number => x != null)),
      ),
      hrv: mean(wRange.map((w) => w.hrv_night).filter((x): x is number => x != null)),
      hrvD: pct(
        mean(wRange.map((w) => w.hrv_night).filter((x): x is number => x != null)),
        mean(wPrev.map((w) => w.hrv_night).filter((x): x is number => x != null)),
      ),
      form: load.at(-1)?.form ?? null,
    };

    return {
      inRange,
      vol: [...vol.values()],
      zones: [...zones.values()],
      effPts,
      decPts,
      driftPts,
      gctPts,
      hrrPts,
      trends: { eff: trendOf(effPts), dec: trendOf(decPts), drift: trendOf(driftPts.filter((p) => !p.hollow)), gct: trendOf(gctPts) },
      load,
      wRange,
      days,
      kpis,
      speedFmt,
      colorRange: isFinite(cmin) ? [cb.fmt(cmin as never), cb.fmt(cmax as never)] : null,
    };
  }, [acts, wellness, from, to, gran, sports, effSport, q, refHr, colorBy]);

  if (!acts || !v) {
    return (
      <div className="flex items-center justify-center h-screen text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }
  if (!acts.length) {
    return (
      <div className="max-w-3xl mx-auto px-8 py-16 text-muted-foreground">
        <h1 className="text-3xl font-bold tracking-tight text-foreground mb-2">Analysis</h1>
        No activities stored yet. Run <code className="text-foreground">uv run coach analysis sync</code>.
      </div>
    );
  }

  const domain: [number, number] = [ms(from), ms(to)];
  const effLabel = effSport === "running" ? "pace" : "speed";
  const sel = acts.find((a) => a.activity_id === selected);
  const table = [...v.inRange]
    .filter((a) => !pickedDay || a.date === pickedDay)
    .sort((a, b) => b.start_local.localeCompare(a.start_local));

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          Analysis <InfoButton topic="page" label="this page" />
        </h1>
        <p className="text-muted-foreground mt-1">
          Is the engine getting better? Trends in efficiency and drift (only runs that pass your filters feed the
          trend), load and recovery.
        </p>
      </div>

      {/* Filters: one row, sticky */}
      <div className="sticky top-0 z-10 -mx-6 px-6 py-3 bg-background/90 backdrop-blur border-b flex flex-wrap items-center gap-3">
        <Seg value={gran} onChange={setGran} options={[["day", "Day"], ["week", "Week"], ["month", "Month"], ["year", "Year"]] as const} />
        <Seg
          value={preset === "custom" ? ("" as any) : preset}
          onChange={(p) => setPreset(p as Preset)}
          options={PRESETS}
        />
        <div className="flex items-center gap-1">
          <Input
            type="date"
            aria-label="From"
            className="h-8 w-[140px] text-xs"
            value={from}
            onChange={(e) => {
              setPreset("custom");
              setCustom({ from: e.target.value, to });
            }}
          />
          <span className="text-muted-foreground text-xs">→</span>
          <Input
            type="date"
            aria-label="To"
            className="h-8 w-[140px] text-xs"
            value={to}
            onChange={(e) => {
              setPreset("custom");
              setCustom({ from, to: e.target.value });
            }}
          />
        </div>
        <div className="flex gap-1.5 ml-auto">
          {SPORTS.map((s) => {
            const on = sports.has(s);
            return (
              <button
                key={s}
                type="button"
                aria-pressed={on}
                onClick={() => {
                  const next = new Set(sports);
                  on ? next.delete(s) : next.add(s);
                  setSports(next);
                }}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs capitalize transition-colors",
                  on ? "text-foreground" : "text-muted-foreground opacity-60",
                )}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: on ? SPORT_COLORS[s] : INK.muted }} />
                {s}
              </button>
            );
          })}
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Kpi label="Training time" value={`${v.kpis.hours.toFixed(1)} h`} delta={v.kpis.hoursD} sub={`${v.kpis.sessions} sessions`} />
        <Kpi label="Distance" value={`${v.kpis.km.toFixed(0)} km`} delta={v.kpis.kmD} />
        <Kpi label="Low-intensity share" value={fmtNum(v.kpis.low, 0, "%")} sub="target ≥ 80%" />
        <Kpi
          label={`${effSport === "running" ? "Pace" : "Speed"} at ${refHr} bpm`}
          value={v.kpis.effNow ? v.speedFmt(v.kpis.effNow) : "—"}
          delta={v.kpis.effD}
          sub="median, qualifying"
        />
        <Kpi label="Median decoupling" value={fmtNum(v.kpis.dec, 1, "%")} sub="target < 5%" />
        <Kpi label="Form (fitness − fatigue)" value={fmtNum(v.kpis.form, 0)} sub={v.kpis.form != null && v.kpis.form < -30 ? "deep fatigue" : "today"} />
        <Kpi label="Resting HR" value={fmtNum(v.kpis.rhr, 0, " bpm")} delta={v.kpis.rhrD} goodWhenUp={false} />
        <Kpi label="Overnight HRV" value={fmtNum(v.kpis.hrv, 0, " ms")} delta={v.kpis.hrvD} />
      </div>

      <ChartCard
        title="Training calendar" info="calendar"
        hint="Daily Garmin training load. Click a day to filter the activity list."
      >
        <CalendarHeat days={v.days} onPick={(d) => setPickedDay((p) => (p === d ? null : d))} />
      </ChartCard>

      <div className="grid lg:grid-cols-2 gap-6">
        <ChartCard title="Volume by sport" info="volume" hint="Hours per period." right={<Legend items={SPORTS.filter((s) => sports.has(s)).map((s) => ({ label: s, color: SPORT_COLORS[s] }))} />}>
          <StackedBars data={v.vol} unit="h" series={SPORTS.filter((s) => sports.has(s)).map((s) => ({ key: s, label: s, color: SPORT_COLORS[s] }))} />
        </ChartCard>
        <ChartCard
          title="Intensity distribution" info="intensity"
          hint="Share of time in your Garmin HR zones: low = Z1–2, moderate = Z3, high = Z4–5. Polarized training keeps low ≥ 80%."
          right={<Legend items={[{ label: "low", color: ZONE_COLORS.low }, { label: "moderate", color: ZONE_COLORS.moderate }, { label: "high", color: ZONE_COLORS.high }]} />}
        >
          <StackedBars
            data={v.zones}
            unit="h"
            percent
            reference={{ y: 0.8, label: "80%" }}
            series={[
              { key: "low", label: "low", color: ZONE_COLORS.low },
              { key: "moderate", label: "moderate", color: ZONE_COLORS.moderate },
              { key: "high", label: "high", color: ZONE_COLORS.high },
            ]}
          />
        </ChartCard>
      </div>

      <ChartCard
        title="Fitness, fatigue & form" info="load"
        hint="42-day (fitness) and 7-day (fatigue) averages of Garmin training load, all sports. Form = fitness − fatigue; below about −30 for a week or more usually shows up as HR creep."
        right={<Legend items={[{ label: "fitness", color: "#3987e5" }, { label: "fatigue", color: "#d95926" }, { label: "form", color: "#c3c2b7" }]} />}
      >
        <SeriesChart
          data={v.load}
          zeroLine
          lines={[
            { key: "fitness", label: "Fitness", color: "#3987e5" },
            { key: "fatigue", label: "Fatigue", color: "#d95926" },
            { key: "form", label: "Form", color: "#c3c2b7", dashed: true },
          ]}
        />
      </ChartCard>

      {/* Aerobic engine */}
      <div className="pt-2 space-y-3">
        <div className="flex flex-wrap items-end gap-4 justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Aerobic engine</h2>
            <p className="text-sm text-muted-foreground max-w-3xl">
              Every {effSport === "running" ? "run" : "ride"} is plotted. Ones that miss the filters below appear as faint
              rings and stay out of the trend line, so a hilly, hot or interval session never bends the trend. Hover
              a filled dot for its details; click one to open its streams. Loosen the filters to bring a ring in.
            </p>
          </div>
          <Seg value={effSport} onChange={setEffSport} options={[["running", "Running"], ["cycling", "Cycling"]] as const} />
        </div>
        <Card>
          <CardContent className="p-4 flex flex-wrap gap-x-8 gap-y-4 items-end">
            <Slider label="Min duration" value={q.minMinutes} min={0} max={120} step={5} fmt={(x) => `${x} min`} onChange={(x) => setQ({ ...q, minMinutes: x })} />
            <Slider label="Max pace variability" value={q.maxPaceCv} min={2} max={40} fmt={(x) => `${x}%`} onChange={(x) => setQ({ ...q, maxPaceCv: x })} />
            <Slider label="Max climbing" value={q.maxElevPerKm} min={2} max={60} fmt={(x) => `${x} m/km`} onChange={(x) => setQ({ ...q, maxElevPerKm: x })} />
            <Slider label="Max temperature" value={q.maxTempC} min={5} max={40} fmt={(x) => `${x}°C`} onChange={(x) => setQ({ ...q, maxTempC: x })} />
            <Slider label="Reference HR" value={refHr} min={110} max={175} fmt={(x) => `${x} bpm`} onChange={setRefHr} />
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={q.excludeStructured} onChange={(e) => setQ({ ...q, excludeStructured: e.target.checked })} className="accent-[#3987e5]" />
              Exclude interval sessions
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Color by
              <select value={colorBy} onChange={(e) => setColorBy(e.target.value as ColorBy)} className="rounded-md border bg-card px-2 py-1 text-xs text-foreground">
                {Object.entries(COLOR_BY).map(([k, c]) => (
                  <option key={k} value={k}>{c.label}</option>
                ))}
              </select>
            </label>
            {colorBy !== "none" && v.colorRange && (
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {v.colorRange[0]}
                <span className="h-2 w-24 rounded-sm" style={{ background: `linear-gradient(90deg, ${RAMP.join(",")})` }} />
                {v.colorRange[1]}
              </div>
            )}
            <button type="button" onClick={() => setQ(DEFAULT_QUALIFIER)} className="text-xs text-muted-foreground underline underline-offset-2 ml-auto">
              reset filters
            </button>
          </CardContent>
        </Card>

        <div className="grid lg:grid-cols-2 gap-6">
          <ChartCard
            title={`Efficiency: ${effLabel} at ${refHr} bpm`} info="efficiency"
            hint={
              effSport === "running"
                ? "Grade-adjusted speed ÷ HR, measured after the first 15 moving minutes, shown as the pace you'd hold at the reference HR. Up the chart = fitter."
                : "Speed ÷ HR (no power on your rides), shown as speed at the reference HR. Wind and traffic make this noisy."
            }
          >
            <TrendScatter
              points={v.effPts}
              trend={v.trends.eff}
              domain={domain}
              yReversed={effSport === "running"}
              yFormat={(y) => (effSport === "running" ? fmtPace(y) : y.toFixed(0))}
              onSelect={setSelected}
            />
          </ChartCard>
          <ChartCard
            title="Aerobic decoupling (Pa:HR)" info="decoupling"
            hint="Efficiency lost from the first to the second half of the session. Under 5% on long steady runs means the aerobic base is holding."
          >
            <TrendScatter
              points={v.decPts}
              trend={v.trends.dec}
              domain={domain}
              yFormat={(y) => `${y.toFixed(0)}%`}
              bands={[{ y1: -5, y2: 5, color: "#0ca30c" }]}
              refLines={[{ y: 5, label: "5%" }]}
              onSelect={setSelected}
            />
          </ChartCard>
          <ChartCard
            title="Drift onset horizon" info="drift"
            hint="Minute at which 5-min efficiency first falls 3% below the minute 15–25 baseline. Hollow rings mean no drift for the whole session, plotted at its length. Higher = more durable."
          >
            <TrendScatter
              points={v.driftPts}
              trend={v.trends.drift}
              domain={domain}
              yFormat={(y) => `${y.toFixed(0)}′`}
              onSelect={setSelected}
            />
          </ChartCard>
          {effSport === "running" ? (
            <ChartCard
              title="Ground-contact creep" info="gct"
              hint="GCT in the last 10 min minus minutes 15–25. A rising creep alongside decoupling points to muscular fatigue rather than cardiac drift."
            >
              <TrendScatter
                points={v.gctPts}
                trend={v.trends.gct}
                domain={domain}
                yFormat={(y) => `${y.toFixed(0)} ms`}
                refLines={[{ y: 0, label: "" }]}
                onSelect={setSelected}
              />
            </ChartCard>
          ) : (
            <ChartCard title="Ground-contact creep" hint="Running only.">
              <p className="text-sm text-muted-foreground">Switch to running to see running dynamics.</p>
            </ChartCard>
          )}
        </div>

        <ChartCard
          title="60 s heart-rate recovery after intervals" info="hrr"
          hint="Mean HR drop one minute after each interval rep (detected from lap paces, manual laps included) whose recovery lasts ≥ 55 s. A faster drop means a quicker parasympathetic rebound; ≥ 30 bpm is strong."
        >
          {v.hrrPts.length ? (
            <TrendScatter points={v.hrrPts} trend={[]} domain={domain} yFormat={(y) => `${y.toFixed(0)}`} refLines={[{ y: 30, label: "30 bpm" }]} onSelect={setSelected} height={200} />
          ) : (
            <p className="text-sm text-muted-foreground">No interval sessions in this range.</p>
          )}
        </ChartCard>
      </div>

      {/* Recovery */}
      <div className="pt-2 space-y-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Recovery</h2>
          <p className="text-sm text-muted-foreground">
            Resting HR rising or HRV falling below its band alongside drift means fatigue, not lost fitness.
          </p>
        </div>
        <div className="grid lg:grid-cols-2 gap-6">
          <ChartCard title="Resting heart rate" info="restingHr" right={<Legend items={[{ label: "daily", color: "#d95926" }, { label: "7-day", color: "#c3c2b7" }]} />}>
            <SeriesChart data={v.wRange} lines={[{ key: "resting_hr", label: "Daily", color: "#d95926" }, { key: "resting_hr_7d", label: "7-day avg", color: "#c3c2b7", dashed: true }]} />
          </ChartCard>
          <ChartCard title="Overnight HRV" info="hrv" right={<Legend items={[{ label: "nightly", color: "#3987e5" }, { label: "7-day", color: "#c3c2b7" }, { label: "balanced band", color: "#199e70" }]} />}>
            <SeriesChart
              data={v.wRange}
              band={{ key: "hrv_band", label: "Balanced", color: "#199e70" }}
              lines={[{ key: "hrv_night", label: "Nightly", color: "#3987e5" }, { key: "hrv_week", label: "7-day avg", color: "#c3c2b7", dashed: true }]}
            />
          </ChartCard>
          <ChartCard title="Sleep score" info="sleep">
            <SeriesChart data={v.wRange} lines={[{ key: "sleep_score", label: "Sleep score", color: "#6250d6" }]} />
          </ChartCard>
          <ChartCard title="Body battery at wake" info="bodyBattery">
            <SeriesChart data={v.wRange} lines={[{ key: "bb_wake", label: "At wake", color: "#199e70" }]} />
          </ChartCard>
        </div>
      </div>

      {/* Activity table + drill-down */}
      <ChartCard
        title="Activities" info="table"
        hint="Click a row for its streams."
        right={
          pickedDay && (
            <button type="button" onClick={() => setPickedDay(null)} className="flex items-center gap-1 text-xs rounded-full border px-2 py-1">
              {format(parseISO(pickedDay), "d MMM")} <X className="h-3 w-3" />
            </button>
          )
        }
      >
        <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-card text-muted-foreground text-left">
              <tr>
                {["Date", "Activity", "Time", "Dist", "Pace / speed", "HR", "Load", `@${refHr} bpm`, "Decoupl.", "Drift", "GCT Δ", "HRR60", "Temp", "m/km"].map((h) => (
                  <th key={h} className="py-2 pr-3 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.map((a) => {
                const m = a.metrics;
                const run = a.sport === "running";
                const fmtSp = (s?: number | null) => (!s ? "—" : run ? `${fmtPace(1000 / s)}` : `${(s * 3.6).toFixed(1)}`);
                return (
                  <tr
                    key={a.activity_id}
                    onClick={() => setSelected(a.activity_id === selected ? null : a.activity_id)}
                    className={cn("border-t cursor-pointer hover:bg-accent/50", a.activity_id === selected && "bg-accent")}
                  >
                    <td className="py-1.5 pr-3 whitespace-nowrap">{format(parseISO(a.date), "EEE d MMM yy")}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      <span className="inline-block h-2 w-2 rounded-full mr-1.5" style={{ background: SPORT_COLORS[sportKey(a.sport)] }} />
                      {a.name}
                      {m.intervals && <span className="ml-1.5 text-muted-foreground">· {m.interval_reps} reps</span>}
                    </td>
                    <td className="py-1.5 pr-3">{fmtDuration(m.duration_s)}</td>
                    <td className="py-1.5 pr-3">{m.distance_m ? fmtNum(m.distance_m / 1000, 1) : "—"}</td>
                    <td className="py-1.5 pr-3">{fmtSp(run ? m.avg_gap_speed ?? m.avg_speed : m.avg_speed)}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.avg_hr, 0)}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.load, 0)}</td>
                    <td className="py-1.5 pr-3">{m.ef ? fmtSp(m.ef * refHr) : "—"}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.decoupling_pct, 1, "%")}</td>
                    <td className="py-1.5 pr-3">{m.drift_onset_min ? `${m.drift_onset_min}′` : m.drift_checked_minutes ? "none" : "—"}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.gct_delta_ms, 0)}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.hrr60_mean, 0)}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.temp_c, 0, "°")}</td>
                    <td className="py-1.5 pr-3">{fmtNum(m.elev_per_km, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </ChartCard>

      {sel && (
        <ChartCard
          title={`${sel.name} · ${format(parseISO(sel.date), "EEE d MMM yyyy")}`} info="streams"
          hint="Streams in 15 s bins. The dashed lines mark the end of the warm-up and the drift onset."
          right={
            <button type="button" aria-label="Close" onClick={() => setSelected(null)}>
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          }
        >
          {!streams ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : !streams.points.length ? (
            <p className="text-sm text-muted-foreground">No sample streams stored for this activity.</p>
          ) : (
            (() => {
              const run = streams.sport === "running";
              const pts = streams.points.map((p) => ({
                ...p,
                pace: run && (p.gap ?? p.speed) ? Math.min(1000 / (p.gap ?? p.speed)!, 900) : null,
                kmh: p.speed ? p.speed * 3.6 : null,
              }));
              const markers = [
                { x: 15, label: "warm-up" },
                ...(streams.metrics.drift_onset_min ? [{ x: streams.metrics.drift_onset_min, label: "drift" }] : []),
              ];
              const has = (k: keyof (typeof pts)[number]) => pts.some((p) => p[k] != null);
              return (
                <div className="grid md:grid-cols-2 gap-x-6 gap-y-3">
                  <StreamPanel syncId="s" data={pts} dataKey="hr" label="Heart rate (bpm)" color="#d95926" markers={markers} />
                  {run ? (
                    <StreamPanel syncId="s" data={pts} dataKey="pace" label="Grade-adjusted pace (/km)" color="#3987e5" reversed yFormat={fmtPace} markers={markers} />
                  ) : (
                    <StreamPanel syncId="s" data={pts} dataKey="kmh" label="Speed (km/h)" color="#3987e5" markers={markers} />
                  )}
                  {has("power") && <StreamPanel syncId="s" data={pts} dataKey="power" label="Power (W)" color="#6250d6" markers={markers} />}
                  {has("gct") && <StreamPanel syncId="s" data={pts} dataKey="gct" label="Ground contact (ms)" color="#199e70" markers={markers} />}
                  {has("elev") && <StreamPanel syncId="s" data={pts} dataKey="elev" label="Elevation (m)" color="#c3c2b7" markers={markers} />}
                  {has("cadence") && <StreamPanel syncId="s" data={pts} dataKey="cadence" label="Cadence (spm)" color="#c98500" markers={markers} />}
                </div>
              );
            })()
          )}
        </ChartCard>
      )}
    </div>
  );
}
