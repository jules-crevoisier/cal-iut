/**
 * Index de recherche globale (Ctrl+K) — portage de la recherche construite
 * dans `export/templates/timetable.html`. Un index plat (enseignants,
 * promos, groupes, cours, salles), accents dépliés pour que « lefevre »
 * trouve « Lefèvre ».
 *
 * Refonte du 29/09/2026 : classement par pertinence (libellé exact, puis
 * début de libellé, puis début de mot, puis n'importe où), plusieurs mots
 * possibles (« kbr wr1 »), résultats groupés par type, surlignage de la
 * correspondance, écrans de l'application et derniers résultats ouverts.
 */

import type { AppPayload } from "../types/app";
import type { Route } from "../hooks/useHashRoute";

export type SearchKind = "Enseignant" | "Groupe" | "Promo" | "Cours" | "Salle" | "Écran";

export interface SearchHit {
  kind: SearchKind;
  label: string;
  sub: string;
  /** Route à appliquer pour "ouvrir" ce résultat. */
  route: Partial<Route>;
}

export function normalize(text: string): string {
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
    const pc = payload.groupParcours[gid];
    index.push({
      kind: "Groupe",
      label: payload.groupLabels[gid] || gid,
      // Le parcours d'abord : « TD AB » existe dans plusieurs promos.
      sub: pc ? `${pc} · ${gid}` : gid,
      route: { vue: "groupe", groupe: gid },
    });
  }

  // Un résultat par PROMO (parcours), en plus des groupes un par un —
  // retour utilisateur 05/09/2026 : chercher un groupe CM et cliquer
  // dessus n'affichait QUE les CM (GroupeView, cohorte = le groupe
  // lui-même pour un CM), sans pouvoir choisir les TD de la même promo.
  // Route vers la Vue Promo, filtrée sur ce parcours à l'arrivée.
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
      sub: `${nGroupes} groupe${nGroupes > 1 ? "s" : ""} · CM, TD, TP`,
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
      sub: room.id === room.label ? `${room.type} · ${room.capacity} places` : `${room.id} · ${room.capacity} places`,
      route: { vue: "salle", salle: room.id },
    });
  }

  return index;
}

/** Écrans de l'application — taper « tâches » ou « salles libres » y mène
 * sans passer par la navigation (« Salles libres » et « Vue Salle » n'y
 * figurent plus depuis le 25/09/2026 : la recherche est leur accès interne). */
export const ECRANS: SearchHit[] = [
  { kind: "Écran", label: "Accueil", sub: "Tableau de bord de la semaine", route: { vue: "accueil" } },
  { kind: "Écran", label: "Vue Semaine", sub: "Planning", route: { vue: "semaine" } },
  { kind: "Écran", label: "Vue Enseignant", sub: "Perspectives", route: { vue: "prof" } },
  { kind: "Écran", label: "Vue Promo", sub: "Perspectives", route: { vue: "promo" } },
  { kind: "Écran", label: "Vue TD / TP", sub: "Perspectives", route: { vue: "groupe" } },
  { kind: "Écran", label: "Salles libres", sub: "Occupation des salles", route: { vue: "salles-libres" } },
  { kind: "Écran", label: "Référence", sub: "Salles, cours, calendrier, liens", route: { vue: "reference" } },
  { kind: "Écran", label: "Contraintes", sub: "Règles et verdicts", route: { vue: "contraintes" } },
  { kind: "Écran", label: "Occupé ailleurs", sub: "Salles et enseignants pris hors MMI", route: { vue: "occupations" } },
  { kind: "Écran", label: "À traiter", sub: "Non placées, doublons, violations", route: { vue: "apf" } },
  { kind: "Écran", label: "Tâches", sub: "Suivi de l'équipe", route: { vue: "taches" } },
  { kind: "Écran", label: "Séances à placer", sub: "Vue Promo", route: { vue: "promo", panel: "aplacer" } },
];

function tokens(query: string): string[] {
  return normalize(query).trim().split(/\s+/).filter(Boolean);
}

/**
 * Pertinence (plus petit = meilleur), `null` si un des mots manque. Le
 * premier mot décide du rang ; les suivants doivent seulement être présents.
 */
