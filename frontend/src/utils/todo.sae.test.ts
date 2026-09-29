/**
 * « À traiter » → cours de SAE hors journée SAE (29/09/2026) : le point a la
 * même forme que son miroir serveur — même fixture et mêmes valeurs que
 * `tests/test_a_traiter_sae_2026_09_29.py::test_forme_du_point_comme_le_frontend`.
 */
import { describe, expect, it } from "vitest";

import type { AnomalieSae } from "../api/client";
import { NATURE_PAR_ID, pointsDepuisSae } from "./todo";

const ANOMALIE: AnomalieSae = {
  id: "ws-hors",
  cours_code: "WS101",
  cours_nom: "SAE WS101",
  type: "TD",
  parcours: "BUT1",
  groupes: ["but1-td-ab"],
  groupes_libelles: ["TD AB"],
  enseignants: ["KBR"],
  semaine: 7,
  jour: 0,
  creneau: 0,
};

describe("pointsDepuisSae", () => {
  it("reprend la forme du miroir serveur (parité)", () => {
    const [p] = pointsDepuisSae([ANOMALIE]);
    expect({
      nature: p.nature,
      cle: p.cle,
      titre: p.title,
      detail: p.sub,
      semaine: p.semaine,
      jour: p.jour,
      creneau: p.creneau,
      parcours: p.parcours,
      enseignants: p.enseignants,
      nombre: p.n,
    }).toEqual({
      nature: "sae-hors-journee",
      cle: "sae-hj|ws-hors",
      titre: "WS101 — SAE WS101",
      detail: "TD · TD AB · hors journée SAE",
      semaine: 7,
      jour: 0,
      creneau: 0,
      parcours: ["BUT1"],
      enseignants: ["KBR"],
      nombre: 1,
    });
    expect(p.sev).toBe("bad");
    expect(NATURE_PAR_ID["sae-hors-journee"].sev).toBe("bad");
  });

  it("ouvre la Vue Promo au bon jour, sur le parcours de la séance", () => {
    expect(pointsDepuisSae([ANOMALIE])[0].route).toEqual({ vue: "promo", sem: 7, jour: 0, parcours: "BUT1" });
  });
});
