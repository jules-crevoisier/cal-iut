import { describe, expect, it } from "vitest";

import type { Doublon } from "../api/client";
import { conflitsParSeance } from "./conflitsSeances";

const seance = (id: string, code: string) => ({ session_id: id, course_code: code, groupes: [], salle: null, enseignants: [] });
const payload = { occupationsExternes: undefined };

describe("conflitsParSeance", () => {
  it("distingue conflit de salle et doublon enseignant, cumulables sur une même séance", () => {
    const doublons: Doublon[] = [
      { semaine: 3, jour: 1, creneau: 2, type: "salle", ressource: "H.101", seances: [seance("a", "WR101"), seance("b", "WR102")] },
      { semaine: 3, jour: 1, creneau: 2, type: "enseignant", ressource: "Jean Dupont", seances: [seance("a", "WR101"), seance("c", "WR103")] },
    ];
    const m = conflitsParSeance(doublons, payload, 3);
    expect(m.get("a")?.salle).toHaveLength(1);
    expect(m.get("a")?.enseignant).toHaveLength(1);
    expect(m.get("b")?.salle).toHaveLength(1);
    expect(m.get("b")?.enseignant).toHaveLength(0);
    expect(m.get("c")?.salle).toHaveLength(0);
    expect(m.get("c")?.enseignant).toHaveLength(1);
  });

  it("ignore les autres semaines et ajoute les occupations Celcat de salle", () => {
    const doublons: Doublon[] = [{ semaine: 4, jour: 0, creneau: 0, type: "salle", ressource: "H.101", seances: [seance("a", "X"), seance("b", "Y")] }];
    const celcat = {
      occupationsExternes: {
        conflits: [
          { seance_id: "z", semaine: 3, ressource_type: "salle", ressource: "h018", message: "Amphi pris par TC" },
          { seance_id: "y", semaine: 3, ressource_type: "enseignant", ressource: "x", message: "prof pris" },
        ],
      },
    } as never;
    const m = conflitsParSeance(doublons, celcat, 3);
    expect(m.has("a")).toBe(false);
    expect(m.get("z")?.salle).toEqual(["Amphi pris par TC"]);
    expect(m.has("y")).toBe(false);
  });
});
