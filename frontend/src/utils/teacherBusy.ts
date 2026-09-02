/**
 * Cours déjà posés du même enseignant, autre parcours / autre colonne.
 * Vue Promo ne les peint pas dans la colonne courante : au déplacement il
 * faut les montrer, sans bloquer (Forcer reste).
 */
import type { AppRow } from "../types/app";

export interface TeacherBusyHit {
  course: string;
  teachers: string[];
}

export function teacherBusyByDaySlot(
  rows: Pick<AppRow, "id" | "w" | "d" | "s" | "c" | "te" | "dur">[],
  teacherCodes: string[],
  week: number,
  excludeSessionId?: string,
): Map<string, TeacherBusyHit> {
  const codes = new Set(teacherCodes.filter(Boolean));
  const hits = new Map<string, TeacherBusyHit>();
  if (codes.size === 0) {
    return hits;
  }
  for (const row of rows) {
    if (row.id === excludeSessionId) continue;
    if (row.w !== week) continue;
    const teachers = row.te.filter((code) => codes.has(code));
    if (teachers.length === 0) continue;
    const duration = Math.max(1, row.dur || 1);
    for (let offset = 0; offset < duration; offset += 1) {
      const key = `${row.d}-${row.s + offset}`;
      if (!hits.has(key)) {
        hits.set(key, { course: row.c, teachers });
      }
    }
  }
  return hits;
}

export function teacherBusyLabel(hit: TeacherBusyHit): string {
  return `${hit.teachers.join(", ")} déjà ${hit.course}`;
}

export function teacherBusyOnCell(
  map: Map<string, TeacherBusyHit>,
  day: number,
  slot: number,
  entries: { c: string; te: string[] }[],
): TeacherBusyHit | null {
  const hit = map.get(`${day}-${slot}`);
  if (!hit) return null;
  const dejaVisible = entries.some(
    (row) => row.c === hit.course && row.te.some((code) => hit.teachers.includes(code)),
  );
  if (dejaVisible) return null;
  return hit;
}
