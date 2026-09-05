/**
 * Index de recherche globale (Ctrl+K) — portage de la recherche construite
 * dans `export/templates/timetable.html`. Un index plat (enseignants,
 * groupes, cours, salles), filtré par sous-chaîne sur libellé + code, accents
 * dépliés pour que « lefevre » trouve « Lefèvre ».
 */

import type { AppPayload } from "../types/app";
import type { Route } from "../hooks/useHashRoute";

export type SearchKind = "Enseignant" | "Groupe" | "Promo" | "Cours" | "Salle";

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

  // Un résultat par PROMO (parcours), en plus des groupes un par un —
  // retour utilisateur 05/09/2026 : chercher un groupe CM et cliquer
  // dessus n'affichait QUE les CM (GroupeView, cohorte = le groupe
  // lui-même pour un CM), sans pouvoir choisir les TD de la même promo.
  // Route vers la Vue Promo, filtrée sur ce parcours à l'arrivée — CM/TD/TP
  // choisissables dans la même page, c'est tout son principe.
  const parcoursVus = new Set<string>();
  for (const gid of groupIds) {
    const pc = payload.groupParcours[gid];
    if (!pc || parcoursVus.has(pc)) continue;
    parcoursVus.add(pc);
  }
  for (const pc of [...parcoursVus].sort((a, b) => a.localeCompare(b, "fr"))) {
    const nGroupes = groupIds.filter((gid) => payload.groupParcours[gid] === pc).length;
    index.push({
      kind: "Promo",
      label: pc,
      sub: `${nGroupes} groupe(s) · CM, TD, TP`,
      route: { vue: "promo", parcours: pc },
    });
  }

  const seenCourse = new Set<string>();
  for (const c of payload.courses) {
    if (seenCourse.has(c.code)) continue;
    seenCourse.add(c.code);
    const parcours = payload.courses
      .filter((x) => x.code === c.code)
      .map((x) => x.parcours)
      .filter(Boolean);
    index.push({
      kind: "Cours",
      label: c.code,
      sub: [c.name, ...parcours].filter(Boolean).join(" · "),
      route: { vue: "cours", cours: c.code },
    });
  }

  for (const room of payload.rooms) {
    index.push({
      kind: "Salle",
      label: room.label,
      sub: room.id === room.label ? `${room.type} · cap. ${room.capacity}` : room.id,
      route: { vue: "salle", salle: room.id },
    });
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
