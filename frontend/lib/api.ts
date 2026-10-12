// Thin fetch wrapper for the FastAPI backend.

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ----------------------------------------------------------- types

export type Profile = {
  name: string;
  garmin_email: string | null;
  recent_5k_seconds: number | null;
  threshold_hr: number | null;
  max_hr: number | null;
  preferred_days: Record<string, number[]>;
  weekly_hours_target: number | null;
  notes: string | null;
  enabled_sports: string[];
  sport_profiles: Record<string, any>;
};

export type SportsCatalog = {
  sports: string[];
  benchmarks: Record<string, any>;
};

export type PlanSummary = {
  id: number;
  name: string;
  goal_text: string;
  start_date: string;
  end_date: string;
  status: string;
  version: number;
  workout_count: number;
  uploaded_count: number;
};

export type Workout = {
  id: number;
  plan_id: number;
  date: string;
  week_number: number;
  sport: string;
  title: string;
  description: string | null;
  primitive_type: string;
  primitive_params: Record<string, unknown>;
  garmin_workout_id: number | null;
  garmin_schedule_id: number | null;
  status: string;
};

export type Warning = {
  severity: string;
  message: string;
  dates: string[];
};

export type PlanDetail = {
  id: number;
  name: string;
  goal_text: string;
  start_date: string;
  end_date: string;
  status: string;
  version: number;
  structure: Record<string, unknown>;
  workouts: Workout[];
  warnings: Warning[];
};

export type Settings = {
  has_garmin_password: boolean;
  has_openrouter_key: boolean;
  openrouter_model: string | null;
};

export type SyncResult = {
  plan_id: number;
  uploaded: number;
  skipped: number;
  failed: [number, string][];
};

export type UnpushResult = {
  plan_id: number;
  removed: number;
  skipped: number;
  failed: [number, string][];
};

// ----------------------------------------------------------- endpoints

export type ChatMessage = { role: "assistant" | "user"; content: string };

export type Facts = Record<string, any>;

export type IntakeQuestion = {
  id: string;
  text: string;
  // Always "text" — every answer is free text, normalised by the model.
  kind: string;
};

export type IntakeTurn = {
  note: string;
  facts: Facts;
  question: IntakeQuestion | null;
  ready: boolean;
  summary: string;
  model_used: string;
  researched: boolean;
  warnings: string[];
  conversation_id: number;
};

export type ConversationSummary = {
  id: number;
  title: string;
  ready: boolean;
  plan_id: number | null;
  updated_at: string;
  turns: number;
};

export type ConversationDetail = {
  id: number;
  title: string;
  history: ChatMessage[];
  facts: Facts;
  question: IntakeQuestion | null;
  ready: boolean;
  summary: string;
  plan_id: number | null;
};


// ------------------------------------------------------------ analysis

export type ActivityMetrics = {
  type: string;
  duration_s: number | null;
  moving_s: number | null;
  distance_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_speed: number | null;
  avg_gap_speed: number | null;
  elev_gain_m: number | null;
  elev_per_km: number | null;
  avg_power: number | null;
  cadence: number | null;
  gct_ms: number | null;
  vo2max: number | null;
  load: number | null;
  aerobic_te: number | null;
  te_label: string | null;
  hr_zones_s: number[];
  structured: boolean;
  temp_c?: number | null;
  dew_point_c?: number | null;
  ef_basis?: "gap" | "speed";
  ef?: number | null;
  ef_power?: number | null;
  pace_cv?: number;
  decoupling_pct?: number;
  decoupling_power_pct?: number;
  hr_drift_bpm?: number;
  speed_change_pct?: number | null;
  drift_checked_minutes?: number;
  drift_onset_min?: number | null;
  drift_onset_km?: number | null;
  gct_delta_ms?: number;
  perf_condition_first?: number;
  perf_condition_last?: number;
  hrr60_mean?: number;
  hrr60_n?: number;
};

export type AnalysisActivity = {
  activity_id: number;
  date: string;
  start_local: string;
  sport: string;
  name: string;
  has_streams: boolean;
  metrics: ActivityMetrics;
};

