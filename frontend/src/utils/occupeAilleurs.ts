/**
 * Vue « Occupé ailleurs » (02/10/2026) : fonctions pures — dates et horaires
 * lisibles, tri, annuaire des ressources, filtres. Testées sans DOM
 * (`occupeAilleurs.test.ts`).
 */
import type { Route } from "../hooks/useHashRoute";
import type { ConflitOccupationExterne, OccupationExterne } from "../types/app";

export type TypeRessource = "salle" | "enseignant";

const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** « 2026-10-08 » -> « jeu. 8 oct. » ; une date illisible est rendue telle quelle. */
export function dateCourte(iso: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${JOURS[d.getDay()]} ${d.getDate()} ${MOIS[d.getMonth()]}`;
}

/** ("08:00", "10:00") -> « 08h00–10h00 » (tiret demi-cadratin). */
export function horaire(debut: string, fin: string): string {
  const h = (t: string) => t.replace(":", "h");
  return `${h(debut)}–${h(fin)}`;
}

function comparerChaines(a: string | undefined, b: string | undefined): number {
  if (a === b) return 0;
  return (a ?? "") < (b ?? "") ? -1 : 1;
}

function trierParDateHeure<T extends { date?: string; debut?: string }>(liste: T[]): T[] {
  // Sans date (serveur ancien) : après ceux qui en ont. `sort` est stable.
  return [...liste].sort((a, b) => {
    if (!a.date && b.date) return 1;
    if (a.date && !b.date) return -1;
    return comparerChaines(a.date, b.date) || comparerChaines(a.debut, b.debut);
  });
}

export function trierConflits(conflits: ConflitOccupationExterne[]): ConflitOccupationExterne[] {
  return trierParDateHeure(conflits);
}

export function trierOccupations(occupations: OccupationExterne[]): OccupationExterne[] {
  return trierParDateHeure(occupations);
}

/** Où mène « Ouvrir » : la même cible que « À traiter » (`utils/todo.ts`,
 *  nature `occupation-externe`) — la Vue Enseignant à la bonne semaine pour un
 *  enseignant, la Vue Promo au bon jour pour une salle. */
export function routeDuConflit(c: ConflitOccupationExterne): Partial<Route> {
  return c.ressource_type === "enseignant"
    ? { vue: "prof", prof: c.ressource, sem: c.semaine }
    : { vue: "promo", sem: c.semaine, jour: c.jour };
}

export type LibelleRessource = (type: TypeRessource, code: string) => string;

export interface EntreeAnnuaire {
  type: TypeRessource;
  code: string;
  libelle: string;
  nombre: number;
}

export function annuaireRessources(occupations: OccupationExterne[], libelle: LibelleRessource): EntreeAnnuaire[] {
  const parCle = new Map<string, EntreeAnnuaire>();
  for (const o of occupations) {
    const cle = `${o.t}:${o.code}`;
    const existante = parCle.get(cle);
    if (existante) existante.nombre += 1;
    else parCle.set(cle, { type: o.t, code: o.code, libelle: libelle(o.t, o.code), nombre: 1 });
  }
  return [...parCle.values()].sort(
    (a, b) =>
      b.nombre - a.nombre || a.libelle.localeCompare(b.libelle, "fr", { sensitivity: "base" }),
  );
}

export function compterDistincts(occupations: OccupationExterne[]): {
  salles: number;
  enseignants: number;
  creneauxSalles: number;
  creneauxEnseignants: number;
} {
  const salles = new Set<string>();
  const enseignants = new Set<string>();
  let creneauxSalles = 0;
  let creneauxEnseignants = 0;
  for (const o of occupations) {
    if (o.t === "salle") {
      salles.add(o.code);
      creneauxSalles += 1;
    } else {
      enseignants.add(o.code);
      creneauxEnseignants += 1;
    }
  }
  return { salles: salles.size, enseignants: enseignants.size, creneauxSalles, creneauxEnseignants };
}

export interface FiltreOccupations {
  type?: "" | TypeRessource;
  ressource?: { type: TypeRessource; code: string } | null;
  texte?: string;
  libelle?: LibelleRessource;
}

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

export function filtrerOccupations(occupations: OccupationExterne[], filtre: FiltreOccupations): OccupationExterne[] {
  const q = normaliser((filtre.texte ?? "").trim());
  const libelle: LibelleRessource = filtre.libelle ?? ((_type, code) => code);
  return occupations.filter((o) => {
    if (filtre.type && o.t !== filtre.type) return false;
    if (filtre.ressource && (o.t !== filtre.ressource.type || o.code !== filtre.ressource.code)) return false;
    if (!q) return true;
    return normaliser(`${libelle(o.t, o.code)} ${o.code} ${o.dep ?? ""} ${o.lib ?? ""}`).includes(q);
  });
}
