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
};