export type WellnessDay = {
  date: string;
  resting_hr: number | null;
  resting_hr_7d: number | null;
  hrv_night: number | null;
  hrv_week: number | null;
  hrv_status: string | null;
  hrv_baseline_low: number | null;
  hrv_baseline_high: number | null;
  sleep_score: number | null;
  sleep_h: number | null;
  stress_avg: number | null;
  bb_wake: number | null;
};

export type StreamPoint = {
  minute: number;
  hr?: number | null;
  speed?: number | null;
  gap?: number | null;
  power?: number | null;
  gct?: number | null;
  cadence?: number | null;
  dist?: number;
  elev?: number;
};

export type ActivityStreams = {
  activity_id: number;
  name: string;
  date: string;
  sport: string;
  metrics: ActivityMetrics;
  points: StreamPoint[];
};

export const api = {
  profile: {
    get: () => request<Profile>("/api/profile"),
    update: (data: Partial<Profile>) =>
      request<Profile>("/api/profile", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
  plans: {
    list: () => request<PlanSummary[]>("/api/plans"),
    get: (id: number) => request<PlanDetail>(`/api/plans/${id}`),
    create: (data: { name: string; goal_text: string; start_date: string; end_date: string }) =>
      request<PlanDetail>("/api/plans", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    delete: (id: number) =>
      request<void>(`/api/plans/${id}`, { method: "DELETE" }),
    generate: (data: {
      goal_text: string;
      start_date: string;
      end_date: string;
      start_volume_km?: number;
      peak_volume_km?: number | null;
      taper_weeks?: number;
    }) =>
      request<{ plan: PlanDetail; model_used: string }>("/api/plans/generate", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    push: (id: number) =>
      request<SyncResult>(`/api/plans/${id}/push`, { method: "POST" }),
    unpush: (id: number) =>
      request<UnpushResult>(`/api/plans/${id}/unpush`, { method: "POST" }),
    export: (id: number) => request<Record<string, unknown>>(`/api/plans/${id}/export`),
    chat: (data: {
      history: ChatMessage[];
      facts: Facts;
      conversation_id?: number | null;
    }) =>
      request<IntakeTurn>("/api/plans/chat", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    conversations: () =>
      request<ConversationSummary[]>("/api/plans/chat/conversations"),
    conversation: (id: number) =>
      request<ConversationDetail>(`/api/plans/chat/conversations/${id}`),
    deleteConversation: (id: number) =>
      request<void>(`/api/plans/chat/conversations/${id}`, { method: "DELETE" }),
    generateFromChat: (data: {
      facts: Facts;
      conversation_id?: number | null;
      start_date: string;
      end_date?: string | null;
      goal_text?: string | null;
      start_volume_km?: number | null;
      peak_volume_km?: number | null;
      taper_weeks?: number;
    }) =>
      request<{ plan: PlanDetail; model_used: string }>("/api/plans/chat/generate", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  },
  workouts: {
    create: (data: Partial<Workout> & { plan_id: number; date: string; sport: string; primitive_type: string }) =>
      request<Workout>("/api/workouts", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    update: (id: number, data: Partial<Workout>) =>
      request<Workout>(`/api/workouts/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    delete: (id: number) =>
      request<void>(`/api/workouts/${id}`, { method: "DELETE" }),
  },
  settings: {
    get: () => request<Settings>("/api/settings"),
    setGarminPassword: (password: string) =>
      request<void>("/api/settings/garmin-password", {
        method: "PUT",
        body: JSON.stringify({ password }),
      }),
    clearGarminPassword: () =>
      request<void>("/api/settings/garmin-password", { method: "DELETE" }),
    setOpenRouter: (api_key: string, model: string | null) =>
      request<void>("/api/settings/openrouter", {
        method: "PUT",
        body: JSON.stringify({ api_key, model }),
      }),
    clearOpenRouter: () =>
      request<void>("/api/settings/openrouter", { method: "DELETE" }),
    primitives: () =>
      request<{ name: string; params: string[] }[]>("/api/settings/primitives"),
    sports: () => request<SportsCatalog>("/api/settings/sports"),
  },
  analysis: {
    activities: () => request<AnalysisActivity[]>("/api/analysis/activities"),
    wellness: () => request<WellnessDay[]>("/api/analysis/wellness"),
    streams: (id: number) =>
      request<ActivityStreams>(`/api/analysis/activities/${id}/streams`),
  },
};
