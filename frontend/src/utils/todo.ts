/**
 * Écran « À traiter » — portage de `buildTodoList` depuis
 * `export/templates/timetable.html`, puis refonte du 29/09/2026 : la liste
 * plate (309 lignes, 21 000 px de haut) devient une liste TRAITABLE —
 * regroupée par nature, filtrable (parcours, semaine, enseignant, gravité),
 * triée par urgence (semaine en cours d'abord, semaines passées à la fin).
 *
 * Chaque point porte donc, en plus de ce qu'on affiche, de quoi le filtrer
 * (`semaine`, `parcours`, `enseignants`) et le ranger (`nature`). Les
 * doublons salle/enseignant viennent d'un appel séparé (`api/doublons.py`,
 * balayage en direct) et sont convertis au même format par
 * `pointsDepuisDoublons`.
 */

import type { AnomalieSae, Doublon, DoublonHebdoRun } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { estNouveau } from "./controleDoublonsHebdo";
import { coursEnConflit, routeVersDoublon } from "./doublons";
import { DAY_LABELS, SLOT_TIMES } from "./slots";

export type NatureTodo =
  | "non-placee"
  | "sans-salle"
  | "doublon"
  | "regle"
  | "contrainte"
  | "sae-hors-journee"
  | "compromis-sae"
  | "trouee";

export interface TodoItem {
  sev: "bad" | "warn";
  title: string;
  sub: string;
  route: Partial<Route>;
  nature: NatureTodo;
  /** Clé stable (React, mémorisation). */
  cle: string;
  /** Indice SOLVEUR de la semaine concernée, `null` si le point n'est lié à
   * aucune semaine (séance non placée, règle globale). */
  semaine: number | null;
  /** Jour (0 = lundi) et créneau, quand ils sont connus — pour le tri et le
   * libellé « quand ». */
  jour: number | null;
  creneau: number | null;
  parcours: string[];
  /** Codes enseignants (jamais des noms) — cf. `codeEnseignant`. */
  enseignants: string[];
  /** Nombre d'occurrences regroupées sur cette ligne (compromis SAE : une
   * entrée par séance du même jour, identiques à l'écran). */
  n: number;
  /** Doublon apparu depuis le contrôle hebdomadaire précédent. */
  nouveau?: boolean;
  /** Type de doublon (salle / enseignant). */
  typeDoublon?: "salle" | "enseignant";
}

export interface NatureInfo {
  id: NatureTodo;
  titre: string;
  /** Libellé du sommaire (compteurs en tête d'écran). */
  court: string;
  aide: string;
  sev: "bad" | "warn";
  /** Où la ligne emmène — affiché en bout de ligne. */
  cible: string;
}

/** Ordre d'affichage = ordre d'importance. Une séance non placée est une
 * heure d'enseignement qui n'aura pas lieu : rien d'autre n'a ce poids. */
