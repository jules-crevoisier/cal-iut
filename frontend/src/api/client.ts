import type {
  DiffResponse,
  FeedbackAnalysis,
  MetaResponse,
  NotificationConfig,
  Placement,
  TimetableResponse,
  ValidationResponse,
} from "../types";
import type { AppPayload } from "../types/app";

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
/** Exportée pour être testée directement (`utils/erreurConflit.test.ts`) :
 * c'est ici que le détail d'un conflit se perdait, et le symptôme visible
 * était à trois fichiers de là. */
export function messageErreur(body: unknown, repli: string): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.message === "string") return b.message;
    if (typeof b.detail === "string") return b.detail;
    // Détail STRUCTURÉ (`{"detail": {"message": ..., "hard_conflicts": [...]}}`)
    // — la forme que le serveur emploie pour tout conflit FORÇABLE. Elle
    // n'était pas reconnue : ni chaîne, ni tableau, on retombait sur le
    // `repli`, c'est-à-dire le statut HTTP (« Conflict »). `detailConflit`
    // ne pouvait alors plus rien y lire, et l'interface n'ouvrait jamais la
    // modale « forcer » — le changement de salle sur la semaine en cours
    // échouait sans un mot (retour utilisateur 08/09/2026).
    //
    // Sérialisé plutôt qu'aplati en texte : `detailConflit` le relit en
    // JSON pour retrouver `hard_conflicts` et `soft_warnings` séparément.
    if (b.detail && typeof b.detail === "object" && !Array.isArray(b.detail)) {
      return JSON.stringify(b.detail);
    }
    if (Array.isArray(b.detail)) {
      const msgs = b.detail
        .map((e) => (e && typeof e === "object" && typeof (e as Record<string, unknown>).msg === "string" ? (e as Record<string, unknown>).msg : null))
        .filter((m): m is string => !!m);
      if (msgs.length) return msgs.join(" ");
    }
  }
  return repli;
}

/** Nature d'un échec d'appel (audit du 29/09/2026, P1-13). Avant, toute
 * erreur se ressemblait : une coupure réseau affichait l'écran de connexion
 * (`fetchMoi`) ou « aucun planning » (`/app-state`).
 * - `session` : 401, la session n'existe pas ou plus → écran de connexion ;
 * - `panne` : pas de réponse exploitable (réseau coupé, délai dépassé, 5xx
 *   sans message de l'application — passerelle, plantage) → bandeau
 *   « Serveur injoignable », l'écran garde ce qu'il montrait ;
 * - `refus` : le serveur a répondu et dit pourquoi (4xx, ou 5xx avec un
 *   message de l'application) → message à l'endroit de l'action. */
export type GenreErreurApi = "session" | "panne" | "refus";

export class ErreurApi extends Error {
  readonly status: number | null;
  readonly genre: GenreErreurApi;

  constructor(message: string, status: number | null, genre: GenreErreurApi) {
    super(message);
    this.name = "ErreurApi";
    this.status = status;
    this.genre = genre;
  }
}

export function estPanne(e: unknown): boolean {
  return e instanceof ErreurApi && e.genre === "panne";
}

export function estSessionAbsente(e: unknown): boolean {
  return e instanceof ErreurApi && e.genre === "session";
}

/** Délai des LECTURES (GET). Toutes lisent l'état déjà en mémoire du
 * serveur (la plus lourde, `/app-state`, coûte ≈ 150 ms à recalculer) :
 * 30 s sans réponse, c'est une panne, pas une lenteur. Les ÉCRITURES n'en
 * ont volontairement aucun : certaines durent (envoi des mails aux
 * enseignants, un par un), et abandonner côté navigateur n'annulerait rien
 * côté serveur — on afficherait « échec » pour une action qui aboutit. */
export const DELAI_LECTURE_MS = 30_000;

/** État de la liaison avec le serveur, diffusé à qui l'écoute (`App.tsx`,
 * pour le bandeau de panne et l'écran de connexion). Une vue qui attrape
 * son erreur pour afficher son propre message n'empêche donc pas le
 * bandeau d'apparaître. */
export type EvenementLiaison = "panne" | "retablie" | "session-absente";
type EcouteurLiaison = (evenement: EvenementLiaison) => void;

const ecouteursLiaison = new Set<EcouteurLiaison>();
let liaisonEnPanne = false;

export function ecouterLiaison(ecouteur: EcouteurLiaison): () => void {
  ecouteursLiaison.add(ecouteur);
  return () => {
    ecouteursLiaison.delete(ecouteur);
  };
}

/** Pour les tests : repart d'une liaison saine, sans écouteur. */
export function reinitialiserLiaison(): void {
  ecouteursLiaison.clear();
  liaisonEnPanne = false;
}

function diffuser(evenement: EvenementLiaison): void {
  if (evenement === "panne") {
    liaisonEnPanne = true;
    ecouteursLiaison.forEach((e) => e("panne"));
    return;
  }
  // Toute réponse, même un refus, prouve que le serveur répond. « Rétablie »
  // n'est diffusé qu'en sortie de panne : pas un évènement par appel.
  const etaitEnPanne = liaisonEnPanne;
  liaisonEnPanne = false;
  if (etaitEnPanne) ecouteursLiaison.forEach((e) => e("retablie"));
  if (evenement === "session-absente") ecouteursLiaison.forEach((e) => e("session-absente"));
}

function panne(message: string, status: number | null): ErreurApi {
  diffuser("panne");
  return new ErreurApi(message, status, "panne");
}

/** Le corps porte-t-il un message de l'APPLICATION (`detail`/`message`) ?
 * Distingue un 503 voulu (« envoi de mail indisponible », `/health`
 * dégradé) d'un 502/503 de la passerelle ou d'un plantage (texte brut). */
function messageApplicatif(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  return typeof b.message === "string" || (b.detail !== undefined && b.detail !== null);
}

async function executer<T>(url: string, init?: RequestInit, delaiMs: number | null = null): Promise<T> {
  // Volontairement AUCUNE option `cache` : le mode par défaut laisse le
  // navigateur garder les réponses et les revalider lui-même (`If-None-Match`
  // sur l'ETag que pose le serveur, `Cache-Control: no-cache`). Tant que rien
  // n'a changé côté serveur, `/app-state` (≈ 590 Ko) revient en 304 vide et
  // le navigateur ressert sa copie — ce code n'en voit rien, il reçoit un 200
  // ordinaire. Un `cache: "no-store"` ici annulerait tout ce mécanisme.
  const controleur = delaiMs !== null && !init?.signal ? new AbortController() : null;
  const minuterie = controleur ? setTimeout(() => controleur.abort(), delaiMs ?? 0) : null;
  const expire = () => controleur?.signal.aborted === true;
  try {
    let res: Response;
    try {
      res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...init,
        ...(controleur ? { signal: controleur.signal } : {}),
      });
    } catch {
      throw panne(expire() ? "Le serveur ne répond pas (délai dépassé)." : "Serveur injoignable.", null);
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      if (res.status >= 500 && !messageApplicatif(body)) {
        throw panne(res.status === 500 ? "Le serveur a rencontré une erreur." : "Serveur injoignable.", res.status);
      }
      const message = messageErreur(body, res.statusText || `Erreur ${res.status}`);
      if (res.status === 401) {
        diffuser("session-absente");
        throw new ErreurApi(message, 401, "session");
      }
      diffuser("retablie");
      throw new ErreurApi(message, res.status, "refus");
    }
    let corps: T;
    try {
      corps = (await res.json()) as T;
    } catch {
      // Corps coupé (délai dépassé en pleine lecture) ou page HTML d'une
      // passerelle servie en 200 : pas une réponse de l'application.
      throw panne(expire() ? "Le serveur ne répond pas (délai dépassé)." : "Réponse du serveur illisible.", res.status);
    }
    diffuser("retablie");
    return corps;
  } finally {
    if (minuterie !== null) clearTimeout(minuterie);
  }
}

