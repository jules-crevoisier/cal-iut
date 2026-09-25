/**
 * Aides pures pour la ligne de résumé du contrôle hebdomadaire des doublons
 * (Jules Crevoisier, 25/09/2026, écran « À traiter ») : libellé, marquage
 * « nouveau » d'une ligne de la liste existante. Testées indépendamment de
 * `TodoView`, même patron que `utils/doublons.ts`.
 */
import { describe, expect, it } from "vitest";

import type { Doublon, DoublonHebdoRun } from "../api/client";
import { estNouveau, libelleControleHebdo } from "./controleDoublonsHebdo";

function doublon(overrides: Partial<Doublon> = {}): Doublon {
  return {
    semaine: 0,
    jour: 3,
    creneau: 3,
    type: "salle",
    ressource: "H.201 / H.203",
    seances: [],
    ...overrides,
  };
}

function run(overrides: Partial<DoublonHebdoRun> = {}): DoublonHebdoRun {
  return {
    date: "2026-09-25",
    semaine_iso: "2026-W39",
    genere_le: "2026-09-25T08:00:00+00:00",
    total: 111,
    par_type: { salle: 80, enseignant: 31 },
    doublons: [],
    nouveaux: [],
    resolus: [],
    premier_controle: false,
    ...overrides,
  };
}

describe("libelleControleHebdo", () => {
  it("names the date (fr), the total and the new-since-previous count", () => {
    expect(libelleControleHebdo(run({ date: "2026-09-25", total: 111, nouveaux: [doublon(), doublon(), doublon(), doublon()] }))).toBe(
      "Contrôle du 25/09/2026 : 111 doublons — 4 nouveaux depuis le contrôle précédent",
    );
  });

  it("uses the singular for exactly one new doublon", () => {
    expect(libelleControleHebdo(run({ nouveaux: [doublon()] }))).toBe(
      "Contrôle du 25/09/2026 : 111 doublons — 1 nouveau depuis le contrôle précédent",
    );
  });

  it("omits the 'depuis le contrôle précédent' clause on the very first control", () => {
    expect(libelleControleHebdo(run({ premier_controle: true, nouveaux: [] }))).toBe("Contrôle du 25/09/2026 : 111 doublons");
  });

  it("says so plainly when there is nothing to fix", () => {
    expect(libelleControleHebdo(run({ total: 0, nouveaux: [], premier_controle: true }))).toBe(
      "Contrôle du 25/09/2026 : aucun doublon",
    );
  });

  it("does not append the new-count clause when nothing changed since the previous control", () => {
    expect(libelleControleHebdo(run({ nouveaux: [] }))).toBe("Contrôle du 25/09/2026 : 111 doublons");
  });
});

describe("estNouveau", () => {
  it("matches on the stable key (semaine, jour, creneau, type, ressource)", () => {
    const d = doublon({ semaine: 5, jour: 2, creneau: 3, type: "salle", ressource: "H.007" });
    const r = run({ nouveaux: [doublon({ semaine: 5, jour: 2, creneau: 3, type: "salle", ressource: "H.007" })] });
    expect(estNouveau(r, d)).toBe(true);
  });

  it("does not match a doublon absent from nouveaux", () => {
    const d = doublon({ ressource: "H.007" });
    const r = run({ nouveaux: [doublon({ ressource: "H.201" })] });
    expect(estNouveau(r, d)).toBe(false);
  });

  it("returns false when there is no run yet", () => {
    expect(estNouveau(null, doublon())).toBe(false);
  });
});