export const NATURES: NatureInfo[] = [
  {
    id: "non-placee",
    titre: "Séances non placées",
    court: "Non placées",
    aide: "Des heures prévues sans aucun créneau. On les rattrape depuis le panneau « À placer » de la Vue Promo.",
    sev: "bad",
    cible: "À placer",
  },
  {
    // Un CM sans grande salle libre reste volontairement sans salle plutôt
    // que d'atterrir dans une salle de 15 places (retour utilisateur
    // 29/08/2026 : « il faut laisser la salle vide, elle sera rentrée par la
    // suite ») — encore faut-il que « par la suite » soit visible ici.
    id: "sans-salle",
    titre: "Séances sans salle",
    court: "Sans salle",
    aide: "Placées, mais personne ne sait où les suivre. La salle se choisit en Vue Promo.",
    sev: "bad",
    cible: "Vue Promo",
  },
  {
    // Retour Kyllian Bresson 25/09/2026 (cf. `api/doublons.py`).
    id: "doublon",
    titre: "Doublons salle / enseignant",
    court: "Doublons",
    aide: "Une salle ou un enseignant pris deux fois sur le même créneau. H.201/H.203 et H.007/H.008 comptent comme une seule salle.",
    sev: "bad",
    cible: "Vue Promo",
  },
  {
    id: "regle",
    titre: "Règles globales en échec",
    court: "Règles en échec",
    aide: "Le détail de chaque règle est dans l'onglet Contraintes.",
    sev: "bad",
    cible: "Contraintes",
  },
  {
    id: "contrainte",
    titre: "Indisponibilités enseignant non respectées",
    court: "Indisponibilités",
    aide: "Une indisponibilité déclarée par l'enseignant tombe sur une de ses séances.",
    sev: "bad",
    cible: "Vue Enseignant",
  },
  {
    // 29/09/2026 : la liste `anomalies` de `GET /api/v1/sae` — le serveur
    // est seul juge de la règle (journées SAE, exceptions déclarées), cf.
    // `pointsDepuisSae` et son miroir `v1_vues.py::points_depuis_sae`.
    id: "sae-hors-journee",
    titre: "Cours de SAE hors journée SAE",
    court: "SAE hors journée",
    aide: "Un cours de SAE n'a lieu que sur une journée SAE de son parcours. Les SAE que la génération place elle-même (exception déclarée, ex. WSA501D) n'y figurent pas.",
    sev: "bad",
    cible: "Vue Promo",
  },
  {
    // Compromis MOU accepté (`--no-sae-supervisor-hard`) : une préférence
    // pas respectée, pas une règle cassée (retour utilisateur 11/08/2026,
    // cf. docs/DATA.md §59).
    id: "compromis-sae",
    titre: "Encadrement SAE le même jour",
    court: "Encadrement SAE",
    aide: "Compromis accepté : l'enseignant encadre une SAE le jour d'un de ses cours. À revoir si possible, rien d'interdit.",
    sev: "warn",
    cible: "Vue Enseignant",
  },
  {
    id: "trouee",
    titre: "Journées trouées",
    court: "Journées trouées",
    aide: "Au moins deux créneaux vides entre deux cours d'un même groupe dans la journée.",
    sev: "warn",
    cible: "Vue TD / TP",
  },
];

export const NATURE_PAR_ID: Record<NatureTodo, NatureInfo> = Object.fromEntries(
  NATURES.map((n) => [n.id, n]),
) as Record<NatureTodo, NatureInfo>;

function libelleSemaine(payload: Pick<AppPayload, "weekLabels">, w: number): string {
  return payload.weekLabels[w] ?? `Semaine ${w + 1}`;
}

function normaliserNom(nom: string): string {
  return nom
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Les séances non placées portent des NOMS d'enseignant (« MARINE
 * RIGUET »), le reste des codes (« MRI ») : on ramène tout aux codes pour
 * qu'un seul filtre « Enseignant » s'applique partout. */
function indexNoms(payload: Pick<AppPayload, "teacherLabels">): Map<string, string> {
  const m = new Map<string, string>();
  for (const [code, nom] of Object.entries(payload.teacherLabels)) m.set(normaliserNom(nom), code);
  return m;
}

/** Semaine solveur et jour d'une date ISO, depuis les lundis de
 * `payload.weekDates` — les violations « date » n'ont que la date. */
export function semaineDeDate(
  payload: Pick<AppPayload, "weekDates">,
  iso: string,
): { semaine: number; jour: number } | null {
  const cible = new Date(`${iso}T00:00:00`).getTime();
  if (Number.isNaN(cible)) return null;
  for (let i = 0; i < payload.weekDates.length; i += 1) {
    const lundi = payload.weekDates[i];
    if (!lundi) continue;
    const debut = new Date(`${lundi}T00:00:00`).getTime();
    const ecartJours = Math.round((cible - debut) / 86_400_000);
    if (ecartJours >= 0 && ecartJours < 7) return { semaine: i, jour: ecartJours };
  }
  return null;
}

function parcoursDesGroupes(payload: Pick<AppPayload, "groupParcours">, groupes: string[]): string[] {
  return [...new Set(groupes.map((g) => payload.groupParcours[g]).filter((p): p is string => Boolean(p)))];
}

