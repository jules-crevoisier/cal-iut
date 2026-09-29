/**
 * Annuaires des écrans de consultation (refonte v2 du 29/09/2026, cf.
 * docs/DESIGN.md « Gabarit de page ») : sans entité choisie, la Vue
 * Enseignant, la Vue TD / TP, la Vue Cours et la Vue Salle montrent la liste
 * de leurs entités avec les chiffres de la semaine partagée — qui enseigne
 * beaucoup cette semaine, quelle salle est saturée — au lieu d'une boîte vide
 * « Choisissez… ».
 *
 * Fonctions pures, testées à part (`annuaires.test.ts`) : une seule passe
 * sur `payload.rows` par annuaire.
 */

import type { AppPayload, AppRow } from "../types/app";
import { compareParcoursForDisplay } from "./years";
import { heuresDe, HEURES_PAR_CRENEAU } from "./planning";
import { occupationSalles } from "./sallesLibres";
import { SLOT_TIMES } from "./slots";

/** Créneaux d'une semaine : 5 jours × 6 créneaux. */
export const CRENEAUX_SEMAINE = 5 * SLOT_TIMES.length;

/** Heures pendant lesquelles un ensemble de séances occupe l'emploi du temps,
 *  chaque créneau compté UNE fois : deux TP jumelés en parallèle (TP A et
 *  TP B du même TD) durent 1 h 30, pas 3 h. C'est la mesure qui a du sens
 *  pour un groupe ; pour un enseignant, on additionne (`heuresDe`). */
export function heuresOccupees(rows: Pick<AppRow, "w" | "d" | "s" | "dur">[]): number {
  const vus = new Set<string>();
  for (const r of rows) {
    const n = Math.max(1, r.dur || 1);
    for (let k = 0; k < n; k += 1) vus.add(`${r.w}-${r.d}-${r.s + k}`);
  }
  return vus.size * HEURES_PAR_CRENEAU;
}

// ── Enseignants ────────────────────────────────────────────────────────

export type EtatContrainte = "aucune" | "respectee" | "sae" | "ecarts";

export interface LigneEnseignant {
  code: string;
  nom: string;
  email: string;
  heuresSemaine: number;
  heuresSemestre: number;
  nSeances: number;
  nMatieres: number;
  nNonPlacees: number;
  contrainte: EtatContrainte;
  /** Indisponibilités déclarées non respectées (hors compromis SAE). */
  nEcarts: number;
}

export function annuaireEnseignants(payload: AppPayload, semaine: number | null): LigneEnseignant[] {
  const acc = new Map<string, { sem: number; tot: number; n: number; matieres: Set<string> }>();
  for (const r of payload.rows) {
    for (const t of r.te) {
      const cur = acc.get(t) ?? { sem: 0, tot: 0, n: 0, matieres: new Set<string>() };
      const h = heuresDe([r]);
      cur.tot += h;
      if (semaine !== null && r.w === semaine) cur.sem += h;
      cur.n += 1;
      cur.matieres.add(r.c);
      acc.set(t, cur);
    }
  }
  const nonPlacees = new Map<string, number>();
  for (const s of payload.seancesNonPlacees ?? []) {
    for (const p of s.profs) nonPlacees.set(p, (nonPlacees.get(p) ?? 0) + 1);
  }
  const infos = new Map(payload.teachers.map((t) => [t.code, t]));
  return Object.keys(payload.teacherLabels)
    .map((code) => {
      const a = acc.get(code);
      const info = infos.get(code);
      const ecarts = info?.violations.filter((v) => v.reason !== "sae_supervision").length ?? 0;
      const sae = (info?.violations.length ?? 0) - ecarts;
      const contrainte: EtatContrainte = !info?.hasConstraint
        ? "aucune"
        : ecarts
          ? "ecarts"
          : sae
            ? "sae"
            : "respectee";
      return {
        code,
        nom: payload.teacherLabels[code] ?? code,
        email: (payload.teacherEmails[code] ?? "").trim(),
        heuresSemaine: a?.sem ?? 0,
        heuresSemestre: a?.tot ?? 0,
        nSeances: a?.n ?? 0,
        nMatieres: a?.matieres.size ?? 0,
        nNonPlacees: nonPlacees.get(code) ?? 0,
        contrainte,
        nEcarts: ecarts,
      };
    })
    .sort((x, y) => x.nom.localeCompare(y.nom, "fr"));
}

// ── Groupes ────────────────────────────────────────────────────────────

export interface LigneGroupe {
  id: string;
  libelle: string;
  parcours: string;
  /** « promo », « td », « tp » (cf. `payload.groupKind`). */
  type: string;
  fc: boolean;
  heuresSemaine: number;
  heuresSemestre: number;
}

const ORDRE_TYPE: Record<string, number> = { promo: 0, cm: 0, td: 1, tp: 2 };

/** Ce que suit un étudiant du groupe : le groupe, son CM de promo et ses TP
 *  (`groupCohort`) — la même cohorte que la fiche du groupe. */
