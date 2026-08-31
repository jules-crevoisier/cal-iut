/**
 * Contrat « À traiter » : séances non placées ouvrent le panneau Promo,
 * les autres kinds de routes restent ceux d'aujourd'hui.
 */
import { describe, expect, it } from "vitest";

import { buildTodoList, type TodoItem } from "./todo";
import {
  catalogTeacher,
  emptyPayload,
  placedRow,
} from "../test/payloadFixture";

function routeOf(item: TodoItem): Record<string, unknown> {
  return item.route as Record<string, unknown>;
}

describe("buildTodoList", () => {
  it("should send unplaced sessions to vue=promo with panel=aplacer when seancesNonPlacees exist", () => {
    const items = buildTodoList(
      emptyPayload({
        seancesNonPlacees: [
          {
            id: "np1",
            code: "WR106",
            nom: "Écriture web",
            type: "TD",
            parcours: "BUT1",
            groupes: ["G1"],
            profs: ["KBR"],
          },
        ],
      }),
    );

    const unplaced = items.filter((item) => routeOf(item).vue === "promo" && routeOf(item).panel === "aplacer");
    expect(unplaced.length).toBeGreaterThan(0);
    expect(items.some((item) => item.route.vue === "aplacer")).toBe(false);
  });

  it("should return an empty list when there are no issues", () => {
    expect(buildTodoList(emptyPayload())).toEqual([]);
  });

  it("should keep no-room items on vue=promo and teacher violations on vue=prof when both exist", () => {
    const items = buildTodoList(
      emptyPayload({
        groupLabels: { G1: "TP A" },
        rows: [
          placedRow({
            id: "no-room",
            c: "MATH1",
            n: "Mathématiques",
            g: ["G1"],
            te: ["KBR"],
            r: "",
            w: 2,
            d: 3,
          }),
        ],
        teachers: [
          catalogTeacher("KBR", "Lefèvre Kevin", {
            violations: [
              {
                course_code: "MATH1",
                week: 1,
                reason: "declared",
              },
            ],
          }),
        ],
      }),
    );

    expect(items.some((item) => item.route.vue === "promo" && routeOf(item).panel !== "aplacer")).toBe(true);
    expect(items.some((item) => item.route.vue === "prof" && item.route.prof === "KBR")).toBe(true);
    expect(items.some((item) => item.route.vue === "aplacer")).toBe(false);
  });
});