export function buildTodoList(payload: AppPayload): TodoItem[] {
  const items: TodoItem[] = [];
  const noms = indexNoms(payload);

  // Séances non placées identiques (même cours, type, groupes, enseignants :
  // les 5 TD d'une même ressource) regroupées sur une ligne « ×5 ».
  const nonPlacees = new Map<string, TodoItem>();
  for (const s of payload.seancesNonPlacees ?? []) {
    const cleNp = `np|${s.code}|${s.type}|${s.groupes.join(",")}|${s.profs.join(",")}`;
    const dejaNp = nonPlacees.get(cleNp);
    if (dejaNp) {
      dejaNp.n += 1;
      continue;
    }
    const item: TodoItem = {
      sev: "bad",
      nature: "non-placee",
      cle: cleNp,
      title: `${s.code} — ${s.nom || "séance non placée"}`,
      sub: `${s.type} · ${s.groupes.join(", ")} · ${s.profs.join(", ")}`,
      // Filtrée sur son parcours à l'arrivée : le panneau « À placer »
      // s'ouvre sur la bonne promo.
      route: { vue: "promo", panel: "aplacer", ...(s.parcours ? { parcours: s.parcours } : {}) },
      semaine: null,
      jour: null,
      creneau: null,
      parcours: s.parcours ? [s.parcours] : [],
      enseignants: s.profs.map((p) => noms.get(normaliserNom(p)) ?? p),
      n: 1,
    };
    nonPlacees.set(cleNp, item);
    items.push(item);
  }

  for (const r of payload.rows) {
    if (r.r) continue;
    const groupes = r.g.map((g) => payload.groupLabels[g] ?? g).join(", ");
    items.push({
      sev: "bad",
      nature: "sans-salle",
      cle: `ss|${r.id}`,
      title: `${r.c} — ${r.n || r.t}`,
      sub: `${r.t} · ${groupes}`,
      route: { vue: "promo", sem: r.w, jour: r.d },
      semaine: r.w,
      jour: r.d,
      creneau: r.s,
      parcours: parcoursDesGroupes(payload, r.g),
      enseignants: r.te,
      n: 1,
    });
  }

  // Violations enseignant : une ligne par (enseignant, jour, cours). Les
  // compromis SAE arrivent une fois par séance du même jour, identiques à
  // l'écran : on les regroupe (« ×3 ») au lieu d'aligner trois lignes pareilles.
  const parCle = new Map<string, TodoItem>();
  for (const t of payload.teachers) {
    for (const v of t.violations) {
      const isSaeCompromise = v.reason === "sae_supervision";
      const quand = v.date ? semaineDeDate(payload, v.date) : null;
      const semaine = v.week ?? quand?.semaine ?? null;
      const jour = v.day ?? quand?.jour ?? null;
      const creneau = v.slot ?? null;
      const cle = `${isSaeCompromise ? "sae" : "ct"}|${t.code}|${v.date ?? `${semaine}-${jour}-${creneau}`}|${v.course_code}`;
      const deja = parCle.get(cle);
      if (deja) {
        deja.n += 1;
        continue;
      }
      const parcours = [
        ...new Set(payload.courses.filter((c) => c.code === v.course_code).map((c) => c.parcours).filter(Boolean)),
      ];
      const item: TodoItem = {
        sev: isSaeCompromise ? "warn" : "bad",
        nature: isSaeCompromise ? "compromis-sae" : "contrainte",
        cle,
        title: t.name,
        sub: v.course_code,
        route: { vue: "prof", prof: t.code, sem: semaine },
        semaine,
        jour,
        creneau,
        parcours,
        enseignants: [t.code],
        n: 1,
      };
      parCle.set(cle, item);
      items.push(item);
    }
  }

  const byGroupDay = new Map<string, number[]>();
  for (const r of payload.rows) {
    for (const g of r.g) {
      const key = `${g}|${r.w}|${r.d}`;
      if (!byGroupDay.has(key)) byGroupDay.set(key, []);
      byGroupDay.get(key)!.push(r.s);
    }
  }
  for (const [key, slots] of byGroupDay) {
    const [gid, wRaw, dRaw] = key.split("|");
    const w = Number(wRaw);
    const d = Number(dRaw);
    if (payload.groupKind[gid] === "promo") continue;
    const used = new Set(slots);
    const lo = Math.min(...slots);
    const hi = Math.max(...slots);
    let gap = 0;
    for (let s = lo; s <= hi; s++) if (!used.has(s)) gap++;
    if (gap >= 2) {
      const pc = payload.groupParcours[gid];
      items.push({
        sev: "warn",
        nature: "trouee",
        cle: `tr|${key}`,
        title: pc ? `${pc} · ${payload.groupLabels[gid] || gid}` : payload.groupLabels[gid] || gid,
        sub: `${gap} créneaux vides entre deux cours`,
        route: { vue: "groupe", groupe: gid, sem: w },
        semaine: w,
        jour: d,
        creneau: null,
        parcours: pc ? [pc] : [],
        enseignants: [],
        n: 1,
      });
    }
  }

  for (const c of payload.ruleChecks) {
    if (c.status === "fail") {
      items.push({
        sev: "bad",
        nature: "regle",
        cle: `rg|${c.id}`,
        title: c.label,
        sub: c.detail,
        route: { vue: "contraintes" },
        semaine: null,
        jour: null,
        creneau: null,
        parcours: [],
        enseignants: [],
        n: 1,
      });
    }
  }

  return items;
}