export function scoreHit(item: SearchHit, query: string): number | null {
  const mots = tokens(query);
  if (mots.length === 0) return 0;
  const label = normalize(item.label);
  const sub = normalize(item.sub);
  const hay = `${label} ${sub}`;
  if (!mots.every((m) => hay.includes(m))) return null;
  const q = mots.join(" ");
  if (label === q) return 0;
  if (sub === q || sub.split(/[\s·]+/).includes(q)) return 1;
  if (label.startsWith(q)) return 2;
  const m = mots[0];
  if (label.split(/[\s./()-]+/).some((w) => w.startsWith(m))) return 3;
  if (label.includes(m)) return 4;
  if (sub.split(/[\s·./()-]+/).some((w) => w.startsWith(m))) return 5;
  return 6;
}

export function runSearch(index: SearchHit[], query: string, limit = 12): SearchHit[] {
  if (!query.trim()) return index.slice(0, limit);
  return index
    .map((item, ordre) => ({ item, ordre, score: scoreHit(item, query) }))
    .filter((x): x is { item: SearchHit; ordre: number; score: number } => x.score !== null)
    .sort((a, b) => a.score - b.score || a.ordre - b.ordre)
    .slice(0, limit)
    .map((h) => h.item);
}

export interface GroupeResultats {
  kind: SearchKind | "Récents";
  titre: string;
  hits: SearchHit[];
  /** Nombre total de correspondances (le groupe peut être tronqué). */
  total: number;
}

const TITRES: Record<SearchKind, string> = {
  Enseignant: "Enseignants",
  Promo: "Promos",
  Groupe: "Groupes TD / TP",
  Cours: "Cours",
  Salle: "Salles",
  Écran: "Écrans",
};

/**
 * Résultats groupés par type. Les groupes sont rangés par leur meilleur
 * résultat : taper « KBR » met les enseignants en tête, « H.2 » les salles.
 */
export function rechercheGroupee(index: SearchHit[], query: string, parGroupe = 5): GroupeResultats[] {
  const scores = index
    .map((item, ordre) => ({ item, ordre, score: scoreHit(item, query) }))
    .filter((x): x is { item: SearchHit; ordre: number; score: number } => x.score !== null)
    .sort((a, b) => a.score - b.score || a.ordre - b.ordre);
  const groupes = new Map<SearchKind, { meilleur: number; hits: SearchHit[] }>();
  for (const s of scores) {
    const g = groupes.get(s.item.kind) ?? { meilleur: s.score, hits: [] };
    g.hits.push(s.item);
    groupes.set(s.item.kind, g);
  }
  return [...groupes.entries()]
    .sort((a, b) => a[1].meilleur - b[1].meilleur)
    .map(([kind, g]) => ({ kind, titre: TITRES[kind], hits: g.hits.slice(0, parGroupe), total: g.hits.length }));
}

export interface Segment {
  texte: string;
  surligne: boolean;
}

/**
 * Découpe `texte` en segments surlignés là où un mot de la requête
 * correspond, sans tenir compte des accents ni de la casse (« lefevre »
 * surligne « Lefèvre »). Les positions sont calculées caractère par
 * caractère sur le texte d'origine, jamais sur sa forme normalisée (qui n'a
 * pas la même longueur dès qu'il y a un accent).
 */
export function surligner(texte: string, query: string): Segment[] {
  const mots = tokens(query);
  if (mots.length === 0 || !texte) return [{ texte, surligne: false }];
  // Forme normalisée + correspondance vers l'index d'origine.
  let norm = "";
  const origine: number[] = [];
  for (let i = 0; i < texte.length; i += 1) {
    const n = normalize(texte[i]);
    for (let k = 0; k < n.length; k += 1) {
      norm += n[k];
      origine.push(i);
    }
  }
  const marque = new Array<boolean>(texte.length).fill(false);
  for (const m of mots) {
    let depuis = 0;
    for (;;) {
      const pos = norm.indexOf(m, depuis);
      if (pos < 0) break;
      for (let k = pos; k < pos + m.length; k += 1) marque[origine[k]] = true;
      depuis = pos + m.length;
    }
  }
  const segments: Segment[] = [];
  for (let i = 0; i < texte.length; i += 1) {
    const dernier = segments[segments.length - 1];
    if (dernier && dernier.surligne === marque[i]) dernier.texte += texte[i];
    else segments.push({ texte: texte[i], surligne: marque[i] });
  }
  return segments;
}
