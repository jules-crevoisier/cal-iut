/**
 * Filtre TP/TD dans la modale semaine par parcours.
 *
 * Retour utilisateur 03/09/2026 : clic BUT1/BUT2 → pouvoir choisir le TP
 * ou TD à regarder, sans noyer la grille de tout le parcours.
 */
import { describe, expect, it } from "vitest";

import type { AppPayload } from "../types/app";
import { emptyPayload, placedRow } from "../test/payloadFixture";
import {
  filtrerRowsParGroupe,
  listerGroupesParcours,
  type FiltreGroupeId,
} from "./parcoursGroupFilter";

function payloadBut1(): AppPayload {
  return emptyPayload({
    groupLabels: {
      "but1-promo": "Promo",
      "but1-td-ab": "TD AB",
      "but1-td-cd": "TD CD",
      "but1-tp-a": "TP A",
      "but1-tp-b": "TP B",
      "but1-tp-c": "TP C",
    },
    groupParcours: {
      "but1-promo": "BUT1",
      "but1-td-ab": "BUT1",
      "but1-td-cd": "BUT1",
      "but1-tp-a": "BUT1",
      "but1-tp-b": "BUT1",
      "but1-tp-c": "BUT1",
      "but2-tp-a": "BUT2-DEV-FI",
    },
    groupKind: {
      "but1-promo": "promo",
      "but1-td-ab": "td",
      "but1-td-cd": "td",
      "but1-tp-a": "tp",
      "but1-tp-b": "tp",
      "but1-tp-c": "tp",
      "but2-tp-a": "tp",
    },
    groupCohort: {
      "but1-tp-a": ["but1-tp-a", "but1-td-ab", "but1-promo"],
      "but1-tp-b": ["but1-tp-b", "but1-td-ab", "but1-promo"],
      "but1-tp-c": ["but1-tp-c", "but1-td-cd", "but1-promo"],
      "but1-td-ab": ["but1-td-ab", "but1-promo"],
      "but1-td-cd": ["but1-td-cd", "but1-promo"],
      "but1-promo": ["but1-promo"],
    },
  });
}

describe("listerGroupesParcours", () => {
  it("should list TD then TP of the parcours, never promo or other years", () => {
    const liste = listerGroupesParcours(payloadBut1(), "BUT1");
    expect(liste.map((g) => g.id)).toEqual([
      "but1-td-ab",
      "but1-td-cd",
      "but1-tp-a",
      "but1-tp-b",
      "but1-tp-c",
    ]);
    expect(liste.map((g) => g.label)).toEqual(["TD AB", "TD CD", "TP A", "TP B", "TP C"]);
  });
});

describe("filtrerRowsParGroupe", () => {
  const rows = [
    placedRow({ id: "cm", w: 0, d: 0, s: 0, c: "WR100", t: "CM", g: ["but1-promo"] }),
    placedRow({ id: "td-ab", w: 0, d: 0, s: 1, c: "WR101", t: "TD", g: ["but1-td-ab"] }),
    placedRow({ id: "tp-a", w: 0, d: 1, s: 0, c: "WR115", t: "TP", g: ["but1-tp-a"] }),
    placedRow({ id: "tp-c", w: 0, d: 1, s: 1, c: "WR116", t: "TP", g: ["but1-tp-c"] }),
  ];
  const parcoursIds = new Set([
    "but1-promo",
    "but1-td-ab",
    "but1-td-cd",
    "but1-tp-a",
    "but1-tp-b",
    "but1-tp-c",
  ]);

  it("should keep all parcours rows when filtre is Tout", () => {
    const filtre: FiltreGroupeId = "Tout";
    expect(filtrerRowsParGroupe(rows, filtre, payloadBut1(), "BUT1", parcoursIds).map((r) => r.id)).toEqual([
      "cm",
      "td-ab",
      "tp-a",
      "tp-c",
    ]);
  });

  it("should keep the TP cohort (TP + TD + CM promo) when a TP is selected", () => {
    expect(
      filtrerRowsParGroupe(rows, "but1-tp-a", payloadBut1(), "BUT1", parcoursIds).map((r) => r.id),
    ).toEqual(["cm", "td-ab", "tp-a"]);
  });

  it("should keep TD + CM when a TD is selected, not other TPs", () => {
    expect(
      filtrerRowsParGroupe(rows, "but1-td-cd", payloadBut1(), "BUT1", parcoursIds).map((r) => r.id),
    ).toEqual(["cm", "tp-c"]);
  });
});
