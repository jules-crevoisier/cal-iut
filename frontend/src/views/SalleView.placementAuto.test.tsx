/**
 * Fiche salle — case « Proposée au placement automatique » (admin) et
 * marqueur « hors auto » — retour utilisateur 22/09/2026 : « supprimer la
 * BU du placement automatique des salles car elle est utilisée pour un seul
 * module, celui de Valérie Mariot ».
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MoiResponse } from "../api/client";
import { SalleView } from "./SalleView";
import { catalogRoom, emptyPayload, testRoute } from "../test/payloadFixture";

const fetchMoi = vi.fn<[], Promise<MoiResponse | null>>();
vi.mock("../api/client", async (importOriginal) => {
  const reel = await importOriginal<typeof import("../api/client")>();
  return { ...reel, fetchMoi: () => fetchMoi() };
});

describe("SalleView — placement automatique", () => {
  it("should show the « hors auto » marker for a room excluded from automatic placement", async () => {
    fetchMoi.mockResolvedValue(null);
    const payload = emptyPayload({
      rooms: [catalogRoom("bu", { label: "BU / A.123", placementAuto: false })],
    });
    render(<SalleView payload={payload} route={testRoute({ vue: "salle", salle: "bu" })} setRoute={vi.fn()} />);
    expect(screen.getByText("hors auto")).toBeInTheDocument();
  });

  it("should not show the checkbox to a non-admin visitor", async () => {
    fetchMoi.mockResolvedValue({ id: 1, email: "e@x.test", role: "edit", status: "active" });
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101", placementAuto: true })],
    });
    render(<SalleView payload={payload} route={testRoute({ vue: "salle", salle: "h101" })} setRoute={vi.fn()} />);
    await waitFor(() => expect(fetchMoi).toHaveBeenCalled());
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("should show the checkbox to an admin, checked when the room is proposed to automatic placement", async () => {
    fetchMoi.mockResolvedValue({ id: 1, email: "admin@x.test", role: "admin", status: "active" });
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101", placementAuto: true })],
    });
    render(<SalleView payload={payload} route={testRoute({ vue: "salle", salle: "h101" })} setRoute={vi.fn()} />);
    const case_ = await screen.findByRole("checkbox", { name: /placement automatique/i });
    expect(case_).toBeChecked();
  });
});
