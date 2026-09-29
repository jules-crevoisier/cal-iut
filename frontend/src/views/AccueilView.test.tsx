/**
 * Accueil : les chiffres de la semaine affichée, et chaque case mène à
 * l'écran où l'on agit.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccueilView } from "./AccueilView";
import { ContexteSemaine } from "../contexts/SemaineGlobale";
import { emptyPayload, placedRow } from "../test/payloadFixture";

const payload = emptyPayload({
  groupParcours: { "but3-dev-fc-td-ef": "BUT3-DEV-FC" },
  weekRows: [
    { monday: "2026-10-05", label: "Semaine 7 (5–9 oct. 2026)", blocked: false, weekIndex: 5 },
    { monday: "2026-10-12", label: "Semaine 8 (12–16 oct. 2026)", blocked: false, weekIndex: 6 },
  ],
  weekStatus: [
    { week: 5, status: "current" },
    { week: 6, status: "future" },
  ],
  rows: [
    placedRow({ id: "a", w: 6, d: 1, s: 1, g: ["but3-dev-fc-td-ef"] }),
    placedRow({ id: "b", w: 6, d: 1, s: 2, g: ["but3-dev-fc-td-ef"] }),
    placedRow({ id: "c", w: 6, d: 3, s: 3, g: ["but3-dev-fc-td-ef"] }),
  ],
});

function monter(setRoute = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (String(url).includes("doublons") ? { doublons: [] } : []),
    })),
  );
  render(
    <ContexteSemaine.Provider value={{ index: 1, setIndex: vi.fn() }}>
      <AccueilView payload={payload} setRoute={setRoute} estAdmin peutModifier />
    </ContexteSemaine.Provider>,
  );
  return setRoute;
}

describe("AccueilView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("should count the sessions of the shared week", async () => {
    monter();
    const tuile = screen.getByRole("button", { name: /^séances cette semaine/i });
    expect(tuile).toHaveTextContent("3");
    await waitFor(() => expect(screen.getByRole("button", { name: /tâches ouvertes/i })).toHaveTextContent("0"));
  });

  it("should open the promo day from the load heatmap", () => {
    const setRoute = monter();
    fireEvent.click(screen.getByTitle(/BUT3-DEV-FC, Mar\. : 2 créneaux/));
    expect(setRoute).toHaveBeenCalledWith({ vue: "promo", sem: 6, jour: 1, parcours: "BUT3-DEV-FC" });
  });
});
