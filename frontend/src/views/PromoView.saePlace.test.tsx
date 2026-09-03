/**
 * Click-to-place sur une cellule SAE : la bande ne doit plus manger le clic.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SeanceAPlacer } from "../api/client";
import { emptyPayload, testRoute } from "../test/payloadFixture";
import { PromoView } from "./PromoView";

vi.mock("../utils/placement", async () => {
  const actual = await vi.importActual<typeof import("../utils/placement")>("../utils/placement");
  return {
    ...actual,
    placerAvecConfirmation: vi.fn().mockResolvedValue({ ok: true }),
  };
});

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const aPlacer: SeanceAPlacer = {
  session_id: "ws-sae",
  course_code: "WS101",
  course_name: "SAE",
  session_type: "TD",
  semestre: "S1",
  parcours: "BUT1",
  annee: "BUT1",
  duration_slots: 1,
  duree_libelle: "1h30",
  group_ids: ["but1-td-ab"],
  groupes_libelles: ["TD AB"],
  teacher_codes: ["MRI"],
  enseignants_libelles: ["Martin"],
  sequence_order: 1,
  semaines_possibles: [0],
  raison: "test",
  placee_provisoirement: false,
  semaine_actuelle: null,
  jour_actuel: null,
  slot_actuel: null,
};

const payload = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  groupKind: { "but1-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"] },
  weekRows: [{ monday: "2026-08-31", label: "Semaine 2", blocked: false, weekIndex: 0 }],
  weekLabels: ["S2"],
  weekDates: ["2026-08-31"],
  weekStatus: [{ week: 0, status: "current" }],
  saeRows: [{ w: 0, d: 0, p: "BUT1", codes: ["WS101"] }],
});

describe("PromoView SAE click-to-place", () => {
  it("should keep placer-ici on SAE cells when a placement is active", async () => {
    const { placerAvecConfirmation } = await import("../utils/placement");
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo" })}
        placementActif={aPlacer}
        onAnnulerPlacement={vi.fn()}
        onPlaced={vi.fn()}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );

    const boutons = screen.getAllByRole("button", { name: /\+ poser ici/i });
    expect(boutons.length).toBeGreaterThan(0);
    fireEvent.click(boutons[0]!);
    expect(placerAvecConfirmation).toHaveBeenCalled();
  });
});
