/** Année scolaire = 2 semestres (1→S1/S2, 2→S3/S4, 3→S5/S6). */

import type { YearMeta } from "../types";

export const DEFAULT_YEARS: YearMeta[] = [
  { id: 1, label: "1re année (S1–S2)", semestres: ["S1", "S2"], parcours: ["BUT1"] },
  { id: 2, label: "2e année (S3–S4)", semestres: ["S3", "S4"], parcours: [] },
  { id: 3, label: "3e année (S5–S6)", semestres: ["S5", "S6"], parcours: [] },
];

export function yearFromSemestre(semestre: string): number {
  if (semestre === "S1" || semestre === "S2") return 1;
  if (semestre === "S3" || semestre === "S4") return 2;
  return 3;
}

export function shortGroupLabel(groupIds: string[], labelsById: Record<string, string>): string {
  if (!groupIds.length) return "";
  const labels = groupIds.map((id) => labelsById[id] ?? id);
  return labels
    .map((label) =>
      label
        .replace(/^TD\s+/i, "")
        .replace(/^TP\s+/i, "")
        .replace(/^Promo\s+/i, "")
        .trim(),
    )
    .join("/");
}
