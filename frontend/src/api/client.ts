import type {
  DiffResponse,
  FeedbackAnalysis,
  MetaResponse,
  Placement,
  TimetableResponse,
  ValidationResponse,
} from "../types";
import type { AppException, AppPayload } from "../types/app";

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

/**
 * État applicatif complet — mêmes données que celles embarquées dans
 * `/legacy` (page HTML/JS historique), calculées par la même fonction Python
 * (`build_payload`). Source unique pour toutes les vues en lecture seule
 * (Enseignant, Promo, Référence, Contraintes, À traiter, recherche) : le
 * frontend ne redérive aucun verdict, il affiche ce que le serveur a déjà
 * validé.
 */
export function fetchAppState(): Promise<AppPayload> {
  return request<AppPayload>("/app-state");
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

// ── Exceptions ponctuelles + régénération ciblée ──
// Portage de la section "ONGLET SEMAINE" de `export/templates/timetable.html`
// (`renderExceptionList`/le handler `regenBtn`) — jusqu'ici jamais câblée
// côté React alors que le backend l'exposait déjà entièrement (retour
// utilisateur 11/08/2026, cf. docs/DATA.md).

export function listExceptions(): Promise<AppException[]> {
  return request<AppException[]>("/exceptions");
}

export function createException(body: {
  kind: "teacher_absence" | "room_unavailable";
  exception_date: string;
  teacher_code?: string | null;
  room_id?: string | null;
  reason?: string | null;
}): Promise<AppException> {
  return request<AppException>("/exceptions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteException(id: number): Promise<{ deleted: boolean }> {
  return request(`/exceptions/${id}`, { method: "DELETE" });
}

export interface RegenResult {
  status: string;
  touched_weeks: number[];
  placements: Placement[];
  message: string;
}

export function regenWeek(week: number, extendNext: boolean): Promise<{ job_id: string; status: string }> {
  return request("/regen/week", {
    method: "POST",
    body: JSON.stringify({ week, extend_next: extendNext }),
  });
}

export type RegenStatus =
  | { job_id: string; status: "running" }
  | { job_id: string; status: "done"; result: RegenResult }
  | { job_id: string; status: "error"; error: string };

export function fetchRegenStatus(jobId: string): Promise<RegenStatus> {
  return request<RegenStatus>(`/regen/status?job_id=${encodeURIComponent(jobId)}`);
}

export function extractTeachers(placements: Placement[]): string[] {
  const set = new Set<string>();
  for (const p of placements) {
    for (const t of p.teacher_codes) set.add(t);
  }
  return [...set].sort();
}
