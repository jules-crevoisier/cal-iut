import type {
  DiffResponse,
  FeedbackAnalysis,
  MetaResponse,
  NotificationConfig,
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

/** Message d'erreur lisible depuis les trois formes que renvoie l'API :
 * `{"detail": "texte"}` (la plupart des routes), `{"message": "texte"}`
 * (comptes utilisateur — 400/403/409/503, cf. `api/main.py`, style choisi
 * pour distinguer un conflit métier d'un problème de session), et
 * `{"detail": [{"msg": "..."}]}` (422 de validation Pydantic — un tableau,
 * jamais une chaîne). Sans ce dernier cas, un mot de passe trop court
 * affichait `[object Object]`. */
function messageErreur(body: unknown, repli: string): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.message === "string") return b.message;
    if (typeof b.detail === "string") return b.detail;
    if (Array.isArray(b.detail)) {
      const msgs = b.detail
        .map((e) => (e && typeof e === "object" && typeof (e as Record<string, unknown>).msg === "string" ? (e as Record<string, unknown>).msg : null))
        .filter((m): m is string => !!m);
      if (msgs.length) return msgs.join(" ");
    }
  }
  return repli;
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
    const body = await res.json().catch(() => null);
    throw new Error(messageErreur(body, res.statusText));
  }
  return res.json() as Promise<T>;
}

/** Système de comptes (31/08/2026, remplace le mot de passe partagé) —
 * session posée en cookie httpOnly par le serveur, jamais manipulée côté JS
 * directement (cf. api/accounts.py). */
export interface MoiResponse {
  id: number;
  email: string;
  role: "read_only" | "edit" | "admin";
  status: "pending_email" | "pending_admin_activation" | "active" | "disabled";
}

export async function login(email: string, password: string): Promise<{ role: string; status: string }> {
  return request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
}

export async function logout(): Promise<void> {
  await request("/auth/logout", { method: "POST" });
}

export async function checkAuthStatus(): Promise<boolean> {
  const r = await request<{ authenticated: boolean }>("/auth/status");
  return r.authenticated;
}

/** `null` = pas connecté (401) plutôt qu'une exception — App.tsx distingue
 * ainsi "pas de session" de "erreur réseau" sans essayer/attraper partout. */
export async function fetchMoi(): Promise<MoiResponse | null> {
  try {
    return await request<MoiResponse>("/auth/me");
  } catch {
    return null;
  }
}

