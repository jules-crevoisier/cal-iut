/**
 * Index de recherche globale (Ctrl+K) — portage de la recherche construite
 * dans `export/templates/timetable.html`. Un index plat (enseignants,
 * groupes, cours, salles), filtré par sous-chaîne sur libellé + code, accents
 * dépliés pour que « lefevre » trouve « Lefèvre ».
 */

import type { AppPayload } from "../types/app";
import type { Route } from "../hooks/useHashRoute";

export type SearchKind = "Enseignant" | "Groupe" | "Cours" | "Salle";

export interface SearchHit {
  kind: SearchKind;
  label: string;
  sub: string;
  /** Route à appliquer pour "ouvrir" ce résultat. */
  route: Partial<Route>;
}

function normalize(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

export function buildSearchIndex(payload: AppPayload): SearchHit[] {
  const index: SearchHit[] = [];

  const teacherCodes = Object.keys(payload.teacherLabels).sort((a, b) =>
    (payload.teacherLabels[a] || a).localeCompare(payload.teacherLabels[b] || b, "fr"),
  );
  for (const code of teacherCodes) {
    index.push({
      kind: "Enseignant",
      label: payload.teacherLabels[code] || code,
      sub: code,
      route: { vue: "prof", prof: code },
    });
  }

  const groupIds = Object.keys(payload.groupLabels).sort((a, b) =>
    (payload.groupLabels[a] || a).localeCompare(payload.groupLabels[b] || b, "fr"),
  );
  for (const gid of groupIds) {
    index.push({
      kind: "Groupe",
      label: payload.groupLabels[gid] || gid,
      sub: gid,
      route: { vue: "groupe", groupe: gid },
    });
  }

  const seenCourse = new Set<string>();
  for (const r of payload.rows) {
    if (seenCourse.has(r.c)) continue;
    seenCourse.add(r.c);
    index.push({
      kind: "Cours",
      label: r.c,
      sub: r.n || "",
      // Un cours n'a pas de vue dédiée : on ouvre la Vue Semaine sur le
      // premier groupe/semaine où il apparaît.
      route: { vue: "semaine", groupe: r.g[0] || "", sem: r.w },
    });
  }

  const seenRoom = new Set<string>();
  for (const r of payload.rows) {
    if (!r.r || seenRoom.has(r.r)) continue;
    seenRoom.add(r.r);
    index.push({ kind: "Salle", label: r.r, sub: "voir son occupation", route: { vue: "reference" } });
  }

  return index;
}

export function runSearch(index: SearchHit[], query: string, limit = 12): SearchHit[] {
  const q = normalize(query).trim();
  if (!q) return index.slice(0, limit);
  return index
    .map((item) => {
      const hay = normalize(item.label + " " + item.sub);
      const pos = hay.indexOf(q);
      return pos < 0 ? null : { item, score: pos };
    })
    .filter((x): x is { item: SearchHit; score: number } => x !== null)
    .sort((a, b) => a.score - b.score)
    .slice(0, limit)
    .map((h) => h.item);
}