// Lectures (GET) en vol, par URL complète — cf. `request`.
const lecturesEnVol = new Map<string, Promise<unknown>>();

/** Nombre de lectures encore en vol — exposé pour les tests seulement. */
export function nombreLecturesEnVol(): number {
  return lecturesEnVol.size;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = accessToken
    ? `${BASE}${path}${path.includes("?") ? "&" : "?"}t=${encodeURIComponent(accessToken)}`
    : `${BASE}${path}`;
  const methode = (init?.method ?? "GET").toUpperCase();
  if (methode !== "GET" || init?.body !== undefined) return executer<T>(url, init);

  // Deux GET identiques lancés pendant qu'un premier est en vol partagent sa
  // réponse au lieu de repartir sur le réseau. Cas réel : au démarrage et
  // après chaque action, plusieurs effets d'`App.tsx` (et le rechargement
  // déclenché par `useRevision`) redemandaient `/app-state` en même temps.
  // L'objet rendu est PARTAGÉ entre les appelants : aucun ne doit le modifier
  // en place (aucun ne le fait aujourd'hui — ils le rangent tel quel dans un
  // état React). Retiré dès la réponse reçue : ce n'est pas un cache, le
  // cache reste celui du navigateur (ETag, cf. `executer`).
  const enVol = lecturesEnVol.get(url);
  if (enVol) return enVol as Promise<T>;
  const promesse = executer<T>(url, init, DELAI_LECTURE_MS).finally(() => lecturesEnVol.delete(url));
  lecturesEnVol.set(url, promesse);
  return promesse;
}

/** Système de comptes (31/08/2026, remplace le mot de passe partagé) —
 * session posée en cookie httpOnly par le serveur, jamais manipulée côté JS
 * directement (cf. api/accounts.py). */
/** `api` = « Accès API » (29/09/2026) : aucun écran de données, seulement
 * ses clés d'accès à l'API v1 en lecture (cf. `api/accounts.py::ROLE_API`). */
export type RoleCompte = "read_only" | "edit" | "admin" | "api";

export interface MoiResponse {
  id: number;
  email: string;
  role: RoleCompte;
  status: "pending_email" | "pending_admin_activation" | "active" | "disabled";
}

export async function login(email: string, password: string): Promise<{ role: string; status: string }> {
  return request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
}

export async function logout(): Promise<void> {
  await request("/auth/logout", { method: "POST" });
}

/** `null` = pas connecté (401). Toute autre erreur (panne réseau, serveur en
 * erreur) REMONTE : avant, elle rendait `null` elle aussi, et une coupure
 * réseau affichait l'écran de connexion à quelqu'un de bien connecté (audit
 * du 29/09/2026, P1-13). */
export async function fetchMoi(): Promise<MoiResponse | null> {
  try {
    return await request<MoiResponse>("/auth/me");
  } catch (e) {
    if (estSessionAbsente(e)) return null;
    throw e;
  }
}

/** Santé du serveur (`GET /health`). Un 503 `degraded` n'est pas une panne :
 * c'est le serveur qui dit qu'un planning est enregistré mais n'a pas pu
 * être chargé (audit du 29/09/2026, P1-6) — les écrans montreraient sinon un
 * planning vide sans que rien ne le signale. */
export interface EtatSante {
  status: "ok" | "degraded";
  detail?: string;
}

