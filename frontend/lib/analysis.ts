// Pure helpers for the analysis page: bucketing, filters, load model.
import { addDays, format, parseISO, startOfWeek } from "date-fns";
import type { AnalysisActivity, WellnessDay } from "@/lib/api";

export type Granularity = "day" | "week" | "month" | "year";

// Dark-mode categorical slots 1-4 (validated against the card surface).
export const SPORT_COLORS: Record<string, string> = {
  running: "#3987e5",
  cycling: "#d95926",
  strength: "#199e70",
  other: "#c98500",
};
export const SPORTS = ["running", "cycling", "strength", "other"] as const;
export const ZONE_COLORS = { low: "#256abf", moderate: "#6da7ec", high: "#cde2fb" };
export const INK = { muted: "#898781", grid: "#2c2c2a", axis: "#383835", text: "#c3c2b7" };

export function sportKey(sport: string): string {
  if (sport === "running" || sport === "cycling") return sport;
  if (sport.includes("strength") || sport === "hiit") return "strength";
  return "other";
}

export function bucketKey(d: string, g: Granularity): string {
  if (g === "day") return d;
  if (g === "week") return format(startOfWeek(parseISO(d), { weekStartsOn: 1 }), "yyyy-MM-dd");
  if (g === "month") return d.slice(0, 7);
  return d.slice(0, 4);
}

export function bucketLabel(key: string, g: Granularity): string {
  if (g === "day") return format(parseISO(key), "d MMM");
  if (g === "week") return "Wk " + format(parseISO(key), "d MMM");
  if (g === "month") return format(parseISO(key + "-01"), "MMM yy");
  return key;
}

/** Every bucket key between from and to, so empty periods show as gaps. */
export function bucketKeys(from: string, to: string, g: Granularity): string[] {
  const keys: string[] = [];
  for (let d = parseISO(from); format(d, "yyyy-MM-dd") <= to; d = addDays(d, 1)) {
    const k = bucketKey(format(d, "yyyy-MM-dd"), g);
    if (keys[keys.length - 1] !== k) keys.push(k);
  }
  return keys;
}

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

// ------------------------------------------------------------- qualifiers

export type Qualifier = {
  minMinutes: number;
  maxPaceCv: number; // %
  maxElevPerKm: number;
  maxTempC: number;
  excludeStructured: boolean;
};

export const DEFAULT_QUALIFIER: Qualifier = {
  minMinutes: 30,
  maxPaceCv: 15,
  maxElevPerKm: 20,
  maxTempC: 40,
  excludeStructured: true,
};

/** Why an activity is excluded from the trend, or null when it qualifies. */
export function disqualify(a: AnalysisActivity, q: Qualifier): string | null {
  const m = a.metrics;
  if ((m.moving_s ?? 0) / 60 < q.minMinutes) return `shorter than ${q.minMinutes} min`;
  if (q.excludeStructured && m.intervals) return "interval session";
  if (m.pace_cv != null && m.pace_cv * 100 > q.maxPaceCv) return "unsteady pace";
  if (m.elev_per_km != null && m.elev_per_km > q.maxElevPerKm) return "hilly";
  if (m.temp_c != null && m.temp_c > q.maxTempC) return "hot";
  return null;
}

// ------------------------------------------------------------------ load

export type LoadPoint = { date: string; load: number; fitness: number; fatigue: number; form: number };

/** Banister-style fitness (42 d) / fatigue (7 d) EWMAs over Garmin training load. */
export function loadModel(acts: AnalysisActivity[], until: string): LoadPoint[] {
  if (!acts.length) return [];
  const daily = new Map<string, number>();
  for (const a of acts) daily.set(a.date, (daily.get(a.date) ?? 0) + (a.metrics.load ?? 0));
  const out: LoadPoint[] = [];
  let ctl = 0;
  let atl = 0;
  for (let d = parseISO(acts[0].date); format(d, "yyyy-MM-dd") <= until; d = addDays(d, 1)) {
    const key = format(d, "yyyy-MM-dd");
    const load = daily.get(key) ?? 0;
    const form = ctl - atl; // form is yesterday's balance going into today
    ctl += (load - ctl) / 42;
    atl += (load - atl) / 7;
    out.push({ date: key, load, fitness: ctl, fatigue: atl, form });
  }
  return out;
}

// --------------------------------------------------------------- formats

export function fmtPace(secPerKm: number | null | undefined): string {
  if (!secPerKm || !isFinite(secPerKm)) return "—";
  const m = Math.floor(secPerKm / 60);
  const s = Math.round(secPerKm % 60);
  return s === 60 ? `${m + 1}:00` : `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtDuration(sec: number | null | undefined): string {
  if (!sec) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export function fmtNum(v: number | null | undefined, digits = 1, unit = ""): string {
  return v == null || !isFinite(v) ? "—" : `${v.toFixed(digits)}${unit}`;
}

/** Speed (m/s) a run would hold at refHr if EF held: the headline efficiency number. */
export function speedAtHr(a: AnalysisActivity, refHr: number): number | null {
  return a.metrics.ef ? a.metrics.ef * refHr : null;
}

export function wellnessByDate(w: WellnessDay[]): Map<string, WellnessDay> {
  return new Map(w.map((d) => [d.date, d]));
}
