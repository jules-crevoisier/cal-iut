import { describe, expect, it } from "vitest";

import type { Doublon } from "../api/client";
import { emptyPayload } from "../test/payloadFixture";
import { coursEnConflit, grouperDoublonsParSemaine, libelleCreneauDoublon, routeVersDoublon } from "./doublons";

const payload = emptyPayload({
  weekLabels: ["Semaine 1", "Semaine 2"],
  weekDates: ["2026-09-28", "2026-10-05"],
});

function doublon(overrides: Partial<Doublon> = {}): Doublon {
  return {
    semaine: 0,
    jour: 0,
    creneau: 0,
    type: "salle",
    ressource: "H.201 / H.203",
    seances: [
      { session_id: "a", course_code: "WR101", groupes: ["g1"], salle: "H.201", enseignants: ["MRI"] },
      { session_id: "b", course_code: "WR205", groupes: ["g2"], salle: "H.203", enseignants: ["AUT"] },
    ],
    ...overrides,
  };
}

describe("libelleCreneauDoublon", () => {
  it("formats a real weekday + ordinal day + short month + slot label", () => {
    // Semaine 0 -> lundi 28/09/2026 ; jeudi = +3 jours -> 1er octobre.
    expect(libelleCreneauDoublon(payload, 0, 3, 3)).toBe("jeudi 1er oct., 14h–15h30");
  });

  it("does not use the ordinal form past the 1st of the month", () => {
    // Semaine 1 -> lundi 05/10/2026 ; mardi = +1 jour -> 6 octobre.
    expect(libelleCreneauDoublon(payload, 1, 1, 0)).toBe("mardi 6 oct., 8h–9h30");
  });

  it("falls back to '?' when the week has no known date", () => {
    expect(libelleCreneauDoublon(payload, 99, 0, 0)).toBe("?, 8h–9h30");
  });
});

describe("routeVersDoublon", () => {
  it("sends the raw solver week index as sem, never a display index", () => {
    expect(routeVersDoublon({ semaine: 7, jour: 2 })).toEqual({ vue: "promo", sem: 7, jour: 2 });
  });
});

describe("grouperDoublonsParSemaine", () => {
  it("groups by solver week index, preserving arrival order within a week", () => {
    const doublons = [
      doublon({ semaine: 0, type: "enseignant", ressource: "MRI" }),
      doublon({ semaine: 1, type: "salle", ressource: "H.007" }),
      doublon({ semaine: 0, type: "salle", ressource: "H.101" }),
    ];
    const groupes = grouperDoublonsParSemaine(payload, doublons);
    expect(groupes.map((g) => g.semaine)).toEqual([0, 1]);
    expect(groupes[0].libelle).toBe("Semaine 1");
    expect(groupes[0].doublons.map((d) => d.ressource)).toEqual(["MRI", "H.101"]);
    expect(groupes[1].doublons.map((d) => d.ressource)).toEqual(["H.007"]);
  });

  it("falls back to a generic label when the week has no known libellé", () => {
    const groupes = grouperDoublonsParSemaine(payload, [doublon({ semaine: 42 })]);
    expect(groupes[0].libelle).toBe("Semaine 43");
  });

  it("returns an empty list for no doublons", () => {
    expect(grouperDoublonsParSemaine(payload, [])).toEqual([]);
  });
});

describe("coursEnConflit", () => {
  it("joins the distinct course codes in conflict", () => {
    expect(coursEnConflit(doublon())).toBe("WR101 / WR205");
  });

  it("does not repeat a course code shared by more than one colliding session", () => {
    const d = doublon({
      seances: [
        { session_id: "a", course_code: "WR101", groupes: ["g1"], salle: "H.201", enseignants: ["MRI"] },
        { session_id: "b", course_code: "WR101", groupes: ["g2"], salle: "H.203", enseignants: ["MRI"] },
      ],
    });
    expect(coursEnConflit(d)).toBe("WR101");
  });
});
