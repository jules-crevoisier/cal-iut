/**
 * Filtre TP/TD dans la modale semaine (clic nom de promo).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { emptyPayload, placedRow } from "../test/payloadFixture";
import { ParcoursWeekModal } from "./ParcoursWeekModal";

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const weekRows = [
  { monday: "2026-08-31", label: "Semaine 2 (31 août–4 sept. 2026)", blocked: false, weekIndex: 0 },
];

const payload = emptyPayload({
  groupLabels: {
    "but1-promo": "Promo",
    "but1-td-ab": "TD AB",
    "but1-tp-a": "TP A",
    "but1-tp-c": "TP C",
  },
  groupParcours: {
    "but1-promo": "BUT1",
    "but1-td-ab": "BUT1",
    "but1-tp-a": "BUT1",
    "but1-tp-c": "BUT1",
  },
  groupKind: {
    "but1-promo": "promo",
    "but1-td-ab": "td",
    "but1-tp-a": "tp",
    "but1-tp-c": "tp",
  },
  groupCohort: {
    "but1-tp-a": ["but1-tp-a", "but1-td-ab", "but1-promo"],
    "but1-tp-c": ["but1-tp-c", "but1-promo"],
    "but1-td-ab": ["but1-td-ab", "but1-promo"],
    "but1-promo": ["but1-promo"],
  },
  teacherLabels: { MRI: "Riguet Marine" },
  weekLabels: ["S2"],
  weekDates: ["2026-08-31"],
  weekRows,
  weekStatus: [{ week: 0, status: "current" }],
  rows: [
    placedRow({ id: "cm", w: 0, d: 0, s: 0, c: "WR100", n: "CM", t: "CM", g: ["but1-promo"], te: ["MRI"], r: "Amphi" }),
    placedRow({ id: "tp-a", w: 0, d: 1, s: 0, c: "WR115", n: "Hébergement", t: "TP", g: ["but1-tp-a"], te: ["MRI"], r: "H.101" }),
    placedRow({ id: "tp-c", w: 0, d: 2, s: 0, c: "WR116", n: "Réseaux", t: "TP", g: ["but1-tp-c"], te: ["MRI"], r: "H.102" }),
  ],
});

const placements: Placement[] = payload.rows.map((r) => ({
  session_id: r.id,
  week: r.w,
  day: r.d,
  slot: r.s,
  course_code: r.c,
  course_name: r.n,
  session_type: r.t,
  group_ids: r.g,
  teacher_codes: r.te,
  room_id: r.r.toLowerCase(),
  room_label: r.r,
  is_eval: false,
  locked: false,
  duration_slots: 1,
}));

describe("ParcoursWeekModal group filter", () => {
  it("should offer Tout and each TD/TP chip, and hide other TPs when one is selected", () => {
    render(
      <ParcoursWeekModal
        payload={payload}
        parcours="BUT1"
        weekIndex={0}
        placements={placements}
        onClose={vi.fn()}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
      />,
    );

    const filtres = screen.getByRole("group", { name: /filtrer par groupe/i });
    expect(within(filtres).getByRole("button", { name: /^tout$/i })).toBeInTheDocument();
    expect(within(filtres).getByRole("button", { name: /^td ab$/i })).toBeInTheDocument();
    expect(within(filtres).getByRole("button", { name: /^tp a$/i })).toBeInTheDocument();
    expect(within(filtres).getByRole("button", { name: /^tp c$/i })).toBeInTheDocument();

    const table = within(screen.getByRole("dialog")).getByRole("table");
    expect(within(table).getByText("WR115")).toBeInTheDocument();
    expect(within(table).getByText("WR116")).toBeInTheDocument();
    expect(within(table).getByText("WR100")).toBeInTheDocument();

    fireEvent.click(within(filtres).getByRole("button", { name: /^tp a$/i }));
    expect(within(table).getByText("WR115")).toBeInTheDocument();
    expect(within(table).getByText("WR100")).toBeInTheDocument();
    expect(within(table).queryByText("WR116")).not.toBeInTheDocument();
  });
});
