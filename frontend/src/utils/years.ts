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

function yearPrefixOf(parcours: string): string {
  const m = /^BUT(\d)/.exec(parcours || "");
  return m ? m[1] : "9";
}

export function isFcParcours(parcours: string): boolean {
  return (parcours || "").includes("FC");
}

/**
 * Portage de `compareParcoursForDisplay` (`export/templates/timetable.html`) :
 * année d'abord, puis FI avant FC de la MÊME année (pas l'ordre alphabétique
 * brut, qui mettrait "CREACOM-FC" avant "DEV-FI" puisque C < D — retour
 * utilisateur 11/08/2026 : "les groupe [FC] sont mis après les fi dans
 * l'ordre"), puis alphabétique.
 */
export function compareParcoursForDisplay(pa: string, pb: string): number {
  const ya = yearPrefixOf(pa);
  const yb = yearPrefixOf(pb);
  if (ya !== yb) return ya.localeCompare(yb);
  const fa = isFcParcours(pa);
  const fb = isFcParcours(pb);
  if (fa !== fb) return fa ? 1 : -1;
  return pa.localeCompare(pb, "fr");
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