export async function signup(email: string, password: string): Promise<{ status: string }> {
  return request("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) });
}

export async function forgotPassword(email: string): Promise<void> {
  await request("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await request("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export interface McpKey {
  id: number;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface McpKeyCreated extends McpKey {
  token: string;
}

export async function listMcpKeys(): Promise<McpKey[]> {
  const r = await request<{ keys: McpKey[] }>("/auth/mcp-keys");
  return r.keys;
}

export async function createMcpKey(): Promise<McpKeyCreated> {
  return request("/auth/mcp-keys", { method: "POST" });
}

export async function revokeMcpKey(id: number): Promise<void> {
  await request(`/auth/mcp-keys/${id}`, { method: "DELETE" });
}

export interface AdminUser {
  id: number;
  email: string;
  role: "read_only" | "edit" | "admin";
  status: "pending_email" | "pending_admin_activation" | "active" | "disabled";
  created_at: string;
  email_confirmed_at: string | null;
  activated_at: string | null;
}

export async function adminListUsers(status?: string): Promise<AdminUser[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  const r = await request<{ users: AdminUser[] }>(`/admin/users${q}`);
  return r.users;
}

export async function adminUpdateUser(
  id: number,
  patch: { role?: string; status?: string },
): Promise<AdminUser> {
  return request(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
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

/** Crée une salle hors bâtiment (retour utilisateur 28/08/2026). Rend la
 * salle créée — l'appelant doit rafraîchir `payload` pour qu'elle apparaisse
 * dans les listes déjà rendues. */
export function creerSalle(body: { label: string; capacity: number }): Promise<{
  id: string;
  label: string;
  capacity: number;
  room_type: string;
}> {
  return request("/rooms", { method: "POST", body: JSON.stringify(body) });
}

/** Change UNIQUEMENT la salle, à créneau inchangé (retour utilisateur
 * 28/08/2026 : « on va vouloir sur la vue promo modifier uniquement les
 * salles »). Endpoint distinct de `movePlacement` : celui-ci refait tous les
 * contrôles de POSITION, qui peuvent refuser à tort une séance déjà posée à
 * une position limite (cf. api/main.py::changer_salle). */
/** Échange de place entre deux séances (`POST /placements/echanger`) — cf.
 * `utils/moveSession.ts::performSwap` pour le pourquoi d'un endpoint dédié
 * plutôt que deux déplacements enchaînés. */
export function echangerPlacements(
  sessionA: string,
  sessionB: string,
  force = false,
): Promise<{ placements: Placement[] }> {
  return request<{ placements: Placement[] }>("/placements/echanger", {
    method: "POST",
    body: JSON.stringify({ session_a: sessionA, session_b: sessionB, force }),
  });
}

export function lireNotifications(): Promise<NotificationConfig> {
  return request<NotificationConfig>("/notifications");
}

export function ecrireNotifications(patch: {
  destinataires?: string[];
  evenements?: Record<string, boolean>;
  delai_minutes?: number;
}): Promise<NotificationConfig> {
  return request<NotificationConfig>("/notifications", { method: "PUT", body: JSON.stringify(patch) });
}

export function testerNotifications(): Promise<{ envoye_a: string[] }> {
  return request<{ envoye_a: string[] }>("/notifications/test", { method: "POST" });
}

export function changerSalle(
  sessionId: string,
  body: { room_id: string; force?: boolean },
): Promise<Placement> {
  return request<Placement>(`/placements/${encodeURIComponent(sessionId)}/salle`, {
    method: "PATCH",
    body: JSON.stringify({ force: false, ...body }),
  });
}

// ── Séances personnalisées : ajouter/modifier/supprimer une séance sur une
// matière EXISTANTE (retour utilisateur 31/08/2026 : « il va falloir créer
// un système où l'on peut créer des cours pour une matière [...] imaginons
// dans une matière on veuille rajouter un CM éval ou un TD, il faut pouvoir
// le faire »). Distinct du reliquat « À placer » : ici on ajoute une heure
// que la maquette n'avait pas prévue, pas on place une heure qu'elle avait
// déjà prévue. Un seul écran choisit tout, y compris le créneau — décision
// explicite de l'utilisateur plutôt qu'un placement différé par clic sur la
// grille. ──

export interface CreerSeanceBody {
  course_code: string;
  session_type: string;
  group_ids: string[];
  teacher_codes: string[];
  duration_slots: number;
  is_eval: boolean;
  note?: string;
  week: number;
  day: number;
  slot: number;
  room_id?: string | null;
  force?: boolean;
}

export function creerSeancePersonnalisee(body: CreerSeanceBody): Promise<Placement> {
  return request<Placement>("/placements/personnalisees", {
    method: "POST",
    body: JSON.stringify({ force: false, ...body }),
  });
}

export interface ModifierSeanceBody {
  session_type?: string;
  group_ids?: string[];
  teacher_codes?: string[];
  duration_slots?: number;
  is_eval?: boolean;
  note?: string;
  week?: number;
  day?: number;
  slot?: number;
  room_id?: string | null;
  force?: boolean;
}

export function modifierSeancePersonnalisee(sessionId: string, body: ModifierSeanceBody): Promise<Placement> {
  return request<Placement>(`/placements/personnalisees/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export interface PatchSeanceMaquetteBody {
  session_type?: string;
  teacher_codes?: string[];
  duration_slots?: number;
  week?: number;
  day?: number;
  slot?: number;
  room_id?: string;
  is_eval?: boolean;
  force?: boolean;
}

export function modifierSeanceMaquette(sessionId: string, body: PatchSeanceMaquetteBody): Promise<Placement> {
  return request<Placement>(`/placements/${encodeURIComponent(sessionId)}/seance`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function supprimerSeancePersonnalisee(sessionId: string): Promise<{ supprimee: boolean }> {
  return request<{ supprimee: boolean }>(`/placements/personnalisees/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
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
  /** Première ouverture détectée (pixel de suivi). `null` ne prouve PAS que
   * le mail n'a pas été lu : beaucoup de clients bloquent les images. */
  opened_at: string | null;
}

/** Le mail EXACT tel qu'il partira pour ce destinataire — rendu par la même
 * fonction que l'envoi réel côté serveur, pour qu'un aperçu ne puisse pas
 * diverger de ce qui part vraiment. */
export function apercuMailProf(code: string): Promise<{ subject: string; text: string; html: string }> {
  return request(`/mail/teacher-links/apercu/${encodeURIComponent(code)}`);
}

export interface TeacherMailPreviewList {
  configured: boolean;
  /** Détail de ce qui manque quand `configured` est faux (retour
   * utilisateur 31/08/2026) — un message qui ne nomme pas la variable
   * absente fait chercher au mauvais endroit. */
  a_la_clef_api: boolean;
  a_url_publique: boolean;
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

export interface CelcatEtat {
  saisie_active: boolean;
  semaines_validees: number[];
  valide_le: string | null;
  dernier_job: Record<string, string> | null;
  compteurs: { created: number; modified: number; deleted: number; blocked: number };
  worker_ok: boolean;
}

export interface CelcatExtra {
  id: string;
  statut: string;
  course_code?: string;
  libelle?: string;
  module_nom?: string;
  event_id?: number;
}

export interface CelcatLog {
  kind: string;
  motif?: string | null;
  session_id?: string | null;
}

export function fetchCelcatEtat(): Promise<CelcatEtat> {
  return request("/celcat/etat");
}

export function patchCelcatSaisie(active: boolean): Promise<CelcatEtat> {
  return request("/celcat/saisie", { method: "PATCH", body: JSON.stringify({ active }) });
}

export function validerSemainesCelcat(semaines: number[]): Promise<CelcatEtat> {
  return request("/celcat/valider", { method: "POST", body: JSON.stringify({ semaines }) });
}

export function fetchCelcatExtras(statut = "ouvert"): Promise<{ extras: CelcatExtra[] }> {
  return request(`/celcat/extras?statut=${encodeURIComponent(statut)}`);
}

export function fetchCelcatLogs(limit = 50): Promise<{ items: CelcatLog[]; cursor: string | null }> {
  return request(`/celcat/logs?limit=${limit}`);
}

export function ignorerExtraCelcat(id: string): Promise<{ statut: string }> {
  return request(`/celcat/extras/${encodeURIComponent(id)}/ignorer`, { method: "POST" });
}

export function ajouterExtraCelcat(id: string): Promise<{ statut: string; session_id?: string }> {
  return request(`/celcat/extras/${encodeURIComponent(id)}/ajouter`, { method: "POST" });
}
