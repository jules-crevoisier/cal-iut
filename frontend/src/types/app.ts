/**
 * Formes JSON exposées par `GET /app-state` — reflet exact de
 * `cal_iut.export.html_view.build_payload`, la même fonction qui alimente
 * la page HTML/JS historique (`/legacy`). Les vérifications (contraintes,
 * SAE, violations enseignant) sont calculées côté serveur ; le frontend ne
 * fait qu'afficher et filtrer ce que le backend a déjà validé.
 *
 * Noms de clés compacts (`w`, `d`, `s`...) conservés tels quels côté JSON
 * pour rester identiques au payload embarqué dans `/legacy` — un futur
 * lecteur qui compare les deux n'a pas à faire de traduction mentale.
 */

export interface AppRow {
  id: string;
  w: number; // semaine (index solveur)
  d: number; // jour, 0 = lundi
  s: number; // créneau, 0 = 8h-9h30
  c: string; // code cours
  n: string; // nom cours
  t: string; // type séance (CM/TD/TP/PTUT)
  g: string[]; // group_ids
  te: string[]; // teacher_codes
  r: string; // salle (libellé), "" si non affectée
  ev: boolean; // is_eval
  dur: number; // duration_slots
  locked: boolean;
}

export interface WeekRow {
  monday: string; // ISO
  label: string;
  blocked: boolean;
  weekIndex: number | null;
}

export interface WeekStatusRow {
  week: number;
  status: "past" | "current" | "future";
}

export interface SaeRow {
  w: number;
  d: number;
  p: string; // parcours
  codes: string[];
}

export interface HolidayRow {
  w: number;
  d: number;
  kind: "ferie" | "vacances";
  label: string;
}

export interface EventRow {
  w: number;
  d: number;
  labels: string[];
}

export interface EventSlotRow {
  w: number;
  d: number;
  s: number;
  label: string;
  parcours: string[];
  room: string | null;
}

export interface TeacherViolation {
  week?: number;
  day?: number;
  slot?: number;
  date?: string;
  course_code: string;
  /**
   * "sae_supervision" = compromis MOU accepté (l'enseignant encadre une SAE
   * ce jour-là, `--no-sae-supervisor-hard` — préférence, pas interdit) ;
   * "declared" = vraie indisponibilité déclarée non respectée. Absent pour
   * les violations de créneau récurrent (`week`/`day`/`slot`, toujours
   * "declared" de fait). Distingué le 11/08/2026 : sans ça, 115/152 entrées
   * de "À traiter" étaient des compromis ATTENDUS affichés comme des bugs
   * (cf. docs/DATA.md §59).
   */
  reason?: "sae_supervision" | "declared";
}

export interface TeacherInfo {
  code: string;
  name: string;
  rawIndisponibilites: string;
  rawDisponibilites: string;
  rawContraintes: string;
  forbiddenSlots: [number, number][];
  forbiddenDates: string[];
  nPlaced: number;
  violations: TeacherViolation[];
  hasConstraint: boolean;
}

export interface RuleCheck {
  id: string;
  label: string;
  status: "pass" | "fail";
  detail: string;
}

export interface InstitutionalEvent {
  label: string;
  start: string;
  end: string;
  kind: "vacances" | "ferie" | "rentree" | "special";
}

export interface RoomCatalogEntry {
  id: string;
  label: string;
  capacity: number;
  type: string;
  equipment: string[];
  nSessions: number;
}

export interface CourseCatalogEntry {
  code: string;
  name: string;
  semestre: string;
  parcours: string;
  nCM: number;
  nTD: number;
  nTP: number;
  nEval: number;
  progressionDefined: boolean;
  teachers: string[];
  ordonnancement: { position: string; target: string }[];
  nPlaced: number;
}

export interface AppQuality {
  total_gaps: number;
  isolated_days: number;
  eval_days_with_multiple: number;
  unbalanced_groups: string[];
  gaps_by_group: Record<string, number>;
}

/**
 * Reflète `api/schemas.py::ExceptionResponse` — `ctx.exceptions` dans
 * `/app-state` est littéralement `[ExceptionResponse.model_dump() for ...]`
 * (`api/main.py::_build_app_context`), pas une entrée par `session_id` (champ
 * qui n'existe pas côté backend — corrigé le 11/08/2026, cf. docs/DATA.md).
 */
export interface AppException {
  id: number;
  kind: "teacher_absence" | "room_unavailable";
  exception_date: string; // ISO "YYYY-MM-DD"
  teacher_code: string | null;
  room_id: string | null;
  slots: number[] | null;
  reason: string | null;
  active: boolean;
}

/** Retour complet de `GET /app-state`. */
/**
 * Une séance que le solveur n'a pas su placer. Sans cette liste, elle
 * disparaissait de toutes les vues et de tous les compteurs — le planning avait
 * l'air complet alors qu'il manquait des heures (cf. docs/DATA.md §66).
 */
export interface SeanceNonPlacee {
  id: string;
  code: string;
  nom: string;
  type: string;
  parcours: string;
  groupes: string[];
  profs: string[];
}

export interface AppPayload {
  status: string | null;
  seancesNonPlacees?: SeanceNonPlacee[];
  objective: number | null;
  quality: AppQuality | null;

  groupLabels: Record<string, string>;
  groupKind: Record<string, string>;
  groupCohort: Record<string, string[]>;
  groupTpPair: Record<string, [string, string]>;
  groupIsFc: Record<string, boolean>;
  groupParcours: Record<string, string>;

  weekLabels: string[];
  weekDates: string[]; // ISO, "" si inconnu — lundi de chaque semaine-solveur
  weekRows: WeekRow[];
  weekStatus: WeekStatusRow[];
  defaultGroup: string | null;

  rows: AppRow[];
  saeRows: SaeRow[];
  holidayRows: HolidayRow[];
  eventRows: EventRow[];
  eventSlotRows: EventSlotRow[];
  exceptions: AppException[];

  teachers: TeacherInfo[];
  teacherLabels: Record<string, string>;
  teacherEmails: Record<string, string>;
  /** Paramètre `t` du lien perso — public depuis le 28/08/2026 (cf.
   * api/auth.py), associe chaque code à lui-même, plus un jeton signé.
   * Intégré par `buildLink` pour éviter le mot de passe. */
  teacherTokens: Record<string, string>;
  /** Même chose pour le lien perso d'un GROUPE d'étudiants. */
  groupTokens: Record<string, string>;

  ruleChecks: RuleCheck[];
  institutionalCalendar: InstitutionalEvent[];

  rooms: RoomCatalogEntry[];
  courses: CourseCatalogEntry[];
}