/** Doublons (`GET /controles/doublons`) au format commun. */
export function pointsDepuisDoublons(
  payload: Pick<AppPayload, "weekDates" | "groupParcours">,
  doublons: Doublon[],
  controle: DoublonHebdoRun | null,
): TodoItem[] {
  return doublons.map((d) => ({
    sev: "bad" as const,
    nature: "doublon" as const,
    cle: `db|${d.semaine}|${d.jour}|${d.creneau}|${d.type}|${d.ressource}`,
    title: d.ressource,
    sub: coursEnConflit(d),
    route: routeVersDoublon(d),
    semaine: d.semaine,
    jour: d.jour,
    creneau: d.creneau,
    parcours: parcoursDesGroupes(payload, d.seances.flatMap((s) => s.groupes)),
    enseignants: [...new Set(d.seances.flatMap((s) => s.enseignants))],
    n: 1,
    nouveau: estNouveau(controle, d),
    typeDoublon: d.type === "salle" ? ("salle" as const) : ("enseignant" as const),
  }));
}

/**
 * Cours de SAE placés hors journée SAE sans exception déclarée — la liste
 * `anomalies` de `GET /api/v1/sae`, jamais recalculée ici. Même forme que
 * le miroir serveur (`v1_vues.py::points_depuis_sae`, test de parité).
 * La ligne ouvre la Vue Promo au bon jour, sur le parcours de la séance.
 */
export function pointsDepuisSae(anomalies: AnomalieSae[]): TodoItem[] {
  return anomalies.map((a) => ({
    sev: "bad" as const,
    nature: "sae-hors-journee" as const,
    cle: `sae-hj|${a.id}`,
    title: `${a.cours_code} — ${a.cours_nom || a.cours_code}`,
    sub: `${a.type} · ${(a.groupes_libelles?.length ? a.groupes_libelles : a.groupes).join(", ")} · hors journée SAE`,
    route: { vue: "promo", sem: a.semaine, jour: a.jour, ...(a.parcours ? { parcours: a.parcours } : {}) },
    semaine: a.semaine,
    jour: a.jour,
    creneau: a.creneau,
    parcours: a.parcours ? [a.parcours] : [],
    enseignants: [...a.enseignants],
    n: 1,
  }));
}

/** Nombre d'occurrences d'une liste de points (une ligne « ×3 » compte 3). */
export function occurrences(items: TodoItem[]): number {
  return items.reduce((n, i) => n + i.n, 0);
}

/** Nombre total de points et nombre « à corriger » (badge de la nav). */
export function compterATraiter(payload: AppPayload | null, nbDoublons: number): { total: number; aCorriger: number } {
  const items = payload ? buildTodoList(payload) : [];
  return {
    total: occurrences(items) + nbDoublons,
    aCorriger: occurrences(items.filter((i) => i.sev === "bad")) + nbDoublons,
  };
}

// ── Filtres ──────────────────────────────────────────────────────────────

export type FiltreSemaine = "toutes" | "a-venir" | "courante" | `s${number}`;

export interface FiltresTodo {
  texte: string;
  parcours: string;
  semaine: FiltreSemaine;
  enseignant: string;
  gravite: "tout" | "bad" | "warn";
}

export const FILTRES_VIDES: FiltresTodo = { texte: "", parcours: "", semaine: "toutes", enseignant: "", gravite: "tout" };

export type StatutSemaine = "past" | "current" | "future";

