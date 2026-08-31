export interface Placement {
  session_id: string;
  week: number;
  day: number;
  slot: number;
  course_code: string;
  course_name: string;
  session_type: string;
  group_ids: string[];
  teacher_codes: string[];
  room_id: string | null;
  room_label: string | null;
  is_eval: boolean;
  locked: boolean;
  duration_slots: number;
}

export interface Quality {
  total_gaps: number;
  isolated_days: number;
  eval_days_with_multiple: number;
  unbalanced_groups: string[];
  gaps_by_group: Record<string, number>;
}

export interface TimetableResponse {
  status: string;
  objective_value: number | null;
  gap_penalty: number;
  placements: Placement[];
  quality: Quality | null;
  run_id: number | null;
}

export interface DiffEntry {
  session_id: string;
  course_code: string;
  solver_week: number;
  solver_day: number;
  solver_slot: number;
  current_week: number;
  current_day: number;
  current_slot: number;
  changed: boolean;
  locked: boolean;
}

export interface DiffResponse {
  run_id: number | null;
  total: number;
  changed_count: number;
  entries: DiffEntry[];
}

export interface FeedbackAnalysis {
  patterns: string[];
  suggestions: Record<string, number>;
  top_courses: { course: string; moves: number }[];
  top_teachers: { teacher: string; moves: number }[];
  total_corrections: number;
}

export interface GroupMeta {
  id: string;
  label: string;
  parcours: string;
  kind: string;
  related_ids: string[];
  annee?: string | null;
}

export interface RoomMeta {
  id: string;
  label: string;
  capacity: number;
  room_type: string;
}

export interface YearMeta {
  id: number;
  label: string;
  semestres: string[];
  parcours: string[];
}

export interface MetaResponse {
  groups: GroupMeta[];
  rooms: RoomMeta[];
  parcours: string[];
  semestres: string[];
  years: YearMeta[];
}

export interface ValidationResponse {
  valid: boolean;
  hard_conflicts: string[];
  soft_warnings: string[];
  /** Sous-ensemble de `hard_conflicts` que « Forcer » ne peut PAS lever
   *  (indisponibilite enseignant declaree, verrou PAC/SAE/evenement). Vide =
   *  tout le reste est negociable. Absent des serveurs anterieurs au
   *  29/08/2026, d'ou l'optionalite. */
  blocking_conflicts?: string[];
}

/** Réglage des notifications par mail (`GET/PUT /notifications`). */
export interface NotificationConfig {
  destinataires: string[];
  evenements: Record<string, boolean>;
  delai_minutes: number;
  /** Libellés fournis par le serveur : l'interface ne les redéclare pas, ils
   *  divergeraient le jour où l'un change. */
  libelles: Record<string, string>;
  en_attente: number;
  /** Faux = RESEND_API_KEY et/ou CAL_IUT_PUBLIC_URL absente(s) : les
   *  réglages sont gardés mais rien ne part. Le détail de LAQUELLE manque
   *  est dans les deux champs suivants (retour utilisateur 31/08/2026 :
   *  un message ne citant que la clé a fait chercher au mauvais endroit
   *  quand c'était l'URL publique l'absente). */
  mail_configure: boolean;
  mail_a_la_clef_api: boolean;
  mail_a_url_publique: boolean;
}

export type ViewMode = "group" | "teacher" | "room";

export interface CalendarEventExtended {
  sessionId: string;
  courseCode: string;
  sessionType: string;
  roomLabel: string | null;
  teacherCodes: string[];
  isEval: boolean;
  locked: boolean;
  week: number;
  day: number;
  slot: number;
}
