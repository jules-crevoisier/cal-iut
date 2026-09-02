/**
 * Occupation enseignant sur un autre parcours — visible au déplacement.
 * Forcer reste possible ; la grille doit montrer le cours déjà posé.
 */
import { describe, expect, it } from "vitest";

import { placedRow } from "../test/payloadFixture";
import {
  teacherBusyByDaySlot,
  teacherBusyLabel,
  teacherBusyOnCell,
} from "./teacherBusy";

describe("teacherBusyByDaySlot", () => {
  it("should map the other parcours slot when the same teacher already has a course", () => {
    const rows = [
      placedRow({ id: "but1", w: 0, d: 0, s: 0, c: "WR101", te: ["KBR"], g: ["but1-td-ab"] }),
      placedRow({ id: "but2", w: 0, d: 0, s: 3, c: "WR311D", te: ["KBR"], g: ["but2-dev-fi-td-ab"] }),
    ];
    const hits = teacherBusyByDaySlot(rows, ["KBR"], 0, "but1");
    expect(hits.get("0-3")).toEqual({ course: "WR311D", teachers: ["KBR"] });
    expect(hits.has("0-0")).toBe(false);
  });

  it("should cover every slot of a long block", () => {
    const rows = [
      placedRow({ id: "bloc", w: 0, d: 1, s: 0, c: "WR110", te: ["KBR"], dur: 2, g: ["but1-tp-a"] }),
    ];
    const hits = teacherBusyByDaySlot(rows, ["KBR"], 0, "autre");
    expect(hits.get("1-0")?.course).toBe("WR110");
    expect(hits.get("1-1")?.course).toBe("WR110");
    expect(hits.has("1-2")).toBe(false);
  });

  it("should ignore other weeks and other teachers", () => {
    const rows = [
      placedRow({ id: "s2", w: 1, d: 0, s: 3, c: "WR311D", te: ["KBR"] }),
      placedRow({ id: "mri", w: 0, d: 0, s: 3, c: "WR102", te: ["MRI"] }),
    ];
    const hits = teacherBusyByDaySlot(rows, ["KBR"], 0, "but1");
    expect(hits.size).toBe(0);
  });
});

describe("teacherBusyLabel", () => {
  it("should name the teacher and the course already placed", () => {
    expect(teacherBusyLabel({ course: "WR311D", teachers: ["KBR"] })).toBe("KBR déjà WR311D");
  });
});

describe("teacherBusyOnCell", () => {
  it("should hide the hint when the busy course is already in the cell", () => {
    const map = teacherBusyByDaySlot(
      [placedRow({ id: "but2", w: 0, d: 0, s: 3, c: "WR311D", te: ["KBR"] })],
      ["KBR"],
      0,
      "but1",
    );
    expect(teacherBusyOnCell(map, 0, 3, [])?.course).toBe("WR311D");
    expect(
      teacherBusyOnCell(map, 0, 3, [{ c: "WR311D", te: ["KBR"] }]),
    ).toBeNull();
  });
});
