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

// Code du lien personnel (prof ou groupe, public — cf. api/auth.py) — posé
// une fois au démarrage (App.tsx, lu depuis `route.t`) quand la page est
// ouverte via un tel lien, puis rejoué sur CHAQUE appel API pour contourner
// le mot de passe partagé sans jamais avoir à le taper (retour utilisateur
// 28/08/2026). `null` = comportement normal, rien n'est ajouté aux requêtes.
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = accessToken
    ? `${BASE}${path}${path.includes("?") ? "&" : "?"}t=${encodeURIComponent(accessToken)}`
    : `${BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  }
  return res.json() as Promise<T>;
}

/** Mot de passe partagé — session posée en cookie httpOnly par le serveur,
 * jamais manipulée côté JS directement (cf. api/auth.py). */
export async function login(password: string): Promise<void> {
  await request("/auth/login", { method: "POST", body: JSON.stringify({ password }) });
}

export async function logout(): Promise<void> {
  await request("/auth/logout", { method: "POST" });
}

export async function checkAuthStatus(): Promise<boolean> {
  const r = await request<{ authenticated: boolean }>("/auth/status");
  return r.authenticated;
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

// ── Séances non placées + placement manuel ──
// Le solveur place ~96,5 % des séances ; le reste bute sur des combinaisons
// prouvées infaisables (cf. docs/DATA.md §66). Ces trois appels permettent de
// placer ce reliquat à la main sans jamais deviner : le serveur ne propose que
// des créneaux où aucune règle n'est violée, et revérifie tout au placement.

export interface SeanceAPlacer {
  session_id: string;
  course_code: string;
  course_name: string;
  session_type: string;
  semestre: string;
  parcours: string;
  annee: string;
  duration_slots: number;
  duree_libelle: string;
  group_ids: string[];
  groupes_libelles: string[];
  teacher_codes: string[];
  enseignants_libelles: string[];
  sequence_order: number | null;
  semaines_possibles: number[];
  raison: string;
  /** Placée en forçant l'ordre pédagogique, pas encore validée — reste
   * listée ici pour pouvoir revenir en arrière (retour utilisateur
   * 28/08/2026). `semaine_actuelle`/`jour_actuel`/`slot_actuel` ne sont
   * remplis que si `placee_provisoirement` est vrai. */
  placee_provisoirement: boolean;
  semaine_actuelle: number | null;
  jour_actuel: number | null;
  slot_actuel: number | null;
}

export interface SeancesAPlacer {
  total_a_placer: number;
  total_placees: number;
  manquantes: SeanceAPlacer[];
  par_parcours: Record<string, number>;
  resume: string;
}

export interface CreneauLibre {
  week: number;
  day: number;
  slot: number;
  label: string;
  date: string;
  salle_label: string | null;
  remarques: string[];
}

export interface CreneauxLibres {
  session_id: string;
  creneaux: CreneauLibre[];
  note: string | null;
}

export function fetchSeancesManquantes(): Promise<SeancesAPlacer> {
  return request<SeancesAPlacer>("/placements/manquantes");
}

export function fetchCreneauxLibres(sessionId: string, depuisSemaine = 0): Promise<CreneauxLibres> {
  return request<CreneauxLibres>(
    `/placements/${encodeURIComponent(sessionId)}/creneaux-libres?depuis_semaine=${depuisSemaine}`,
  );
}

export function placerSeance(
  sessionId: string,
  body: { week: number; day: number; slot: number; room_id?: string | null; lock?: boolean; force?: boolean },
): Promise<Placement> {
  return request<Placement>(`/placements/${encodeURIComponent(sessionId)}/placer`, {
    method: "POST",
    body: JSON.stringify({ lock: false, force: false, ...body }),
  });
}

// ── Suivi des placements forcés (ordre pédagogique) — retour utilisateur
// 28/08/2026 : « valider »/« revenir en arrière ». ──

export interface ForcagePedagogique {
  session_id: string;
  etait_en_attente: boolean;
}

export function validerPlacementForce(sessionId: string): Promise<ForcagePedagogique> {
  return request<ForcagePedagogique>(`/placements/${encodeURIComponent(sessionId)}/valider`, { method: "POST" });
}

export function retirerPlacementForce(sessionId: string): Promise<ForcagePedagogique> {
  return request<ForcagePedagogique>(`/placements/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}

// ── Remplissage automatique du reliquat ──
// Constat du 26/08/2026 sur le run réel : sur 20 séances manquantes, 20
// avaient au moins un créneau parfaitement valable. Faire cliquer 85 fois pour
// poser des séances que la machine sait poser serait un gâchis.

export interface SeancePlaceeAuto {
  session_id: string;
  course_code: string;
  week: number;
  day: number;
  slot: number;
  date: string;
}

export interface SeanceRefusee {
  session_id: string;
  course_code: string;
  raison: string;
}

export interface Completion {
  placees: SeancePlaceeAuto[];
  refusees: SeanceRefusee[];
  resume: string;
}

export function completerPlacements(): Promise<Completion> {
  return request<Completion>("/placements/completer", { method: "POST" });
}

// ── Envoi automatique du lien perso par mail (retour utilisateur 28/08/2026) ──

export interface TeacherMailPreview {
  code: string;
  name: string;
  email: string | null;
  sent_at: string | null;
}

export interface TeacherMailPreviewList {
  configured: boolean;
  teachers: TeacherMailPreview[];
}

export function fetchTeacherMailPreview(): Promise<TeacherMailPreviewList> {
  return request<TeacherMailPreviewList>("/mail/teacher-links");
}

export interface TeacherMailSendResult {
  code: string;
  ok: boolean;
  error: string | null;
}

export function sendTeacherMails(codes: string[]): Promise<{ results: TeacherMailSendResult[] }> {
  return request("/mail/teacher-links/send", { method: "POST", body: JSON.stringify({ codes }) });
}
