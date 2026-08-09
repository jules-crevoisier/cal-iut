import type {
  DiffResponse,
  FeedbackAnalysis,
  MetaResponse,
  Placement,
  TimetableResponse,
  ValidationResponse,
} from "../types";

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  }
  return res.json() as Promise<T>;
}

export function fetchMeta(): Promise<MetaResponse> {
  return request<MetaResponse>("/meta");
}

export function ingest(parcours: string, semestre: string): Promise<Record<string, unknown>> {
  return request("/ingest", {
    method: "POST",
    body: JSON.stringify({ parcours, semestre }),
  });
}

export function solve(params: {
  parcours: string;
  semestre: string;
  weeks?: number;
  optimize_gaps?: boolean;
}): Promise<TimetableResponse> {
  return request<TimetableResponse>("/solve", {
    method: "POST",
    body: JSON.stringify({
      // weeks omis si non fourni : le backend calcule l'horizon par défaut
      // depuis le calendrier réel (cal_iut.calendar.academic.default_horizon_weeks).
      ...(params.weeks !== undefined ? { weeks: params.weeks } : {}),
      optimize_gaps: params.optimize_gaps ?? false,
      assign_rooms: true,
      parcours: params.parcours,
      semestre: params.semestre,
    }),
  });
}

export function fetchTimetable(params: {
  group_id?: string;
  teacher_code?: string;
  room_id?: string;
  week?: number;
}): Promise<TimetableResponse> {
  const qs = new URLSearchParams();
  if (params.group_id) qs.set("group_id", params.group_id);
  if (params.teacher_code) qs.set("teacher_code", params.teacher_code);
  if (params.room_id) qs.set("room_id", params.room_id);
  if (params.week !== undefined) qs.set("week", String(params.week));
  return request<TimetableResponse>(`/timetable?${qs}`);
}

export function fetchDiff(): Promise<DiffResponse> {
  return request<DiffResponse>("/diff");
}

export function fetchFeedbackAnalysis(): Promise<FeedbackAnalysis> {
  return request<FeedbackAnalysis>("/feedback/analysis");
}

export function applyFeedback(): Promise<Record<string, unknown>> {
  return request("/feedback/apply", { method: "POST" });
}

export function validateMove(
  sessionId: string,
  body: { week: number; day: number; slot: number; room_id?: string | null },
): Promise<ValidationResponse> {
  return request<ValidationResponse>(`/placements/${encodeURIComponent(sessionId)}/validate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function movePlacement(
  sessionId: string,
  body: {
    week: number;
    day: number;
    slot: number;
    room_id?: string | null;
    lock?: boolean;
    force?: boolean;
  },
): Promise<Placement> {
  return request<Placement>(`/placements/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function fetchCorrections(): Promise<Record<string, unknown>[]> {
  return request("/corrections");
}

export function exportCsvUrl(): string {
  return `${BASE}/export/csv`;
}

export function exportJson(): Promise<Record<string, unknown>[]> {
  return request("/export/json");
}

export function extractTeachers(placements: Placement[]): string[] {
  const set = new Set<string>();
  for (const p of placements) {
    for (const t of p.teacher_codes) set.add(t);
  }
  return [...set].sort();
}
