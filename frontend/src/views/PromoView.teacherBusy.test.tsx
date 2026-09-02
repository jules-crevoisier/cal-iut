/**
 * Vue Promo : au glisser, les cases du créneau où l’enseignant a déjà un
 * cours (autre parcours) doivent l’afficher — Forcer reste possible.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { emptyPayload, placedRow, testRoute } from "../test/payloadFixture";
import { PromoView } from "./PromoView";

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

function placementPour(id: string, patch: Partial<Placement> = {}): Placement {
  return {
    session_id: id,
    week: 0,
    day: 0,
    slot: id === "but2" ? 3 : 0,
    course_code: id === "but2" ? "WR311D" : "WR101",
    course_name: id === "but2" ? "Audiovisuel" : "Écriture",
    session_type: "TD",
    group_ids: id === "but2" ? ["but2-dev-fi-td-ab"] : ["but1-td-ab"],
    teacher_codes: ["KBR"],
    room_id: "h005",
    room_label: "H.005",
    is_eval: false,
    locked: false,
    duration_slots: 1,
    ...patch,
  };
}

const payloadDeuxParcours = emptyPayload({
  groupLabels: {
    "but1-td-ab": "TD AB",
    "but2-dev-fi-td-ab": "TD AB DEV",
  },
  groupParcours: {
    "but1-td-ab": "BUT1",
    "but2-dev-fi-td-ab": "BUT2-DEV-FI",
  },
  groupKind: {
    "but1-td-ab": "td",
    "but2-dev-fi-td-ab": "td",
  },
  groupCohort: {
    "but1-td-ab": ["but1-td-ab"],
    "but2-dev-fi-td-ab": ["but2-dev-fi-td-ab"],
  },
  teacherLabels: { KBR: "Bresson Kyllian" },
  weekRows: [{ monday: "2026-08-31", label: "Semaine 2", blocked: false, weekIndex: 0 }],
  weekLabels: ["S2"],
  weekDates: ["2026-08-31"],
  weekStatus: [{ week: 0, status: "current" }],
  rows: [
    placedRow({
      id: "but1",
      w: 0,
      d: 0,
      s: 0,
      c: "WR101",
      t: "TD",
      te: ["KBR"],
      g: ["but1-td-ab"],
    }),
    placedRow({
      id: "but2",
      w: 0,
      d: 0,
      s: 3,
      c: "WR311D",
      t: "TD",
      te: ["KBR"],
      g: ["but2-dev-fi-td-ab"],
    }),
  ],
});

const dataTransfer = { effectAllowed: "move", setData: vi.fn(), getData: vi.fn() };

function chipDansGrille(code: string): HTMLElement {
  const texte = within(screen.getByRole("table")).getByText(code);
  return (texte.closest("[draggable]") ?? texte.parentElement) as HTMLElement;
}

describe("PromoView teacher busy overlay", () => {
  it("should show the already placed course on empty cells when dragging the same teacher", () => {
    render(
      <PromoView
        payload={payloadDeuxParcours}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        placements={[placementPour("but1"), placementPour("but2")]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByText("KBR déjà WR311D")).not.toBeInTheDocument();
    fireEvent.dragStart(chipDansGrille("WR101"), { dataTransfer });
    expect(screen.getAllByText("KBR déjà WR311D").length).toBeGreaterThan(0);
  });

  it("should not label the occupied cell that already shows that course", () => {
    render(
      <PromoView
        payload={payloadDeuxParcours}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        placements={[placementPour("but1"), placementPour("but2")]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    fireEvent.dragStart(chipDansGrille("WR101"), { dataTransfer });
    const chip = within(screen.getByRole("table")).getByText("WR311D").closest("td");
    expect(chip).toBeTruthy();
    expect(within(chip as HTMLElement).queryByText("KBR déjà WR311D")).not.toBeInTheDocument();
  });
});
