/**
 * Chiffres des annuaires (refonte v2 du 29/09/2026) : heures de la semaine
 * choisie, du semestre, mail manquant, contrainte, cohorte d'un groupe,
 * volume placé d'une matière, occupation d'une salle.
 */
import { describe, expect, it } from "vitest";

import {
  annuaireCours,
  annuaireEnseignants,
  annuaireGroupes,
  annuaireSalles,
  CRENEAUX_SEMAINE,
  heuresOccupees,
} from "./annuaires";
import { catalogCourse, catalogRoom, catalogTeacher, emptyPayload, placedRow } from "../test/payloadFixture";

const DEUX_SEMAINES = {
  weekLabels: ["S1", "S2"],
  weekDates: ["2026-01-05", "2026-01-12"],
  weekRows: [
    { monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 },
    { monday: "2026-01-12", label: "S2", blocked: false, weekIndex: 1 },
  ],
};

describe("heuresOccupees", () => {
  it("compte une fois un créneau occupé par deux séances en parallèle", () => {
    const rows = [
      placedRow({ id: "a", w: 0, d: 0, s: 0 }),
      placedRow({ id: "b", w: 0, d: 0, s: 0 }),
      placedRow({ id: "c", w: 0, d: 1, s: 2, dur: 2 }),
    ];
    expect(heuresOccupees(rows)).toBe(4.5);
  });
});

describe("annuaireEnseignants", () => {
  const payload = emptyPayload({
    ...DEUX_SEMAINES,
    teacherLabels: { AAA: "Abel Anne", BBB: "Brun Bea", CCC: "Col Cid" },
    teacherEmails: { AAA: "anne@iut.test", BBB: " " },
    teachers: [
      catalogTeacher("AAA", "Abel Anne", { hasConstraint: true }),
      catalogTeacher("BBB", "Brun Bea", {
        hasConstraint: true,
        violations: [
          { course_code: "X", date: "2026-01-05", reason: "declared" },
          { course_code: "X", date: "2026-01-06", reason: "sae_supervision" },
        ],
      }),
    ],
    rows: [
      placedRow({ id: "1", w: 0, te: ["AAA"], c: "WR101" }),
      placedRow({ id: "2", w: 0, te: ["AAA", "BBB"], c: "WR102", dur: 2 }),
      placedRow({ id: "3", w: 1, te: ["AAA"], c: "WR101" }),
    ],
    seancesNonPlacees: [{ id: "n", code: "WR103", nom: "", type: "TD", parcours: "", groupes: [], profs: ["BBB"] }],
  });

  it("donne les heures de la semaine choisie et du semestre, et les matières", () => {
    const [a, b, c] = annuaireEnseignants(payload, 0);
    expect(a).toMatchObject({ code: "AAA", heuresSemaine: 4.5, heuresSemestre: 6, nMatieres: 2, nSeances: 3 });
    expect(b).toMatchObject({ code: "BBB", heuresSemaine: 3, heuresSemestre: 3, nNonPlacees: 1 });
    expect(c).toMatchObject({ code: "CCC", heuresSemaine: 0, nSeances: 0 });
    expect(annuaireEnseignants(payload, 1)[0].heuresSemaine).toBe(1.5);
    expect(annuaireEnseignants(payload, null)[0].heuresSemaine).toBe(0);
  });

  it("signale le mail manquant (vide ou blanc) et l'état de la contrainte", () => {
    const lignes = annuaireEnseignants(payload, 0);
    expect(lignes.map((l) => l.email)).toEqual(["anne@iut.test", "", ""]);
    expect(lignes.map((l) => l.contrainte)).toEqual(["respectee", "ecarts", "aucune"]);
    expect(lignes[1].nEcarts).toBe(1);
  });
});

describe("annuaireGroupes", () => {
  it("compte les heures de la cohorte, TP jumelés en parallèle comptés une fois", () => {
    const payload = emptyPayload({
      groupLabels: { p: "Promo BUT1", td: "TD AB", a: "TP A", b: "TP B" },
      groupKind: { p: "promo", td: "td", a: "tp", b: "tp" },
      groupParcours: { p: "BUT1", td: "BUT1", a: "BUT1", b: "BUT1" },
      groupCohort: { p: ["p"], td: ["p", "td", "a", "b"], a: ["p", "td", "a"], b: ["p", "td", "b"] },
      rows: [
        placedRow({ id: "cm", s: 0, g: ["p"] }),
        placedRow({ id: "tpa", s: 1, g: ["a"] }),
        placedRow({ id: "tpb", s: 1, g: ["b"] }),
      ],
    });
    const lignes = annuaireGroupes(payload, 0);
    // Ordre : promo, puis TD, puis TP.
    expect(lignes.map((l) => l.id)).toEqual(["p", "td", "a", "b"]);
    expect(lignes.map((l) => l.heuresSemaine)).toEqual([1.5, 3, 3, 3]);
  });
});

describe("annuaireCours", () => {
  it("donne le volume placé par rapport à la maquette et les non placées", () => {
    const payload = emptyPayload({
      courses: [catalogCourse("WR101", "Anglais", { nTD: 3, nTP: 1, nPlaced: 2, teachers: ["AAA"] })],
      rows: [placedRow({ id: "1", c: "WR101", te: ["BBB"] }), placedRow({ id: "2", w: 1, c: "WR101" })],
      seancesNonPlacees: [{ id: "n", code: "WR101", nom: "", type: "TD", parcours: "BUT1", groupes: [], profs: [] }],
    });
    expect(annuaireCours(payload, 0)[0]).toMatchObject({
      prevues: 4,
      placees: 2,
      nonPlacees: 1,
      heuresSemaine: 1.5,
      heuresPlacees: 3,
      enseignants: ["AAA", "BBB"],
    });
  });
});

describe("annuaireSalles", () => {
  it("donne les créneaux occupés de la semaine, fusions comprises", () => {
    const payload = emptyPayload({
      rooms: [
        catalogRoom("h007", { label: "H.007" }),
        catalogRoom("h008", { label: "H.008" }),
        catalogRoom("h007_h008", { label: "H.007-008", combines: ["h007", "h008"] }),
      ],
      rows: [placedRow({ id: "1", r: "H.007-008", dur: 2 }), placedRow({ id: "2", d: 1, r: "H.007" })],
    });
    const parId = Object.fromEntries(annuaireSalles(payload, 0).map((l) => [l.id, l]));
    expect(parId.h007.creneauxOccupes).toBe(3);
    expect(parId.h008.creneauxOccupes).toBe(2);
    expect(parId.h007_h008.creneauxOccupes).toBe(3);
    expect(parId.h007.taux).toBeCloseTo(3 / CRENEAUX_SEMAINE);
  });
});
