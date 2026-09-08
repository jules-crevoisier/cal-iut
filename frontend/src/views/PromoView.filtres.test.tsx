/**
 * Filtre année / parcours sur la grille Promo.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { emptyPayload, placedRow, testRoute } from "../test/payloadFixture";
import { PromoView } from "./PromoView";

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const payload = emptyPayload({
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
  teacherLabels: { MRI: "Riguet" },
  weekRows: [{ monday: "2026-08-31", label: "Semaine 2", blocked: false, weekIndex: 0 }],
  weekLabels: ["S2"],
  weekDates: ["2026-08-31"],
  weekStatus: [{ week: 0, status: "current" }],
  rows: [
    placedRow({ id: "b1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"] }),
    placedRow({ id: "b2", w: 0, d: 0, s: 1, c: "WR311D", g: ["but2-dev-fi-td-ab"] }),
  ],
});

describe("PromoView filters", () => {
  // La vue Promo s'ouvre sur le jour EN COURS depuis le 08/09/2026 : sans
  // horloge figée, ces tests passeraient le lundi et échoueraient le mardi.
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-07T09:00:00")); // un lundi
  });
  afterAll(() => vi.useRealTimers());

  it("should hide other years when Année BUT1 is selected", () => {
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo", jour: 0 })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("WR101")).toBeInTheDocument();
    expect(within(table).getByText("WR311D")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/^année$/i), { target: { value: "BUT1" } });
    expect(within(table).getByText("WR101")).toBeInTheDocument();
    expect(within(table).queryByText("WR311D")).not.toBeInTheDocument();
  });
});
