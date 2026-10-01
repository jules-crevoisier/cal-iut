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
  /** Séance ajoutée depuis l'interface, distincte de la maquette — seule à
   * proposer modifier/supprimer (retour utilisateur 31/08/2026). */
  custom: boolean;
  /** Évènement à horaire libre (retour Jules 23/09/2026, Kyllian Bresson :
   * présentation PAC 13h15-14h) — libellé français de l'horaire RÉEL, ex.
   * "13h15–14h". Absent tant qu'aucun horaire libre n'a été saisi. */
  hor?: string;
  /** `true` quand `hor` tombe dans la pause méridienne (12h30-14h) : la
   * séance est STOCKÉE sur le créneau 3 (position de stockage uniquement),
   * Vue Promo doit alors l'exclure de la cellule normale du créneau 3 et la
   * rendre dans la ligne "pause" à la place. Absent/`false` sinon. */
  midi?: boolean;
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
  // Proposée au placement automatique (solveur + résolution API) — retour
  // utilisateur 22/09/2026 : « supprimer la BU du placement automatique des
  // salles car elle est utilisée pour un seul module ». `false` reste
  // choisissable à la main, juste jamais retenue seule par la génération
  // automatique — cf. `ReferenceView.tsx` (marqueur « hors auto »).
  placementAuto: boolean;
  // Salles individuelles recouvertes par cette salle si elle est une fusion
  // (ex. `h007_h008` → `["h007", "h008"]`), vide sinon — cf.
  // `html_view.py::_room_catalog`. Ajouté le 22/09/2026 (todo département,
  // Kyllian Bresson : « Planning des salles disponibles ») pour que la Vue
  // « Salles libres » sache qu'occuper la salle fusionnée occupe aussi
  // chaque moitié, et inversement.
  combines: string[];
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
  /** Salles réservées par des tiers (`salles_reservees.yaml`), telles que
   *  déclarées — optionnel : absent des anciens payloads et des fixtures. */
  roomReservations?: { salle: string; date: string; slots: number[]; motif: string }[];
  /** Occupations HORS MMI relevées dans Celcat par le sidecar (01/10/2026,
   *  `api/occupations_externes.py::pour_payload`). Absent d'un serveur plus
   *  ancien et d'un lien public. */
  occupationsExternes?: OccupationsExternesPayload;
  /** Valeurs modifiées dans l'appli (29/09/2026, `api/reference.py::
   *  surcharges_pour_payload`), avec la valeur d'origine. Vide sur un lien
   *  public (adresses). Absent d'un serveur plus ancien. */
  surchargesReference?: SurchargesReference;
  /** Intervenants créés dans l'appli (« Nouvel intervenant », 30/09/2026,
   *  `api/reference.py::intervenants_pour_payload`) : par qui, quand, et
   *  combien de séances (supprimable à 0). Vide sur un lien public. */
  intervenantsAppli?: Record<string, IntervenantAppli>;
  /** Prénom, nom et type de chaque enseignant (onglet « Enseignants &
   *  vacataires », 01/10/2026, `ingestion/identite_enseignants.py`). Vide
   *  sur un lien public ; absent d'un serveur plus ancien : se déduit alors
   *  de `teacherLabels` (`utils/identiteEnseignant.ts`). Jamais de
   *  téléphone ici : il n'est servi qu'aux rôles edit / admin. */
  teacherIdentites?: Record<string, IdentiteEnseignant>;
  courses: CourseCatalogEntry[];
}

export type TypeEnseignant = "enseignant" | "vacataire";

export interface IdentiteEnseignant {
  prenom: string;
  /** Nom de famille, en capitales. */
  nom: string;
  /** `null` : à préciser. */
  type: TypeEnseignant | null;
}

/** Un intervenant créé dans l'appli plutôt que dans la configuration. */
export interface IntervenantAppli {
  nom: string;
  cree_le: string;
  /** Adresse du compte qui l'a créé (affichée aux administrateurs). */
  cree_par: string;
  nb_seances: number;
}

/** Une valeur saisie dans l'appli par-dessus la configuration. */
export interface SurchargeReference {
  valeur: string;
  /** Ce que dit le fichier (ou la maquette) ; `null` s'il ne dit rien. */
  origine: string | null;
  modifie_le: string | null;
  modifie_par: string;
}

export interface SurchargesReference {
  enseignants: Record<
    string,
    {
      email?: SurchargeReference;
      nom?: SurchargeReference;
      prenom?: SurchargeReference;
      nom_famille?: SurchargeReference;
      type?: SurchargeReference;
      /** Jamais dans le payload : seulement dans `GET /reference/enseignants`. */
      telephone?: SurchargeReference;
    }
  >;
  cours: Record<string, { intitule?: SurchargeReference }>;
}

/** Une occupation hors MMI sur NOS créneaux (clés courtes, comme `rows`). */
export interface OccupationExterne {
  /** « enseignant » : programmé ailleurs ; « salle » : réservée dans Celcat. */
  t: "enseignant" | "salle";
  /** Trigramme (« AFR ») ou id de salle (« h018 »). */
  code: string;
  /** Semaine SOLVEUR, jour (0 = lundi), créneaux chevauchés (0-5). */
  w: number;
  d: number;
  s: number[];
  date: string;
  /** Heures RÉELLES dans Celcat (« 10:00 », « 12:30 »). */
  debut: string;
  fin: string;
  /** Département abrégé (« TC ») ; vide = administration / hors département. */
  dep: string;
  lib: string;
  cat: string;
}

/** Séance MMI déjà placée sur une occupation externe (« À traiter »). */
export interface ConflitOccupationExterne {
  seance_id: string;
  course_code: string;
  nom: string;
  type: string;
  semaine: number;
  jour: number;
  creneau: number;
  groupes: string[];
  enseignants: string[];
  ressource_type: "enseignant" | "salle";
  ressource: string;
  message: string;
}

export interface OccupationsExternesPayload {
  releveLe: string | null;
  ageSecondes: number | null;
  absent: boolean;
  perime: boolean;
  fraicheurHeures: number;
  strict: boolean;
  erreur: string | null;
  occupations: OccupationExterne[];
  conflits: ConflitOccupationExterne[];
}
