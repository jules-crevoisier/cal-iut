/**
 * Contrat pur du parcage inter-semaines : décider park / navigate / refuse,
 * un seul parcage à la fois, masquage grille, sélection explicite.
 */
import { describe, expect, it } from "vitest";

import type { Placement } from "../../types";
import type { WeekRow } from "../../types/app";
import {
  clearPark,
  createPark,
  decideWeekDrop,
  isHiddenOnGrid,
  replacePark,
  selectPark,
  type ParkUiState,
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
    expect(
      decideWeekDrop({
        placement: null,
        target: semaineCible,
        currentSolverWeek: 0,
      }),
    ).toBe("refuse");
  });

  it("should return refuse when the session is locked", () => {
    expect(
      decideWeekDrop({
        placement: placement({ locked: true }),
        target: semaineCible,
        currentSolverWeek: 0,
      }),
    ).toBe("refuse");
  });

  it("should return refuse when the target week is missing", () => {
    expect(
      decideWeekDrop({
        placement: placement(),
        target: undefined,
        currentSolverWeek: 0,
      }),
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

  it("should return refuse when the target weekIndex is null", () => {
    expect(
      decideWeekDrop({
        placement: placement(),
        target: { ...semaineCible, weekIndex: null },
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

describe("createPark / isHiddenOnGrid / selectPark / clearPark / replacePark", () => {
  it("should snapshot origin week day slot room and labels when createPark runs", () => {
    const source = placement({ week: 2, day: 3, slot: 4, room_id: "b204", room_label: "B204" });
    const state = createPark(source, 1);
    source.week = 99;
    source.day = 99;
    source.slot = 99;
    expect(state.parked).toEqual({
      sessionId: "maquette-1",
      origin: expect.objectContaining({
        session_id: "maquette-1",
        week: 2,
        day: 3,
        slot: 4,
        room_id: "b204",
        room_label: "B204",
        course_code: "WR101",
        course_name: "Écriture",
      }),
      viaDisplayWeek: 1,
    });
    expect(state.selected).toBe(false);
  });

  it("should hide the parked session on the grid when createPark has run", () => {
    const state = createPark(placement(), 1);
    expect(isHiddenOnGrid(state, "maquette-1")).toBe(true);
  });

  it("should not hide another session when a different one is parked", () => {
    const state = createPark(placement(), 1);
    expect(isHiddenOnGrid(state, "maquette-2")).toBe(false);
  });

  it("should keep selected false when createPark runs", () => {
    expect(createPark(placement(), 1).selected).toBe(false);
  });

  it("should mark the park selected only when selectPark is called", () => {
    const parked = createPark(placement(), 1);
    expect(parked.selected).toBe(false);
    const selected = selectPark(parked);
    expect(selected.selected).toBe(true);
    expect(selected.parked?.sessionId).toBe("maquette-1");
    expect(isHiddenOnGrid(selected, "maquette-1")).toBe(true);
  });

  it("should leave selected false when selectPark runs without a parked session", () => {
    const vide: ParkUiState = { parked: null, selected: false };
    expect(selectPark(vide)).toEqual({ parked: null, selected: false });
  });

  it("should clear the park when clearPark is called", () => {
    const state = clearPark(selectPark(createPark(placement(), 1)));
    expect(state.parked).toBeNull();
    expect(state.selected).toBe(false);
    expect(isHiddenOnGrid(state, "maquette-1")).toBe(false);
  });

  it("should replace the first park when replacePark receives a second session", () => {
    const premier = createPark(placement({ session_id: "s-a", course_code: "WR101" }), 1);
    const state = replacePark(premier, placement({ session_id: "s-b", course_code: "WR102", slot: 1 }), 2);
    expect(state.parked?.sessionId).toBe("s-b");
    expect(state.parked?.origin.slot).toBe(1);
    expect(state.parked?.viaDisplayWeek).toBe(2);
    expect(state.selected).toBe(false);
    expect(isHiddenOnGrid(state, "s-b")).toBe(true);
    expect(isHiddenOnGrid(state, "s-a")).toBe(false);
  });
});
