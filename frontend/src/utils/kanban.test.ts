import { describe, expect, it } from "vitest";

import { emptyPayload, placedRow } from "../test/payloadFixture";
import { dateReelleRow, libelleDatesTache, routeVersSeance, seancesConcernees } from "./kanban";

const payload = emptyPayload({
  weekRows: [
    { monday: "2026-09-21", label: "Semaine du 21/09", blocked: false, weekIndex: 0 },
    { monday: "2026-09-28", label: "Semaine du 28/09", blocked: false, weekIndex: 1 },
  ],
  teacherLabels: { KBR: "Kyllian Bresson" },
  rows: [
    placedRow({ id: "s1", w: 0, d: 0, s: 0, te: ["KBR"], c: "WR106" }), // lundi 21/09
    placedRow({ id: "s2", w: 0, d: 3, s: 1, te: ["KBR"], c: "WR107" }), // jeudi 24/09
    placedRow({ id: "s3", w: 1, d: 0, s: 0, te: ["KBR"], c: "WR108" }), // lundi 28/09
    placedRow({ id: "s4", w: 0, d: 0, s: 0, te: ["AUT"], c: "WR109" }), // autre enseignant, même jour
  ],
});

describe("dateReelleRow", () => {
  it("computes the real ISO date from the week's monday plus the day offset", () => {
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 0, d: 0 }))).toBe("2026-09-21");
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 0, d: 3 }))).toBe("2026-09-24");
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 1, d: 2 }))).toBe("2026-09-30");
  });

  it("returns null when the row's week has no known monday", () => {
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 99, d: 0 }))).toBeNull();
  });
});

describe("seancesConcernees", () => {
  it("returns nothing when the tache has no teacher", () => {
    expect(seancesConcernees(payload, { enseignant_code: null, date_debut: "2026-09-21", date_fin: null })).toEqual([]);
  });

  it("returns nothing when the tache has no date_debut", () => {
    expect(seancesConcernees(payload, { enseignant_code: "KBR", date_debut: null, date_fin: null })).toEqual([]);
  });

  it("filters by teacher, excluding sessions of another teacher on the same day", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-21", date_fin: "2026-10-05" });
    expect(result.map((r) => r.row.id)).not.toContain("s4");
  });

  it("treats a missing date_fin as a single-day range (date_debut only)", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-21", date_fin: null });
    expect(result.map((r) => r.row.id)).toEqual(["s1"]);
  });

  it("includes every session across a multi-day range", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-21", date_fin: "2026-09-28" });
    expect(result.map((r) => r.row.id)).toEqual(["s1", "s2", "s3"]);
  });

  it("excludes sessions outside the declared range", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-22", date_fin: "2026-09-27" });
    expect(result.map((r) => r.row.id)).toEqual(["s2"]);
  });

  it("sorts results chronologically", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-01", date_fin: "2026-10-01" });
    expect(result.map((r) => r.dateIso)).toEqual(["2026-09-21", "2026-09-24", "2026-09-28"]);
  });
});

describe("routeVersSeance", () => {
  it("sends the raw solver week index as sem, never a display index", () => {
    expect(routeVersSeance(placedRow({ id: "x", w: 7, d: 2 }))).toEqual({ vue: "promo", sem: 7, jour: 2 });
  });
});

describe("libelleDatesTache", () => {
  it("returns null without a start date", () => {
    expect(libelleDatesTache(null, null)).toBeNull();
  });

  it("formats a single day", () => {
    expect(libelleDatesTache("2026-09-25", null)).toBe("25 sept. 2026");
  });

  it("formats identical start/end as a single day", () => {
    expect(libelleDatesTache("2026-09-25", "2026-09-25")).toBe("25 sept. 2026");
  });

  it("formats a multi-day range", () => {
    expect(libelleDatesTache("2026-09-25", "2026-10-02")).toBe("25 sept. – 2 oct. 2026");
  });
});
