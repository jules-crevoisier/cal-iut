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