/** Statut de chaque semaine solveur (passée / en cours / à venir), tel que
 * calculé côté serveur (`weekStatus`). Une semaine absente est « à venir » :
 * on ne cache jamais un point faute de savoir. */
export function statutsSemaines(payload: Pick<AppPayload, "weekStatus">): Map<number, StatutSemaine> {
  return new Map((payload.weekStatus ?? []).map((w) => [w.week, w.status]));
}

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

/**
 * Un point sans la dimension filtrée : il passe le filtre de semaine (une
 * séance non placée ou une règle globale ne dépend d'aucune semaine, et reste
 * toujours importante) mais pas ceux de parcours ni d'enseignant (« ce qui
 * concerne KBR » ne doit pas lister les journées trouées des étudiants).
 */
export function filtrerPoints(
  items: TodoItem[],
  f: FiltresTodo,
  statuts: Map<number, StatutSemaine>,
  libelles: Record<string, string> = {},
): TodoItem[] {
  const q = normaliser(f.texte.trim());
  const courante = [...statuts].find(([, s]) => s === "current")?.[0] ?? null;
  return items.filter((it) => {
    if (f.gravite !== "tout" && it.sev !== f.gravite) return false;
    if (f.parcours && !it.parcours.includes(f.parcours)) return false;
    if (f.enseignant && !it.enseignants.includes(f.enseignant)) return false;
    if (f.semaine !== "toutes" && it.semaine !== null) {
      if (f.semaine === "a-venir" && statuts.get(it.semaine) === "past") return false;
      if (f.semaine === "courante" && it.semaine !== courante) return false;
      if (f.semaine.startsWith("s") && it.semaine !== Number(f.semaine.slice(1))) return false;
    }
    if (q) {
      const hay = normaliser(
        [it.title, it.sub, ...it.parcours, ...it.enseignants, ...it.enseignants.map((c) => libelles[c] ?? "")].join(" "),
      );
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

/**
 * Tri par urgence : sans semaine d'abord (non placées, règles), puis la
 * semaine en cours, puis les semaines à venir dans l'ordre, puis les semaines
 * passées (la plus récente d'abord) — ce qui est derrière nous ne se corrige
 * plus guère. Dans une semaine : jour, puis créneau.
 */
export function trierParUrgence(items: TodoItem[], statuts: Map<number, StatutSemaine>): TodoItem[] {
  const rang = (it: TodoItem): [number, number] => {
    if (it.semaine === null) return [0, 0];
    const s = statuts.get(it.semaine) ?? "future";
    if (s === "current") return [1, 0];
    if (s === "future") return [2, it.semaine];
    return [3, -it.semaine];
  };
  return [...items].sort((a, b) => {
    const [ga, sa] = rang(a);
    const [gb, sb] = rang(b);
    return ga - gb || sa - sb || (a.jour ?? -1) - (b.jour ?? -1) || (a.creneau ?? -1) - (b.creneau ?? -1);
  });
}

/** « jeu. 1er oct. · 14h–15h30 » — « 1er » et non « 1 » : lu à voix haute,
 * « 1 oct. » sonne faux à côté de « 2 oct. » (cf. `utils/doublons.ts`). */
const FMT_JOUR_SEM = new Intl.DateTimeFormat("fr-FR", { weekday: "short" });
const FMT_MOIS = new Intl.DateTimeFormat("fr-FR", { month: "short" });

export function libelleQuand(payload: Pick<AppPayload, "weekDates">, it: TodoItem): string {
  if (it.semaine === null) return "";
  const lundi = payload.weekDates[it.semaine];
  let jour = "";
  if (it.jour !== null) {
    if (lundi) {
      const d = new Date(`${lundi}T00:00:00`);
      d.setDate(d.getDate() + it.jour);
      jour = `${FMT_JOUR_SEM.format(d)} ${d.getDate() === 1 ? "1er" : d.getDate()} ${FMT_MOIS.format(d)}`;
    } else {
      jour = DAY_LABELS[it.jour] ?? "";
    }
  }
  const creneau = it.creneau !== null ? SLOT_TIMES[it.creneau]?.label ?? "" : "";
  return [jour, creneau].filter(Boolean).join(" · ");
}

export { libelleSemaine };
