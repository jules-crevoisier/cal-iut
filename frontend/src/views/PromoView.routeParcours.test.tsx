/**
 * Retour utilisateur 05/09/2026 : chercher un groupe CM et cliquer dessus
 * n'affichait QUE les CM — il faut pouvoir choisir les TD de la même
 * promo. La recherche route désormais vers la Vue Promo avec
 * `route.parcours` posé ; cette vue doit filtrer dessus à l'arrivée.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
  weekRows: [{ monday: "2026-08-31", label: "Semaine 2", blocked: false, weekIndex: 0 }],
  weekLabels: ["S2"],
  weekDates: ["2026-08-31"],
  weekStatus: [{ week: 0, status: "current" }],
  rows: [
    placedRow({ id: "b1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"] }),
    placedRow({ id: "b2", w: 0, d: 0, s: 1, c: "WR311D", g: ["but2-dev-fi-td-ab"] }),
  ],
});

describe("PromoView filtre via route.parcours (arrivée depuis la recherche)", () => {
  it("should filter the grid to the searched parcours on arrival, showing its TD not just its CM", () => {
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo", jour: 0, parcours: "BUT2-DEV-FI" })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("WR311D")).toBeInTheDocument();
    expect(within(table).queryByText("WR101")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^année$/i)).toHaveValue("BUT2");
  });
});