export function annuaireGroupes(payload: AppPayload, semaine: number | null): LigneGroupe[] {
  const ids = Object.keys(payload.groupLabels);
  // Séances de chaque groupe, puis union sur la cohorte.
  const parGroupe = new Map<string, AppRow[]>();
  for (const r of payload.rows) {
    for (const g of r.g) {
      const l = parGroupe.get(g) ?? [];
      l.push(r);
      parGroupe.set(g, l);
    }
  }
  return ids
    .map((id) => {
      const cohorte = payload.groupCohort[id] ?? [id];
      const rows = new Map<string, AppRow>();
      for (const g of cohorte) for (const r of parGroupe.get(g) ?? []) rows.set(r.id, r);
      const toutes = [...rows.values()];
      return {
        id,
        libelle: payload.groupLabels[id] ?? id,
        parcours: payload.groupParcours[id] ?? "",
        type: payload.groupKind[id] ?? "",
        fc: Boolean(payload.groupIsFc[id]),
        heuresSemaine: semaine === null ? 0 : heuresOccupees(toutes.filter((r) => r.w === semaine)),
        heuresSemestre: heuresOccupees(toutes),
      };
    })
    .sort(
      (a, b) =>
        compareParcoursForDisplay(a.parcours, b.parcours) ||
        (ORDRE_TYPE[a.type] ?? 9) - (ORDRE_TYPE[b.type] ?? 9) ||
        a.libelle.localeCompare(b.libelle, "fr"),
    );
}

// ── Cours ──────────────────────────────────────────────────────────────

export interface LigneCours {
  code: string;
  nom: string;
  parcours: string;
  semestre: string;
  /** Séances prévues par la maquette (CM + TD + TP + évaluations). */
  prevues: number;
  placees: number;
  nonPlacees: number;
  heuresSemaine: number;
  heuresPlacees: number;
  enseignants: string[];
}

/** Une ligne par matière ET par parcours (une ressource commune à deux
 *  parcours a deux maquettes). Les séances d'une ligne sont celles dont un
 *  groupe appartient au parcours — toutes, quand la matière n'en a qu'un. */
export function annuaireCours(payload: AppPayload, semaine: number | null): LigneCours[] {
  const parCode = new Map<string, AppRow[]>();
  for (const r of payload.rows) {
    const l = parCode.get(r.c) ?? [];
    l.push(r);
    parCode.set(r.c, l);
  }
  const nbEntrees = new Map<string, number>();
  for (const e of payload.courses) nbEntrees.set(e.code, (nbEntrees.get(e.code) ?? 0) + 1);
  return payload.courses
    .map((e) => {
      const toutes = parCode.get(e.code) ?? [];
      const rows =
        (nbEntrees.get(e.code) ?? 1) > 1
          ? toutes.filter((r) => r.g.some((g) => payload.groupParcours[g] === e.parcours))
          : toutes;
      const enseignants = [...new Set([...e.teachers, ...rows.flatMap((r) => r.te)])];
      return {
        code: e.code,
        nom: e.name,
        parcours: e.parcours,
        semestre: e.semestre,
        prevues: e.nCM + e.nTD + e.nTP + e.nEval,
        placees: e.nPlaced,
        nonPlacees: (payload.seancesNonPlacees ?? []).filter(
          (s) => s.code === e.code && (!s.parcours || !e.parcours || s.parcours === e.parcours),
        ).length,
        heuresSemaine: semaine === null ? 0 : heuresDe(rows.filter((r) => r.w === semaine)),
        heuresPlacees: heuresDe(rows),
        enseignants,
      };
    })
    .sort(
      (a, b) =>
        compareParcoursForDisplay(a.parcours, b.parcours) ||
        a.semestre.localeCompare(b.semestre, "fr") ||
        a.code.localeCompare(b.code, "fr", { numeric: true }),
    );
}

// ── Salles ─────────────────────────────────────────────────────────────

export interface LigneSalle {
  id: string;
  libelle: string;
  capacite: number;
  type: string;
  placementAuto: boolean;
  /** Créneaux occupés de la semaine (sur `CRENEAUX_SEMAINE`), fusions et
   *  réservations comprises — même calcul que « Salles libres ». */
  creneauxOccupes: number;
  /** 0 → 1. */
  taux: number;
  seancesSemestre: number;
}

export function annuaireSalles(payload: AppPayload, semaine: number | null): LigneSalle[] {
  const occupes = new Map<string, number>();
  if (semaine !== null) {
    for (let d = 0; d < 5; d += 1) {
      for (const [id, cases] of occupationSalles(payload, semaine, d)) {
        occupes.set(id, (occupes.get(id) ?? 0) + cases.filter(Boolean).length);
      }
    }
  }
  return payload.rooms
    .map((r) => {
      const n = occupes.get(r.id) ?? 0;
      return {
        id: r.id,
        libelle: r.label,
        capacite: r.capacity,
        type: r.type,
        placementAuto: r.placementAuto,
        creneauxOccupes: n,
        taux: n / CRENEAUX_SEMAINE,
        seancesSemestre: r.nSessions,
      };
    })
    .sort((a, b) => a.libelle.localeCompare(b.libelle, "fr"));
}

/** Libellés lisibles des types de salle du catalogue (`rooms.yaml`). */
const TYPES_SALLE: Record<string, string> = {
  standard: "Salle banalisée",
  tp_standard: "Salle de TP",
  combined: "Salles réunies",
  studio_av: "Studio audiovisuel",
  evaluation: "Salle d'examen",
  td_design: "Salle de design",
  tp_mac: "Salle Mac",
  amphi: "Amphithéâtre",
  tp_anglais: "Salle de langues",
  tp_vr_reseaux: "Salle VR / réseaux",
  reserve: "Réservée",
};

export function libelleTypeSalle(type: string): string {
  return TYPES_SALLE[type] ?? type.replace(/_/g, " ");
}

/** Libellé d'un type de groupe : « Promo », « TD », « TP ». */
export function libelleTypeGroupe(type: string): string {
  if (type === "promo" || type === "cm") return "Promo";
  return type.toUpperCase();
}
