/**
 * Carte parquée dans « À placer » : visible, clic = sélection,
 * Annuler = callback — aucun POST /deposer.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { emptyPayload } from "../test/payloadFixture";
import { APlacerView } from "./APlacerView";

const origin: Placement = {
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
};

const inventaireVide = {
  total_a_placer: 0,
  total_placees: 12,
  manquantes: [],
  par_parcours: {},
  resume: "Tout est placé.",
};

function parkState(selected = false) {
  return {
    parked: {
      sessionId: origin.session_id,
      origin,
      viaDisplayWeek: 1,
    },
    selected,
  };
}

function renderParcage(extra: Record<string, unknown> = {}) {
  const onSelectPark = vi.fn();
  const onAnnulerPark = vi.fn();
  render(
    <APlacerView
      onPlacement={vi.fn()}
      payload={emptyPayload()}
      variante="panneau"
      park={parkState()}
      onSelectPark={onSelectPark}
      onAnnulerPark={onAnnulerPark}
      {...extra}
    />,
  );
  return { onSelectPark, onAnnulerPark };
}

describe("APlacerView parked card", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => inventaireVide,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should show a parked card in À placer when a session is parked", async () => {
    renderParcage();
    expect(await screen.findByRole("article", { name: /WR101/ })).toBeInTheDocument();
    expect(screen.getByText(/écriture/i)).toBeInTheDocument();
  });

  it("should call onSelectPark when the parked card is clicked", async () => {
    const { onSelectPark } = renderParcage();
    const carte = await screen.findByRole("article", { name: /WR101/ });
    fireEvent.click(carte);
    expect(onSelectPark).toHaveBeenCalledTimes(1);
  });

  it("should call onAnnulerPark when Annuler is clicked on the parked card", async () => {
    const { onAnnulerPark } = renderParcage();
    await screen.findByRole("article", { name: /WR101/ });
    fireEvent.click(screen.getByRole("button", { name: /^annuler$/i }));
    expect(onAnnulerPark).toHaveBeenCalledTimes(1);
  });

  it("should not POST /deposer when the parked card is shown selected or cancelled", async () => {
    const { onAnnulerPark } = renderParcage({ park: parkState(true) });
    await screen.findByRole("article", { name: /WR101/ });
    fireEvent.click(screen.getByRole("button", { name: /^annuler$/i }));
    await waitFor(() => expect(onAnnulerPark).toHaveBeenCalled());
    const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(urls.some((u) => u.includes("/deposer"))).toBe(false);
  });
});
