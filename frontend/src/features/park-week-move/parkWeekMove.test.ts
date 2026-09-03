/**
 * Contrat pur du parcage inter-semaines : file multi, sélection, masquage.
 */
import { describe, expect, it } from "vitest";

import type { Placement } from "../../types";
import type { WeekRow } from "../../types/app";
import {
  addPark,
  clearPark,
  createPark,
  decideWeekDrop,
  emptyPark,
  hasParked,
  isHiddenOnGrid,
  removePark,
  replacePark,
  selectPark,
  selectedParked,
} from "./parkWeekMove";

function placement(patch: Partial<Placement> = {}): Placement {
  return {
    session_id: "maquette-1",
    week: 0,
    day: 0,
    slot: 0,
    course_code: "WR101",
    course_name: "Écriture",
    session_type: "TD",
    group_ids: ["but1-td-ab"],
    teacher_codes: ["MRI"],
    room_id: "h005",
    room_label: "H.005",
    is_eval: false,
    locked: false,
    duration_slots: 1,
    ...patch,
  };
}

const semaineCible: WeekRow = {
  monday: "2026-10-12",
  label: "Semaine 8 (12–16 oct. 2026)",
  blocked: false,
  weekIndex: 6,
};

const semaineOrigine: WeekRow = {
  monday: "2026-08-31",
  label: "Semaine 2 (31 août–4 sept. 2026)",
  blocked: false,
  weekIndex: 0,
};

describe("decideWeekDrop", () => {
  it("should return park when an unlocked placement is dropped on another non-blocked week with a solver weekIndex", () => {
    expect(
      decideWeekDrop({
        placement: placement(),
        target: semaineCible,
        currentSolverWeek: 0,
      }),
    ).toBe("park");
  });

  it("should return refuse when placement is missing", () => {
    expect(decideWeekDrop({ placement: null, target: semaineCible, currentSolverWeek: 0 })).toBe("refuse");
  });

  it("should return refuse when the session is locked", () => {
    expect(
      decideWeekDrop({ placement: placement({ locked: true }), target: semaineCible, currentSolverWeek: 0 }),
    ).toBe("refuse");
  });

  it("should return refuse when the target week is blocked", () => {
    expect(
      decideWeekDrop({
        placement: placement(),
        target: { ...semaineCible, blocked: true },
        currentSolverWeek: 0,
      }),
    ).toBe("refuse");
  });

  it("should return navigate when the target week already holds the session", () => {
    expect(
      decideWeekDrop({
        placement: placement({ week: 0 }),
        target: semaineOrigine,
        currentSolverWeek: 6,
      }),
    ).toBe("navigate");
  });
});

describe("multi-park file", () => {
  it("should snapshot origin when createPark runs", () => {
    const source = placement({ week: 2, day: 3, slot: 4 });
    const state = createPark(source, 1);
    source.week = 99;
    expect(state.items).toHaveLength(1);
    expect(state.items[0]?.origin.week).toBe(2);
    expect(state.selectedSessionId).toBeNull();
  });

  it("should keep both sessions when a second is added", () => {
    const premier = createPark(placement({ session_id: "s-a", course_code: "WR101" }), 1);
    const state = addPark(premier, placement({ session_id: "s-b", course_code: "WR102", slot: 1 }), 2);
    expect(state.items.map((p) => p.sessionId)).toEqual(["s-a", "s-b"]);
    expect(isHiddenOnGrid(state, "s-a")).toBe(true);
    expect(isHiddenOnGrid(state, "s-b")).toBe(true);
    expect(state.selectedSessionId).toBeNull();
  });

  it("should not duplicate when the same session is parked twice", () => {
    const premier = createPark(placement({ session_id: "s-a" }), 1);
    const state = addPark(premier, placement({ session_id: "s-a", week: 3 }), 2);
    expect(state.items).toHaveLength(1);
    expect(state.items[0]?.origin.week).toBe(3);
    expect(state.items[0]?.viaDisplayWeek).toBe(2);
  });

  it("should select one session without clearing the queue", () => {
    let state = createPark(placement({ session_id: "s-a" }), 1);
    state = addPark(state, placement({ session_id: "s-b" }), 1);
    state = selectPark(state, "s-a");
    expect(state.selectedSessionId).toBe("s-a");
    expect(selectedParked(state)?.sessionId).toBe("s-a");
    expect(state.items).toHaveLength(2);
  });

  it("should remove only the cancelled session from the queue", () => {
    let state = createPark(placement({ session_id: "s-a" }), 1);
    state = addPark(state, placement({ session_id: "s-b" }), 1);
    state = selectPark(state, "s-a");
    state = removePark(state, "s-a");
    expect(state.items.map((p) => p.sessionId)).toEqual(["s-b"]);
    expect(state.selectedSessionId).toBeNull();
    expect(isHiddenOnGrid(state, "s-a")).toBe(false);
  });

  it("should clear the whole queue with clearPark", () => {
    let state = addPark(createPark(placement({ session_id: "s-a" }), 1), placement({ session_id: "s-b" }), 1);
    state = clearPark(state);
    expect(state).toEqual(emptyPark());
    expect(hasParked(state)).toBe(false);
  });

  it("should append via replacePark (compat) instead of replacing the queue", () => {
    const premier = createPark(placement({ session_id: "s-a" }), 1);
    const state = replacePark(premier, placement({ session_id: "s-b" }), 2);
    expect(state.items.map((p) => p.sessionId)).toEqual(["s-a", "s-b"]);
  });
});
