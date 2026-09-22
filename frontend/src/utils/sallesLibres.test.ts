/**
 * Logique pure de la Vue « Salles libres » (todo département 22/09/2026,
 * Kyllian Bresson : « Planning des salles disponibles »). Rouge d'abord :
 * `occupationSalles`/`sallesLibresAuCreneau` n'existent pas encore.
 */
import { describe, expect, it } from "vitest";

import { catalogRoom, emptyPayload, placedRow } from "../test/payloadFixture";
import { occupationSalles, sallesLibresAuCreneau } from "./sallesLibres";

describe("occupationSalles", () => {
  it("should mark a slot occupied for a duration-1 session", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 2, dur: 1, r: "H.101", c: "WR108", t: "TD" })],
    });

    const grille = occupationSalles(payload, 0, 0);

    expect(grille.get("h101")?.[2]).toEqual([{ code: "WR108", type: "TD", groupes: [] }]);
    expect(grille.get("h101")?.[1]).toBeNull();
    expect(grille.get("h101")?.[3]).toBeNull();
  });

  it("should occupy both s and s+1 for a duration-2 session", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 2, dur: 2, r: "H.101", c: "WR108", t: "TP" })],
    });

    const grille = occupationSalles(payload, 0, 0);

    expect(grille.get("h101")?.[2]).not.toBeNull();
    expect(grille.get("h101")?.[3]).not.toBeNull();
    expect(grille.get("h101")?.[4]).toBeNull();
  });

  it("should not let a duration overflowing the day crash (capped at slot 5)", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 5, dur: 2, r: "H.101", c: "WR108", t: "TP" })],
    });

    expect(() => occupationSalles(payload, 0, 0)).not.toThrow();
  });

  it("should match a room label with a suffix like « (Évaluation) »", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("a018", { label: "A.018" })],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 0, dur: 1, r: "A.018 (Évaluation)", c: "WR108", t: "CM", ev: true })],
    });

    const grille = occupationSalles(payload, 0, 0);

    expect(grille.get("a018")?.[0]).not.toBeNull();
  });

  it("should ignore rows from another week or another day", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [
        placedRow({ id: "s1", w: 1, d: 0, s: 0, dur: 1, r: "H.101", c: "AUTRE", t: "TD" }),
        placedRow({ id: "s2", w: 0, d: 1, s: 0, dur: 1, r: "H.101", c: "AUTRE", t: "TD" }),
      ],
    });

    const grille = occupationSalles(payload, 0, 0);

    expect(grille.get("h101")?.[0]).toBeNull();
  });

  it("should occupy each half when the combined room is booked directly", () => {
    const payload = emptyPayload({
      rooms: [
        catalogRoom("h007", { label: "H.007" }),
        catalogRoom("h008", { label: "H.008" }),
        catalogRoom("h007_h008", { label: "H.007+H.008", combines: ["h007", "h008"] }),
      ],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 0, dur: 1, r: "H.007+H.008", c: "WR108", t: "TD" })],
    });

    const grille = occupationSalles(payload, 0, 0);

    expect(grille.get("h007_h008")?.[0]).not.toBeNull();
    expect(grille.get("h007")?.[0]).not.toBeNull();
    expect(grille.get("h008")?.[0]).not.toBeNull();
  });

  it("should occupy the combined room when only one half is booked, without occupying the other half", () => {
    const payload = emptyPayload({
      rooms: [
        catalogRoom("h007", { label: "H.007" }),
        catalogRoom("h008", { label: "H.008" }),
        catalogRoom("h007_h008", { label: "H.007+H.008", combines: ["h007", "h008"] }),
      ],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 0, dur: 1, r: "H.007", c: "WR108", t: "TD" })],
    });

    const grille = occupationSalles(payload, 0, 0);

    expect(grille.get("h007")?.[0]).not.toBeNull();
    expect(grille.get("h007_h008")?.[0]).not.toBeNull();
    expect(grille.get("h008")?.[0]).toBeNull();
  });
});

describe("réservations par des tiers (salles_reservees.yaml)", () => {
  it("should mark a reserved room busy on its date and slots, with its motive", () => {
    // Semaine 0 = lundi 2026-01-05 (fixture) ; jour 2 = mercredi 7 janvier.
    const payload = emptyPayload({
      rooms: [catalogRoom("h018", { label: "H.018" })],
      roomReservations: [{ salle: "h018", date: "2026-01-07", slots: [1, 2], motif: "Direction" }],
    });

    const grille = occupationSalles(payload, 0, 2);

    expect(grille.get("h018")?.[1]).toEqual([{ code: "Réservée", type: "reservation", groupes: ["Direction"] }]);
    expect(grille.get("h018")?.[2]).not.toBeNull();
    expect(grille.get("h018")?.[0]).toBeNull();
    expect(occupationSalles(payload, 0, 1).get("h018")?.[1]).toBeNull();
    expect(sallesLibresAuCreneau(payload, 0, 2, 1)).toEqual([]);
  });
});

describe("sallesLibresAuCreneau", () => {
  const baseRooms = [
    catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" }),
    catalogRoom("h201", { label: "H.201", capacity: 40, type: "standard" }),
    catalogRoom("bu", { label: "BU / A.123", capacity: 12, type: "reserve", placementAuto: false }),
  ];

  it("should list free rooms sorted by capacity then label", () => {
    const payload = emptyPayload({ rooms: baseRooms, rows: [] });

    const libres = sallesLibresAuCreneau(payload, 0, 0, 0);

    expect(libres.map((r) => r.id)).toEqual(["h101", "h201"]);
  });

  it("should exclude a room occupied at that slot", () => {
    const payload = emptyPayload({
      rooms: baseRooms,
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 0, dur: 1, r: "H.101", c: "WR108", t: "TD" })],
    });

    const libres = sallesLibresAuCreneau(payload, 0, 0, 0);

    expect(libres.map((r) => r.id)).toEqual(["h201"]);
  });

  it("should filter by minimum capacity", () => {
    const payload = emptyPayload({ rooms: baseRooms, rows: [] });

    const libres = sallesLibresAuCreneau(payload, 0, 0, 0, { capaciteMin: 30 });

    expect(libres.map((r) => r.id)).toEqual(["h201"]);
  });

  it("should filter by room type", () => {
    const payload = emptyPayload({ rooms: baseRooms, rows: [] });

    const libres = sallesLibresAuCreneau(payload, 0, 0, 0, { type: "reserve" });

    // "bu" hors placement auto reste exclue même filtrée par type : les deux
    // filtres se combinent (cf. test suivant pour l'inclusion explicite).
    expect(libres.map((r) => r.id)).toEqual([]);
  });

  it("should exclude rooms outside automatic placement by default", () => {
    const payload = emptyPayload({ rooms: baseRooms, rows: [] });

    const libres = sallesLibresAuCreneau(payload, 0, 0, 0);

    expect(libres.map((r) => r.id)).not.toContain("bu");
  });

  it("should include rooms outside automatic placement when asked", () => {
    const payload = emptyPayload({ rooms: baseRooms, rows: [] });

    const libres = sallesLibresAuCreneau(payload, 0, 0, 0, { inclureHorsAuto: true });

    expect(libres.map((r) => r.id)).toContain("bu");
  });
});
