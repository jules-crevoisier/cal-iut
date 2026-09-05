/**
 * Contrat de recherche : index catalogues complets, 4 kinds, routes fiche.
 * Un cours ou une salle sans aucune séance placée doit quand même sortir.
 */
import { describe, expect, it } from "vitest";

import { buildSearchIndex, runSearch, type SearchHit } from "./search";
import {
  catalogCourse,
  catalogRoom,
  emptyPayload,
  placedRow,
} from "../test/payloadFixture";

function routeOf(hit: SearchHit): Record<string, unknown> {
  return hit.route as Record<string, unknown>;
}

const payload = emptyPayload({
  teacherLabels: { KBR: "Lefèvre Kevin" },
  groupLabels: { G1: "TP A" },
  courses: [
    catalogCourse("WR106", "Écriture web", { nPlaced: 0 }),
    catalogCourse("MATH1", "Mathématiques", { nPlaced: 2 }),
  ],
  rooms: [
    catalogRoom("INUTILISEE", { label: "Salle froide", nSessions: 0 }),
    catalogRoom("B204", { nSessions: 3 }),
  ],
  rows: [
    placedRow({
      id: "placed-math",
      c: "MATH1",
      n: "Mathématiques",
      te: ["KBR"],
      g: ["G1"],
      r: "B204",
    }),
  ],
});

describe("buildSearchIndex", () => {
  it("should route each kind to its admin fiche when the index is built from catalogs", () => {
    const index = buildSearchIndex(payload);

    const kinds = [...new Set(index.map((hit) => hit.kind))].sort();
    expect(kinds).toEqual(["Cours", "Enseignant", "Groupe", "Salle"]);

    const teacher = index.find((h) => h.kind === "Enseignant" && h.route.prof === "KBR");
    expect(teacher).toBeDefined();
    expect(routeOf(teacher!)).toMatchObject({ vue: "prof", prof: "KBR" });

    const groupe = index.find((h) => h.kind === "Groupe" && h.route.groupe === "G1");
    expect(groupe).toBeDefined();
    expect(routeOf(groupe!)).toMatchObject({ vue: "groupe", groupe: "G1" });

    const cours = index.find(
      (h) =>
        h.kind === "Cours" &&
        (routeOf(h).cours === "WR106" || h.label.includes("WR106") || h.sub.includes("WR106")),
    );
    expect(cours).toBeDefined();
    expect(routeOf(cours!)).toMatchObject({ vue: "cours", cours: "WR106" });

    const salle = index.find(
      (h) =>
        h.kind === "Salle" &&
        (routeOf(h).salle === "INUTILISEE" || h.label.includes("froide") || h.sub.includes("INUTILISEE")),
    );
    expect(salle).toBeDefined();
    expect(routeOf(salle!)).toMatchObject({ vue: "salle", salle: "INUTILISEE" });
  });

  it("should include a course with 0 placed rows when it exists only in the catalog", () => {
    const hits = runSearch(buildSearchIndex(payload), "WR106");
    expect(hits.some((h) => h.kind === "Cours")).toBe(true);
    for (const hit of hits.filter((h) => h.kind === "Cours")) {
      expect(routeOf(hit).vue).not.toBe("semaine");
      expect(routeOf(hit)).toMatchObject({ vue: "cours", cours: "WR106" });
    }
  });

  it("should include a room with 0 sessions when it exists only in the catalog", () => {
    const hits = runSearch(buildSearchIndex(payload), "froide");
    expect(hits.some((h) => h.kind === "Salle")).toBe(true);
    for (const hit of hits.filter((h) => h.kind === "Salle")) {
      expect(routeOf(hit).vue).not.toBe("reference");
      expect(routeOf(hit)).toMatchObject({ vue: "salle", salle: "INUTILISEE" });
    }
  });

  it("should add one Promo result per distinct parcours, routing to Vue Promo filtered on it", () => {
    // Retour utilisateur 05/09/2026 : chercher un groupe CM et cliquer
    // dessus n'affichait QUE les CM — il faut pouvoir choisir les TD de la
    // même promo. La recherche gagne donc un résultat « Promo » à part,
    // par parcours, qui ouvre la Vue Promo déjà filtrée dessus.
    const avecPromo = emptyPayload({
      groupLabels: { cm1: "CM", td1: "TD AB" },
      groupParcours: { cm1: "BUT1", td1: "BUT1" },
    });
    const index = buildSearchIndex(avecPromo);
    const promo = index.find((h) => h.kind === "Promo" && h.label === "BUT1");
    expect(promo).toBeDefined();
    expect(routeOf(promo!)).toMatchObject({ vue: "promo", parcours: "BUT1" });
    // Un seul résultat Promo pour BUT1, pas un par groupe.
    expect(index.filter((h) => h.kind === "Promo" && h.label === "BUT1")).toHaveLength(1);
  });

  it("should return no hits when the query matches nothing", () => {
    expect(runSearch(buildSearchIndex(payload), "zzzz-inconnu")).toEqual([]);
  });

  it("should not send a placed course to vue=semaine when searching MATH1", () => {
    const hits = runSearch(buildSearchIndex(payload), "MATH1");
    const cours = hits.filter((h) => h.kind === "Cours");
    expect(cours.length).toBeGreaterThan(0);
    for (const hit of cours) {
      expect(routeOf(hit).vue).not.toBe("semaine");
      expect(routeOf(hit)).toMatchObject({ vue: "cours", cours: "MATH1" });
    }
  });

  it("should not send a used room to vue=reference when searching B204", () => {
    const hits = runSearch(buildSearchIndex(payload), "B204");
    const salles = hits.filter((h) => h.kind === "Salle");
    expect(salles.length).toBeGreaterThan(0);
    for (const hit of salles) {
      expect(routeOf(hit).vue).not.toBe("reference");
      expect(routeOf(hit)).toMatchObject({ vue: "salle", salle: "B204" });
    }
  });
});