export async function fetchSante(): Promise<EtatSante> {
  try {
    return await request<EtatSante>("/health");
  } catch (e) {
    if (e instanceof ErreurApi && e.status === 503 && e.genre === "refus") {
      return { status: "degraded", detail: e.message };
    }
    throw e;
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
  /** Nom libre donné à la création — `null` pour les clés d'avant le 29/09/2026. */
  nom?: string | null;
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

export async function createMcpKey(nom?: string): Promise<McpKeyCreated> {
  const propre = nom?.trim();
  return request("/auth/mcp-keys", { method: "POST", body: JSON.stringify(propre ? { nom: propre } : {}) });
}

export async function revokeMcpKey(id: number): Promise<void> {
  await request(`/auth/mcp-keys/${id}`, { method: "DELETE" });
}

export interface AdminUser {
  id: number;
  email: string;
  role: RoleCompte;
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

/** Suppression physique (25/09/2026, retour utilisateur Jules : « supprimer
 * les personnes en attente d'activation ») — réservée par le serveur aux
 * comptes jamais activés (`pending_email`/`pending_admin_activation`,
 * `Depends(require_role("admin"))` + `accounts.PENDING_STATUSES` côté
 * `api/main.py`) ; un compte déjà actif renvoie un 409 avec `message`. */
export async function adminDeleteUser(id: number): Promise<void> {
  await request(`/admin/users/${id}`, { method: "DELETE" });
}

// ── Sauvegardes JSON datées (item B, 22/09/2026) ──
// Todo : « Avoir un fichier JSON backup des semaines et séances placées à
// une date précise ». Réservé admin côté serveur (`Depends(require_role(
// "admin"))`, cf. `api/main.py`) — pas de vérification de rôle ici, même
// principe que `adminListUsers`/`adminUpdateUser` juste au-dessus.

export interface SauvegardeMeta {
  date: string; // AAAA-MM-JJ
  taille_octets: number;
  nb_placements: number;
}

export async function listSauvegardes(): Promise<SauvegardeMeta[]> {
  const r = await request<{ sauvegardes: SauvegardeMeta[] }>("/sauvegardes");
  return r.sauvegardes;
}

export async function creerSauvegardeMaintenant(): Promise<SauvegardeMeta> {
  return request<SauvegardeMeta>("/sauvegardes", { method: "POST" });
}

/** URL de téléchargement direct — même patron que `exportCsvUrl()` :
 * `window.open(sauvegardeUrl(jour), "_blank")`, jamais un `fetch` (laisse le
 * navigateur gérer le téléchargement du fichier). */
export function sauvegardeUrl(jour: string): string {
  return `${BASE}/sauvegardes/${encodeURIComponent(jour)}`;
}

// ── Anti-aspiration (29/09/2026, cf. api/anti_aspiration.py et
// docs/ANTI-ASPIRATION.md) — écran « Trafic », réservé admin côté serveur.

export type ModeAntiAspiration = "off" | "observe" | "enforce";
export type FenetreTrafic = "15min" | "1h" | "24h";
export type TypeBlocage = "ip" | "cidr" | "user_agent";

export interface BudgetTrafic {
  categorie: string;
  nombre: number;
  periode_s: number;
  rafale: number;
  description: string;
}

export interface ClientTrafic {
  ip: string;
  requetes: number;
  requetes_15min: number;
  requetes_1h: number;
  requetes_24h: number;
  /** Part des requêtes sans compte (liens publics, flux, sondes), 0 à 1. */
  part_publique: number;
  /** Requêtes au-delà du budget (refusées en mode blocage, seulement
   *  comptées en observation). */
  depassements: number;
  /** Refusées par la liste de blocage. */
  refus_403: number;
  /** 401/403 rendus par l'application (routes fermées) : ce que compte le
   *  bannissement sur refus d'accès répétés. */
  refus_acces: number;
  user_agent: string;
  user_agents_distincts: number;
  chemins: Array<{ chemin: string; nb: number }>;
  categorie: string;
  compte_id: number | null;
  compte_email: string | null;
  /** Liens `?t=` différents vus pour cette IP (un humain en ouvre 1 à 3). */
  liens_distincts: number;
  dernier_passage: string;
  blocage_id: string | null;
}

export interface TraficResponse {
  mode: ModeAntiAspiration;
  variable: string;
  comptage_actif: boolean;
  fenetre: FenetreTrafic;
  genere_le: string;
  /** Protections toujours actives, distinctes de la limitation de débit. */
  protections: {
    actives: boolean;
    variable: string;
    refus_actif: boolean;
    refus_variable: string;
    refus_seuil: number;
    refus_fenetre_s: number;
    refus_duree_s: number;
  };
  budgets: BudgetTrafic[];
  bannissement: { seuil: number; fenetre_s: number; duree_s: number };
  exemptes: string[];
  resume: {
    requetes: number;
    clients: number;
    depassements: number;
    refus_403: number;
    refus_acces: number;
    ip_bloquees: number;
  };
  clients: ClientTrafic[];
}

export interface Blocage {
  id: string;
  type: TypeBlocage;
  valeur: string;
  motif: string;
  auteur: string;
  cree_le: string;
  expire_le: string | null;
  automatique: boolean;
  /** « refus » : 401/403 répétés (toujours actif) ; « debit » : 429 répétés
   *  (limitation de débit en mode blocage). */
  source: "manuel" | "refus" | "debit";
}

export interface NouveauBlocage {
  type: TypeBlocage;
  valeur: string;
  motif: string;
  /** "1h", "24h", "7j" ; `null` = permanent. */
  duree: string | null;
  /** Le blocage viserait l'administrateur lui-même : confirmé. */
  forcer?: boolean;
}

export function fetchTrafic(fenetre: FenetreTrafic): Promise<TraficResponse> {
  return request<TraficResponse>(`/admin/trafic?fenetre=${encodeURIComponent(fenetre)}`);
}

export async function listBlocages(): Promise<Blocage[]> {
  const r = await request<{ blocages: Blocage[] }>("/admin/blocages");
  return r.blocages;
}

export function creerBlocage(corps: NouveauBlocage): Promise<Blocage> {
  return request<Blocage>("/admin/blocages", { method: "POST", body: JSON.stringify(corps) });
}

export async function supprimerBlocage(id: string): Promise<void> {
  await request(`/admin/blocages/${encodeURIComponent(id)}`, { method: "DELETE" });
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

/** Révision de l'état côté serveur (`GET /api/v1/version`, cf.
 * `api/revision.py`) — quelques octets, avance à chaque modification visible
 * par qui que ce soit. Sondée par `hooks/useRevision.ts` pour ne recharger
 * l'état complet QUE quand elle a bougé. */
export interface VersionEtat {
  revision: number;
  modifie_le: string;
}

export function fetchVersion(): Promise<VersionEtat> {
  return request<VersionEtat>("/api/v1/version");
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
 * dans les listes déjà rendues. `placement_auto` coché par défaut (absent =
 * `true` côté serveur) — retour utilisateur 22/09/2026. */
export function creerSalle(body: { label: string; capacity: number; placement_auto?: boolean }): Promise<{
  id: string;
  label: string;
  capacity: number;
  room_type: string;
  placement_auto: boolean;
}> {
  return request("/rooms", { method: "POST", body: JSON.stringify(body) });
}

/** Modifie une salle EXISTANTE (bâtiment ou perso) — réservé admin. Retour
 * utilisateur 22/09/2026 : « supprimer la BU du placement automatique des
 * salles car elle est utilisée pour un seul module, celui de Valérie
 * Mariot ». Persisté côté serveur dans l'overlay salles perso, y compris
 * pour une salle du bâtiment (`rooms.yaml` n'est jamais réécrit) — survit
 * donc à un redéploiement sans correctif de code. */
export function modifierSalle(roomId: string, body: { placement_auto: boolean }): Promise<{
  id: string;
  label: string;
  capacity: number;
  room_type: string;
  placement_auto: boolean;
}> {
  return request(`/rooms/${encodeURIComponent(roomId)}`, { method: "PATCH", body: JSON.stringify(body) });
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

// ── Évènement hors maquette (réunion, conférence...) affiché en clair sur
// l'EDT — retour utilisateur 07/09/2026, étendu le 23/09/2026 (Kyllian
// Bresson : « m'ajouter une séance évènement [...] à 13h15 jusqu'à 14h »)
// d'un horaire réel optionnel, quand les six créneaux fixes ne suffisent
// pas (ex. pause méridienne). Distinct de `CreerSeanceBody` : `libelle`
// invente son propre `course_code`, jamais besoin d'une matière connue. ──

export interface CreerEvenementBody {
  libelle: string;
  semestre: string;
  group_ids: string[];
  teacher_codes: string[];
  duration_slots: number;
  note?: string;
  week: number;
  day: number;
  slot: number;
  room_id?: string | null;
  force?: boolean;
  /** Optionnels, toujours ensemble, format "HH:MM" — cf. hint du formulaire :
   * une heure entre 12h30 et 14h s'affiche dans la pause méridienne. */
  heure_debut?: string | null;
  heure_fin?: string | null;
}

export function creerEvenement(body: CreerEvenementBody): Promise<Placement> {
  return request<Placement>("/placements/evenements", {
    method: "POST",
    body: JSON.stringify({ force: false, ...body }),
  });
}

export interface ModifierSeanceBody {
  course_code?: string;
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
  heure_debut?: string | null;
  heure_fin?: string | null;
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

/** Retire une séance du planning SANS la supprimer du catalogue — elle
 * rejoint « À placer » et peut être reposée plus tard. Retour utilisateur
 * (03/09/2026) : un enseignant ne sait parfois pas encore quand il sera
 * disponible ; endpoint déjà là côté serveur (`api/deposer.py`), jamais
 * relié à l'interface jusqu'ici. */
export function deposerPlacement(sessionId: string): Promise<{ ok: boolean; session_id: string; deposee: boolean }> {
  return request(`/placements/${encodeURIComponent(sessionId)}/deposer`, { method: "POST" });
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
  /** Le worker du sidecar tourne-t-il ? Le mettre en pause libère le VPN,
   *  partagé avec le compte Celcat de l'équipe, SANS vider la file. */
  worker_actif?: boolean;
  semaines_validees: number[];
  semaines_passees: number[];
  semaines_lancees: number[];
  semaines_creation_autorisee?: number[];
  semaines_completes: number[];
  valide_le: string | null;
  dernier_job: Record<string, string> | null;
  derniere_ecriture_celcat: string | null;
  compteurs: { created: number; modified: number; deleted: number; blocked: number };
  worker_ok: boolean;
  /** Règles d'envoi (WR100BU, PTUT) actives ? Variable d'environnement
   *  `CAL_IUT_REGLES_ENVOI` (`off` par défaut) des services backend et celcat-nuit. */
  regles_envoi_actives?: boolean;
  variable_regles_envoi?: string;
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
  /** Permet d'aller vérifier l'évènement dans Celcat — une ligne sans lui
   * ne sert qu'à compter. */
  event_id?: number | null;
  course_code?: string | null;
  at?: string | null;
  /** Tentatives d'un échec qui se répète : le worker retente toutes les 30 à
   * 60 s, et ces tentatives sont regroupées sur une seule ligne côté serveur
   * (cf. `celcat/logs.py`). « 87 tentatives » vaut mieux que 87 lignes. */
  repetitions?: number | null;
}

/** Ce que le sidecar a relevé dans Celcat, et QUAND. L'API ne lit jamais
 * Celcat elle-même (son conteneur n'a ni VPN ni navigateur) : elle sert un
 * relevé déposé dans le volume partagé, d'où l'âge et `perime`. */
export interface CelcatInstantane {
  evenements: Array<Record<string, unknown>>;
  groupes: string[];
  releve_le: string | null;
  age_secondes: number | null;
  perime: boolean;
  demande_en_cours: boolean;
  erreur: string | null;
  nb_evenements?: number;
  nb_groupes?: number;
}

/** Une ligne de la comparaison Celcat / cal-iut. Le rapprochement est fait
 * PAR LE SERVEUR : ses règles (matière, groupe, jour, et l'heure avec son
 * décalage de 9'21" dû au fuseau historique de Paris) y sont déjà testées.
 * Les réimplémenter ici garantirait qu'elles divergent, et une comparaison
 * fausse est pire qu'aucune : elle enverrait corriger ce qui va bien. */
export interface LigneComparaison {
  /** « hors_celcat » : séance sans équivalent module dans Celcat (BU,
   * évènements officiels). Ce n'est pas un écart — rien à y corriger. */
  statut: "identique" | "ecart" | "absente_celcat" | "en_trop_celcat" | "hors_celcat";
  session_id: string;
  course_code: string;
  caliut: { jour: number | null; heure: string; salle: string | null; semaine: number | null } | null;
  celcat: {
    event_id: number | null;
    jour: number | null;
    heure: string | null;
    salle: string | null;
    /** Toutes les salles de l'évènement. Un cours posé sur deux salles à la
     *  fois est un écart, et l'écran doit pouvoir dire lesquelles. */
    salles: string[] | null;
    categorie: string | null;
    module: string | null;
    groupe: string | null;
  } | null;
  ecarts: string[];
}

export interface CelcatComparaison {
  semaine: number;
  semaine_celcat: number;
  /** Lundi de la semaine : « lundi 07/09 » se vérifie d'un coup d'oeil,
   * « semaine 1 » demande de compter. */
  lundi: string | null;
  releve_le: string | null;
  age_secondes: number | null;
  perime: boolean;
  lignes: LigneComparaison[];
}

/** Un écart que le serveur n'a PAS su traduire en correction, et pourquoi.
 *
 * Ces cas tombaient dans un `continue` muet : le tableau annonçait neuf
 * écarts, le message cinq corrections, et rien n'expliquait les quatre
 * autres. Un compteur qui ne tombe pas juste, sans explication, apprend à
 * ne plus faire confiance à l'écran. */
export interface EcartAbandonne {
  statut: string;
  session_id: string;
  course_code: string;
  event_id: number | null;
  groupe: string | null;
  /** Repère machine : `event_id_absent`, `groupe_inconnu`,
   *  `suppression_epargnee`. */
  raison: string;
  /** La même chose en français, prête à afficher. */
  explication: string;
}

export interface CelcatCorrection {
  modifications: number;
  creations: number;
  suppressions: number;
  total: number;
  hors_celcat: number;
  /** Suppressions volontairement laissées de côté (`supprimer: false`). */
  suppressions_ignorees: number;
  /** Corrections qui attendaient DÉJÀ d'être poussées, donc non rajoutées.
   *
   *  C'est la réponse à « j'ai cliqué trois fois et rien ne bouge » : le
   *  serveur déduplique, et l'écran annonçait quand même le compte entier à
   *  chaque clic. Optionnel : un serveur plus ancien ne le renvoie pas. */
  deja_en_file?: number;
  abandonnes?: EcartAbandonne[];
  message: string;
}

/** Pousse les écarts d'une semaine vers Celcat — via la FILE d'attente, donc
 * avec tous les garde-fous du worker. N'écrit jamais directement. */
/** `supprimer: false` pousse modifications et créations sans toucher aux
 *  « en trop » — le mode à employer quand quelqu'un travaille dans Celcat en
 *  même temps : un écart se rattrape, une suppression non. */
export function corrigerEcartsCelcat(
  semaine: number,
  options?: { supprimer?: boolean },
): Promise<CelcatCorrection> {
  const suffixe = options?.supprimer === false ? "&supprimer=false" : "";
  return request(`/celcat/comparaison/corriger?semaine=${semaine}${suffixe}`, { method: "POST" });
}

export function fetchCelcatComparaison(semaine: number): Promise<CelcatComparaison> {
  return request(`/celcat/comparaison?semaine=${semaine}`);
}

/** Ce qu'une resynchronisation a jeté, et ce qu'elle a reconstruit. */
export interface CelcatResync extends CelcatCorrection {
  semaines: number[];
  retires: number;
}

/** Repart de la comparaison : jette les jobs en attente sur ces semaines et
 *  ré-enfile uniquement ce qui diverge réellement. Sans `semaines`, le
 *  serveur prend celles que l'établissement a validées. */
export function resynchroniserFileCelcat(
  semaines?: number[],
  options?: { supprimer?: boolean },
): Promise<CelcatResync> {
  const params = new URLSearchParams();
  if (semaines && semaines.length) params.set("semaines", semaines.join(","));
  if (options?.supprimer === false) params.set("supprimer", "false");
  const q = params.toString();
  return request(`/celcat/file/resynchroniser${q ? `?${q}` : ""}`, { method: "POST" });
}

/** Ce qui attend d'être poussé, et ce que le worker a fait en dernier. Les
 * deux ensemble : une file qui ne bouge pas malgré des passages réguliers
 * est le signe d'une panne. */
export interface CelcatFile {
  en_attente: number;
  par_action: Record<string, number>;
  passe_le: string | null;
  age_secondes: number | null;
  reussis: number;
  echecs: number;
  ignores: number;
  /** Jobs en attente d'une semaine encore non posée dans Celcat — ni un
   *  échec ni un abandon (consigne du 08/09/2026). */
  differes: number;
  resume: string;
}

/** Une correspondance ajoutée depuis l'écran, par-dessus `celcat.yaml`. */
export interface CelcatMapping {
  cle: string;
  valeur: string;
  ajoute_le: string | null;
  ajoute_par: string;
}

/** Une cause de blocage, telle que le worker l'a journalisée.
 *
 *  `famille` et `cle` disent si l'écran peut la régler lui-même : une salle
 *  sans équivalent se mappe, une séance disparue de la maquette non. */
export interface CelcatBlocage {
  motif: string;
  seances: string[];
  tentatives: number;
  famille: FamilleMappingCelcat | "";
  cle: string;
  /** Aucune des séances concernées n'est placée au planning : ce blocage
   *  n'appartient donc à AUCUNE semaine. Le ranger sous celle qu'on regarde
   *  le ferait apparaître là où la comparaison ne mentionne rien. */
  sans_semaine?: boolean;
}

/** `matieres` (29/09/2026) : code de cours -> code module Celcat (`TSB…`). */
export type FamilleMappingCelcat = "salles" | "enseignants" | "matieres";

export interface CelcatMappings {
  salles: CelcatMapping[];
  enseignants: CelcatMapping[];
  /** Absent d'un serveur plus ancien. */
  matieres?: CelcatMapping[];
  /** Codes modules relevés (`celcat_matieres.yaml`) : les seuls acceptés. */
  matieres_celcat?: string[];
  /** Les salles que Celcat contient réellement, relevées sur l'instantané :
   *  choisir dans une liste vraie évite d'inventer un nom que l'écriture
   *  refusera ensuite en silence. */
  salles_celcat: string[];
  manquants: CelcatBlocage[];
  /** Ce qui bloque sur d'AUTRES semaines — compté, jamais tu : filtrer sans
   *  le dire ferait croire que le reste s'est réglé. */
  bloques_autres_semaines?: number;
}

/** `semaine` restreint les blocages à celle qu'on regarde. */
export function fetchCelcatMappings(semaine?: number | null): Promise<CelcatMappings> {
  const q = semaine === null || semaine === undefined ? "" : `?semaine=${semaine}`;
  return request(`/celcat/mappings${q}`);
}

/** Ajoute ou corrige une correspondance. Prend effet au passage suivant du
 *  worker, sans redéploiement : les séances bloquées repartent seules. */
export function definirMappingCelcat(
  famille: FamilleMappingCelcat,
  cle: string,
  valeur: string,
  semaine?: number | null,
): Promise<CelcatMappings> {
  const q = semaine === null || semaine === undefined ? "" : `?semaine=${semaine}`;
  return request(`/celcat/mappings${q}`, {
    method: "PUT",
    body: JSON.stringify({ famille, cle, valeur }),
  });
}

export function oublierMappingCelcat(
  famille: FamilleMappingCelcat,
  cle: string,
  semaine?: number | null,
): Promise<CelcatMappings> {
  const s = semaine === null || semaine === undefined ? "" : `&semaine=${semaine}`;
  return request(
    `/celcat/mappings?famille=${encodeURIComponent(famille)}&cle=${encodeURIComponent(cle)}${s}`,
    { method: "DELETE" },
  );
}

export function fetchCelcatFile(): Promise<CelcatFile> {
  return request("/celcat/file");
}

/** `leger` (le défaut) omet les 2337 évènements — 790 Ko qu'aucun écran
 *  n'affiche, et dont le poids faisait échouer l'appel. */
export function fetchCelcatInstantane(leger = true): Promise<CelcatInstantane> {
  return request(`/celcat/instantane${leger ? "?leger=1" : ""}`);
}

/** Demande un relevé. Le sidecar l'honore à son prochain passage (moins
 * d'une minute) : ce n'est pas un ordre immédiat, et l'interface ne doit pas
 * laisser croire le contraire. */
export function rafraichirCelcatInstantane(): Promise<{ demande: boolean; message: string }> {
  return request("/celcat/instantane/rafraichir", { method: "POST" });
}

/** Une correction encore en vol pour une semaine, retrouvée après avoir
 *  quitté l'onglet Celcat puis y être revenu (retour utilisateur du
 *  25/09/2026). L'état vit CÔTÉ SERVEUR, jamais dans ce navigateur : Jules et
 *  Kyllian travaillent depuis des postes différents, et c'est le MÊME worker
 *  qu'ils attendent tous les deux.
 *
 *  `etat` :
 *  - "absente" : rien en file pour cette semaine, ou déjà résolu ;
 *  - "en_cours" : mise en file, en attente du worker et/ou d'un relevé frais ;
 *  - "termine" : le worker est repassé ET un relevé plus récent est arrivé ;
 *  - "expire" : le délai généreux (45 min) a couru sans conclure — les jobs
 *    restent en file, seul CE SUIVI a cessé d'être fiable. */
export interface CelcatCorrectionEnCours {
  semaine: number;
  etat: "absente" | "en_cours" | "termine" | "expire";
  mise_en_file_le: string | null;
  par: string;
  total: number;
  message: string;
}

export function fetchCelcatCorrectionEnCours(semaine: number): Promise<CelcatCorrectionEnCours> {
  return request(`/celcat/comparaison/en-cours?semaine=${semaine}`);
}

/** Geste manuel de secours seulement — le suivi s'efface déjà tout seul une
 *  fois le travail fini ou périmé. Ne touche jamais la file elle-même. */
export function effacerCelcatCorrectionEnCours(semaine: number): Promise<CelcatCorrectionEnCours> {
  return request(`/celcat/comparaison/en-cours?semaine=${semaine}`, { method: "DELETE" });
}

/**
 * Autorise (ou retire l'autorisation de) la CRÉATION sur une semaine que
 * Celcat a encore vide — signalement du 28/09/2026 : « elle est en lancé
 * mais elle n'est toujours pas passée ». Le worker refuse par défaut de
 * créer sur une semaine non posée ; ceci est la levée, semaine par semaine.
 * `semaineCelcat` est l'indice du MASQUE Celcat (`comparaison.semaine_celcat`).
 */
export function autoriserCreationSemaineCelcat(semaineCelcat: number, autorisee: boolean): Promise<CelcatEtat> {
  return request<CelcatEtat>("/celcat/semaines/creation", {
    method: "PATCH",
    body: JSON.stringify({ semaine_celcat: semaineCelcat, autorisee }),
  });
}

export function fetchCelcatEtat(): Promise<CelcatEtat> {
  return request("/celcat/etat");
}

export function patchCelcatSaisie(active: boolean): Promise<CelcatEtat> {
  return request("/celcat/saisie", { method: "PATCH", body: JSON.stringify({ active }) });
}

/** Marche/pause du worker du sidecar.
 *
 *  À NE PAS CONFONDRE avec `patchCelcatSaisie` : couper la saisie VIDE la
 *  file d'attente côté serveur. Cette pause-ci ne détruit rien — elle rend
 *  seulement le VPN, et le worker reprend là où il s'était arrêté. */
export function patchCelcatWorker(actif: boolean): Promise<CelcatEtat> {
  return request("/celcat/worker", { method: "PATCH", body: JSON.stringify({ actif }) });
}

export function validerSemainesCelcat(semaines: number[]): Promise<CelcatEtat> {
  return request("/celcat/valider", { method: "POST", body: JSON.stringify({ semaines }) });
}

export function lancerNuitCelcat(): Promise<CelcatEtat> {
  return request("/celcat/lancer-nuit", { method: "POST" });
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

/** Kanban « Tâches » (22/09/2026, retour utilisateur Jules) — tâches
 *  HUMAINES partagées par l'équipe, distinctes de « À traiter » (généré
 *  automatiquement). Reflète `api/schemas.py::TacheResponse`. */
export interface Tache {
  id: number;
  titre: string;
  description: string | null;
  colonne: "a_faire" | "en_cours" | "fait";
  ordre: number;
  enseignant_code: string | null;
  /** Qui doit agir (texte libre, ex. « Jules », « Kyllian ») — 25/09/2026. */
  concerne: string | null;
  /** Onglet du kanban (Jules, dicté 25/09/2026 : « entre les affaires par
   *  rapport à l'emploi du temps [...] et les affaires à propos de la
   *  plateforme ») — toujours "edt" ou "plateforme" en sortie d'API, jamais
   *  `null` (une carte antérieure à ce champ est lue comme "edt" côté
   *  serveur, cf. `api/main.py::_tache_to_response`). */
  categorie: "edt" | "plateforme";
  /** Urgence (même demande, 25/09/2026) — toujours "normale" ou "urgente"
   *  en sortie d'API, même raisonnement que `categorie`. */
  priorite: "normale" | "urgente";
  date_debut: string | null; // ISO "AAAA-MM-JJ"
  date_fin: string | null; // ISO "AAAA-MM-JJ"
  cree_par: string;
  cree_le: string;
  maj_le: string;
  fait_le: string | null;
  /** Images jointes (30/09/2026). Facultatif : un serveur plus ancien que
   * l'interface ne l'envoie pas (déploiements décalés) — lire `?? []`. */
  images?: ImageTache[];
}

/** Image jointe à une tâche — cf. `api/pieces_jointes.py` côté serveur. */
export interface ImageTache {
  id: number;
  nom: string;
  type: string;
  taille: number;
  largeur: number | null;
  hauteur: number | null;
  cree_par: string;
  cree_le: string;
  /** `src` à utiliser tel quel (même origine, cookie de session). */
  url: string;
}

/** Limites du serveur, reprises pour refuser tout de suite côté interface
 * (le serveur reste seul juge : types vérifiés sur le contenu). */
export const IMAGES_TACHE = {
  max: 10,
  tailleMax: 8 * 1024 * 1024,
  types: ["image/png", "image/jpeg", "image/webp", "image/gif"],
} as const;

export interface TacheCreateBody {
  titre: string;
  description?: string | null;
  colonne?: Tache["colonne"];
  ordre?: number | null;
  enseignant_code?: string | null;
  concerne?: string | null;
  categorie?: Tache["categorie"];
  priorite?: Tache["priorite"];
  date_debut?: string | null;
  date_fin?: string | null;
}

export type TachePatchBody = Partial<TacheCreateBody>;

export function fetchTaches(): Promise<Tache[]> {
  return request("/taches");
}

export function creerTache(body: TacheCreateBody): Promise<Tache> {
  return request("/taches", { method: "POST", body: JSON.stringify(body) });
}

export function patchTache(id: number, body: TachePatchBody): Promise<Tache> {
  return request(`/taches/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function supprimerTache(id: number): Promise<{ deleted: boolean }> {
  return request(`/taches/${id}`, { method: "DELETE" });
}

/** Une image par appel (multipart, champ `fichier`) ; rend la tâche à jour. */
export function envoyerImageTache(tacheId: number, fichier: File): Promise<Tache> {
  const corps = new FormData();
  corps.append("fichier", fichier, fichier.name);
  // `headers` vide : le navigateur pose lui-même le `Content-Type`
  // multipart avec sa frontière (le défaut JSON d'`executer` le casserait).
  return request(`/taches/${tacheId}/images`, { method: "POST", body: corps, headers: {} });
}

export function supprimerImageTache(tacheId: number, imageId: number): Promise<Tache> {
  return request(`/taches/${tacheId}/images/${imageId}`, { method: "DELETE" });
}

// ── Doublons salle / enseignant (retour Kyllian Bresson 25/09/2026) ──
// « une possibilité de vérification après placement pour salles et
// enseignants en double [...] que je puisse corriger cela rapidement » —
// cf. `api/doublons.py` côté serveur (module pur) pour le calcul.

export interface DoublonSeance {
  session_id: string;
  course_code: string;
  /** `group_ids` bruts — résolus en libellés côté client, même convention
   * que `payload.groupLabels` ailleurs (todo.ts, kanban.ts). */
  groupes: string[];
  salle: string | null;
  /** Codes enseignants bruts — résolus via `payload.teacherLabels`. */
  enseignants: string[];
}

export interface Doublon {
  /** Indice SOLVEUR de la semaine (jamais l'indice d'affichage) — cf.
   * mémoire projet « Trois numérotations de semaines ». */
  semaine: number;
  jour: number;
  creneau: number;
  type: "salle" | "enseignant";
  /** Nom de l'enseignant (déjà résolu côté serveur) ou libellé(s) de
   * salle(s) — jamais un code brut pour ce champ précis. */
  ressource: string;
  seances: DoublonSeance[];
}

export function fetchDoublons(semaine?: number | null): Promise<Doublon[]> {
  const q = semaine === null || semaine === undefined ? "" : `?semaine=${semaine}`;
  return request<{ doublons: Doublon[] }>(`/controles/doublons${q}`).then((r) => r.doublons);
}

// ── Contrôle hebdomadaire des doublons (Jules Crevoisier, 25/09/2026) ──
// « on veut faire quelque chose qui vérifie chaque semaine [...] » — filet
// automatique côté serveur (`api/controle_doublons_hebdo.py`), ces deux
// fonctions ne font que lire le dernier résultat et le déclencher à la
// demande (« Vérifier maintenant »).

export interface DoublonHebdoRun {
  /** AAAA-MM-JJ — jour calendaire où le contrôle a tourné. */
  date: string;
  /** AAAA-Www (ISO 8601), ex. « 2026-W39 » — période du filet, jamais une
   * semaine solveur/grille. */
  semaine_iso: string;
  genere_le: string;
  total: number;
  par_type: Record<string, number>;
  doublons: Doublon[];
  /** Apparus depuis le contrôle PRÉCÉDENT (clé stable semaine/jour/créneau/
   * type/ressource) — vide au tout premier contrôle (`premier_controle`). */
  nouveaux: Doublon[];
  resolus: Doublon[];
  /** `true` si aucun contrôle n'existait avant celui-ci — `nouveaux`/
   * `resolus` n'ont alors aucun sens (rien à comparer). */
  premier_controle: boolean;
}

export function fetchControleDoublonsHebdo(): Promise<DoublonHebdoRun | null> {
  return request<{ dernier: DoublonHebdoRun | null }>("/controles/doublons/hebdo").then((r) => r.dernier);
}

export function executerControleDoublonsHebdo(): Promise<DoublonHebdoRun> {
  return request<DoublonHebdoRun>("/controles/doublons/hebdo", { method: "POST" });
}

// ── Compléter une information de référence manquante (29/09/2026) ──
// « quand on a un email manquant, peut-être un numéro de salle Celcat
// manquant, etc., il faut pouvoir ajouter l'info et l'enregistrer » — cf.
// `api/reference.py`. Une seule liste des manques (`GET /reference/manques`),
// relue par chaque écran qui en signale un, et une route par famille.

export type FamilleManque = "enseignant" | "salle" | "cours" | "groupe" | "seance";
export type ChampManque = "email" | "nom" | "code_celcat" | "capacite" | "type" | "intitule" | "id_celcat" | "salle";
export type GraviteManque = "bloque_celcat" | "bloque_envoi_liens" | "cosmetique";

export interface Manque {
  id: string;
  famille: FamilleManque;
  cle: string;
  libelle: string;
  champ: ChampManque;
  champ_libelle: string;
  gravite: GraviteManque;
  usage: string;
  nb_seances: number;
  /** Rôle qui peut compléter depuis l'appli ; `null` = fichier de configuration. */
  role_requis: "edit" | "admin" | null;
  ou_completer: string;
  /** Écran où compléter (champs de `Route`). */
  ecran: Record<string, string | number>;
}

export interface ListeManques {
  revision: number;
  modifie_le: string;
  total: number;
  par_gravite: Record<string, number>;
  par_famille: Record<string, number>;
  manques: Manque[];
}

export interface ReferenceEnregistree {
  famille: FamilleManque;
  cle: string;
  valeurs: Record<string, string | number>;
  message: string;
  revision: number;
}

export function fetchManques(): Promise<ListeManques> {
  return request<ListeManques>("/reference/manques");
}

export function completerContactEnseignant(code: string, email: string): Promise<ReferenceEnregistree> {
  return request(`/reference/enseignants/${encodeURIComponent(code)}/contact`, {
    method: "PUT",
    body: JSON.stringify({ email }),
  });
}

export function completerEnseignant(
  code: string,
  body: {
    nom?: string;
    code_celcat?: string;
    prenom?: string;
    nom_famille?: string;
    telephone?: string;
    type?: string;
  },
): Promise<ReferenceEnregistree> {
  return request(`/reference/enseignants/${encodeURIComponent(code)}`, { method: "PUT", body: JSON.stringify(body) });
}

// ── « Nouvel intervenant » (30/09/2026, administrateurs) ──

export interface SaisieIntervenant {
  nom: string;
  code: string;
  code_celcat?: string;
  email?: string;
  /** Facultatifs (01/10/2026). */
  telephone?: string;
  type?: string;
}

export interface ErreurIntervenant {
  champ: "nom" | "code" | "code_celcat" | "email" | "telephone" | "type";
  statut: number;
  message: string;
  code_existant: string | null;
}

export interface AvertissementIntervenant {
  type: "code_dans_celcat" | "code_celcat_pris" | "nom_proche";
  titre: string;
  message: string;
  code_existant: string | null;
  nom_existant: string | null;
  /** `code_existant` a une fiche dans l'appli : lien vers elle. */
  fiche: boolean;
  /** « Créer quand même » ne suffit pas : corriger la saisie. */
  bloquant: boolean;
}

export interface VerificationIntervenant {
  code: string;
  nom: string;
  email: string | null;
  code_celcat: string | null;
  telephone?: string | null;
  type?: "enseignant" | "vacataire" | null;
  erreurs: ErreurIntervenant[];
  avertissements: AvertissementIntervenant[];
  suggestion_code: string | null;
  peut_creer: boolean;
}

export interface IntervenantCree {
  code: string;
  nom: string;
  email: string | null;
  code_celcat: string | null;
  telephone?: string | null;
  type?: "enseignant" | "vacataire" | null;
  cree_le: string;
  avertissements_confirmes: AvertissementIntervenant[];
  message: string;
  revision: number;
}

/** Validation en direct de la modale : rien n'est écrit. */
export function verifierIntervenant(saisie: SaisieIntervenant): Promise<VerificationIntervenant> {
  return request("/reference/enseignants/verifier", { method: "POST", body: JSON.stringify(saisie) });
}

/** Crée l'intervenant. 409 avec `{message, avertissements}` (JSON dans le
 *  message de l'erreur, cf. `messageErreur`) tant qu'un avertissement n'est
 *  pas confirmé — `avertissementsDeLErreur` les relit. */
export function creerIntervenant(saisie: SaisieIntervenant & { confirmer?: boolean }): Promise<IntervenantCree> {
  return request("/reference/enseignants", { method: "POST", body: JSON.stringify(saisie) });
}

/** Les avertissements d'un refus de `creerIntervenant`, ou null. */
export function avertissementsDeLErreur(e: unknown): AvertissementIntervenant[] | null {
  if (!(e instanceof Error)) return null;
  try {
    const d = JSON.parse(e.message) as { avertissements?: AvertissementIntervenant[] };
    return Array.isArray(d.avertissements) ? d.avertissements : null;
  } catch {
    return null;
  }
}

/** Supprime un intervenant créé dans l'appli, sans séance. */
export function supprimerIntervenant(code: string): Promise<ReferenceEnregistree> {
  return request(`/reference/enseignants/${encodeURIComponent(code)}`, { method: "DELETE" });
}

export function completerSalle(
  roomId: string,
  body: { capacite?: number; type?: string; code_celcat?: string },
): Promise<ReferenceEnregistree> {
  return request(`/reference/salles/${encodeURIComponent(roomId)}`, { method: "PUT", body: JSON.stringify(body) });
}

export function completerCours(
  code: string,
  body: { intitule?: string; code_celcat?: string },
): Promise<ReferenceEnregistree> {
  return request(`/reference/cours/${encodeURIComponent(code)}`, { method: "PUT", body: JSON.stringify(body) });
}

/** « Revenir à la valeur du fichier » : retire une saisie faite dans l'appli
 *  (29/09/2026). `champ` : `contact` (mail), `nom` (complet), `prenom`,
 *  `nom_famille`, `telephone` ou `type` d'un enseignant, `intitule` d'une
 *  matière. */
export function retablirValeurFichier(
  famille: "enseignants" | "cours",
  cle: string,
  champ: "contact" | "nom" | "intitule" | "prenom" | "nom_famille" | "telephone" | "type",
): Promise<ReferenceEnregistree> {
  return request(`/reference/${famille}/${encodeURIComponent(cle)}/${champ}`, { method: "DELETE" });
}

/** Un cours de SAE placé hors journée SAE sans exception déclarée — la liste
 *  `anomalies` de `GET /api/v1/sae` (le serveur est seul juge de la règle). */
export interface AnomalieSae {
  id: string;
  cours_code: string;
  cours_nom: string;
  type: string;
  parcours: string;
  groupes: string[];
  groupes_libelles: string[];
  enseignants: string[];
  semaine: number;
  jour: number;
  creneau: number;
}

export function fetchAnomaliesSae(): Promise<AnomalieSae[]> {
  return request<{ anomalies?: AnomalieSae[] }>("/api/v1/sae").then((r) =>
    Array.isArray(r?.anomalies) ? r.anomalies : [],
  );
}

// ── Onglet « Codes Celcat » de Référence (30/09/2026) ──
// « un onglet [...] où on pouvait renseigner les codes Celcat pour les cours
// et les salles aussi » — cf. `api/codes_celcat.py`. Toutes les entités du
// planning, leur code Celcat et son origine ; saisie réservée aux admins.

export type FamilleCodeCelcat = "cours" | "salles" | "enseignants" | "groupes";
/** `fichier` et `maquette` : code CONNU, verrouillé ; `appli` : saisi ici ;
 *  `voulu` : « sans code (voulu) », rien ne part ; `manquant` : à saisir ;
 *  `regle` : cours « envoi sans module » (celcat.yaml) — part sans matière,
 *  catégorie / remarque / département imposés par la règle (`note`). */
export type OrigineCodeCelcat = "fichier" | "maquette" | "appli" | "manquant" | "voulu" | "regle";

export interface LigneCodeCelcat {
  cle: string;
  libelle: string;
  semestre: string | null;
  parcours: string | null;
  type_salle: string | null;
  capacite: number | null;
  nb_seances: number;
  /** Le code qui part vers Celcat. */
  code: string | null;
  /** Le code connu hors saisie (fichier ou maquette). */
  code_connu: string | null;
  origine: OrigineCodeCelcat;
  /** « celcat.yaml », « maquette (corrigé M→C) » ; pour « voulu » : celcat.yaml ou appli. */
  origine_detail: string | null;
  /** Cours : le code tel que la maquette l'écrit. */
  code_maquette: string | null;
  motif_sans_code: string | null;
  saisi_le: string | null;
  /** Adresse du compte — administrateurs seulement. */
  saisi_par: string | null;
  valeur_avant: string | null;
  alerte: string | null;
  /** Saisie ancienne qui passe devant un code connu différent. */
  avertissement: string | null;
  note: string | null;
  /** Saisir ou modifier le code (manquant ou saisi dans l'appli). */
  modifiable: boolean;
  peut_revenir: boolean;
  peut_marquer_sans_code: boolean;
  peut_retirer_sans_code: boolean;
}

export interface FamilleCodesCelcat {
  famille: FamilleCodeCelcat;
  aide: string;
  exemple: string;
  modifiable: boolean;
  total: number;
  /** Manquants (le « sans code voulu » n'en fait pas partie). */
  sans_code: number;
  sans_code_bloquants: number;
  saisis: number;
  voulus: number;
  /** Cours envoyés sans module par une règle de celcat.yaml. */
  sans_module?: number;
  maquette: number;
  suggestions: string[];
  lignes: LigneCodeCelcat[];
}

export interface CodesCelcat {
  revision: number;
  admin: boolean;
  familles: Record<FamilleCodeCelcat, FamilleCodesCelcat>;
}

export interface CodeCelcatEnregistre {
  famille: FamilleCodeCelcat;
  cle: string;
  code: string | null;
  origine: OrigineCodeCelcat;
  message: string;
  revision: number;
}

export function fetchCodesCelcat(): Promise<CodesCelcat> {
  return request<CodesCelcat>("/reference/codes-celcat");
}

export function definirCodeCelcat(famille: FamilleCodeCelcat, cle: string, code: string): Promise<CodeCelcatEnregistre> {
  return request<CodeCelcatEnregistre>("/reference/codes-celcat", {
    method: "PUT",
    body: JSON.stringify({ famille, cle, code }),
  });
}

/** Retire la saisie faite dans l'appli : « Revenir à manquant » (ou au
 *  code connu, pour une saisie antérieure au verrou). */
export function effacerCodeCelcat(famille: FamilleCodeCelcat, cle: string): Promise<CodeCelcatEnregistre> {
  const q = new URLSearchParams({ famille, cle });
  return request<CodeCelcatEnregistre>(`/reference/codes-celcat?${q.toString()}`, { method: "DELETE" });
}

/** « Sans code (voulu) » : rien ne part vers Celcat, motif obligatoire. */
export function marquerSansCodeCelcat(famille: FamilleCodeCelcat, cle: string, motif: string): Promise<CodeCelcatEnregistre> {
  return request<CodeCelcatEnregistre>("/reference/codes-celcat/sans-code", {
    method: "PUT",
    body: JSON.stringify({ famille, cle, motif }),
  });
}

export function retirerSansCodeCelcat(famille: FamilleCodeCelcat, cle: string): Promise<CodeCelcatEnregistre> {
  const q = new URLSearchParams({ famille, cle });
  return request<CodeCelcatEnregistre>(`/reference/codes-celcat/sans-code?${q.toString()}`, { method: "DELETE" });
}

// ── Onglet « Enseignants & vacataires » de Référence (01/10/2026) ──
// `GET /reference/enseignants` : tous les enseignants, leur identité, leur
// mail, leur code Celcat (la ligne même de l'onglet « Codes Celcat ») et —
// rôles edit / admin seulement — leur téléphone.

export interface SurchargeIdentite {
  valeur: string | null;
  origine: string | null;
  modifie_le: string | null;
  modifie_par: string;
}

export interface LigneAnnuaireEnseignant {
  /** Le diminutif (« KBR ») : identifiant, non modifiable. */
  code: string;
  prenom: string;
  /** Nom de famille, en capitales. */
  nom: string;
  /** Le nom affiché partout dans l'appli. */
  nom_complet: string;
  /** `null` : à préciser. */
  type: "enseignant" | "vacataire" | null;
  email: string | null;
  /** E.164 ; `null` si absent OU masqué (lecture seule). */
  telephone: string | null;
  telephone_affiche: string | null;
  nb_seances: number;
  code_celcat: LigneCodeCelcat | null;
  cree_dans_appli: boolean;
  surcharges: Partial<Record<"email" | "nom" | "prenom" | "nom_famille" | "type" | "telephone", SurchargeIdentite>>;
}

export interface AnnuaireEnseignantsReponse {
  revision: number;
  peut_modifier: boolean;
  admin: boolean;
  telephone_visible: boolean;
  compteurs: {
    total: number;
    enseignants: number;
    vacataires: number;
    a_preciser: number;
    sans_mail: number;
    /** `null` quand le téléphone est masqué. */
    sans_telephone: number | null;
    sans_code_celcat: number;
  };
  lignes: LigneAnnuaireEnseignant[];
}

export function fetchAnnuaireEnseignants(): Promise<AnnuaireEnseignantsReponse> {
  return request<AnnuaireEnseignantsReponse>("/reference/enseignants");
}
