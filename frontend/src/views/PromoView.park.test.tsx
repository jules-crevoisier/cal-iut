/**
 * Parcage inter-semaines — Vue Promo.
 * Déposer sur une autre semaine = visuel À placer, puis performMove.
 * Jamais POST /deposer. Pas de move auto même créneau.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { emptyPayload, placedRow, testRoute } from "../test/payloadFixture";
import { performMove } from "../utils/moveSession";
import { PromoView } from "./PromoView";

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const inventaireVide = {
  total_a_placer: 0,
  total_placees: 12,
  manquantes: [],
  par_parcours: {},
  resume: "Tout est placé.",
};

const weekRows = [
  { monday: "2026-08-31", label: "Semaine 2 (31 août–4 sept. 2026)", blocked: false, weekIndex: 0 },
  { monday: "2026-10-12", label: "Semaine 8 (12–16 oct. 2026)", blocked: false, weekIndex: 6 },
  { monday: "2026-12-21", label: "Vacances de Noël", blocked: true, weekIndex: null },
  { monday: "2027-03-08", label: "Semaine 29 (8–12 mars 2027)", blocked: false, weekIndex: 27 },
];

function placementPour(id: string, patch: Partial<Placement> = {}): Placement {
  return {
    session_id: id,
    week: 0,
    day: 0,
    slot: 0,
    course_code: id === "maquette-2" ? "WR102" : "WR101",
    course_name: id === "maquette-2" ? "Atelier" : "Écriture",
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

const payloadPromo = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  groupKind: { "but1-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"] },
  teacherLabels: { MRI: "Riguet Marine" },
  weekLabels: ["S2", "S8", "Vac", "S29"],
  weekDates: ["2026-08-31", "2026-10-12", "2026-12-21", "2027-03-08"],
  weekRows,
  weekStatus: [
    { week: 0, status: "current" },
    { week: 6, status: "future" },
    { week: 27, status: "future" },
  ],
  rows: [
    placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", n: "Écriture", g: ["but1-td-ab"] }),
    placedRow({ id: "maquette-2", w: 0, d: 0, s: 1, c: "WR102", n: "Atelier", g: ["but1-td-ab"] }),
  ],
});

const dataTransfer = { effectAllowed: "move", setData: vi.fn(), getData: vi.fn() };

function urlsDesAppels(): string[] {
  return vi.mocked(fetch).mock.calls.map(([url, init]) => `${(init?.method ?? "GET").toUpperCase()} ${String(url)}`);
}

function aEcritVers(fragment: string): boolean {
  return urlsDesAppels().some((ligne) => {
    const [methode, url] = ligne.split(" ", 2);
    const ecriture = methode !== "GET" && methode !== "HEAD";
    return Boolean(url?.includes(fragment) && (ecriture || fragment.includes("deposer")));
  });
}

async function rendrePromo(extra: Record<string, unknown> = {}) {
  const onPlacementUpdated = vi.fn();
  const onError = vi.fn();
  render(
    <PromoView
      payload={payloadPromo}
      route={testRoute({ vue: "promo", jour: 0, sem: 0, panel: "aplacer" })}
      placements={[placementPour("maquette-1"), placementPour("maquette-2", { slot: 1 })]}
      onPlacementUpdated={onPlacementUpdated}
      onError={onError}
      setRoute={vi.fn()}
      onAPlacerRefresh={vi.fn()}
      {...extra}
    />,
  );
  await waitFor(() => {
    expect(screen.getByText(/séances à placer à la main/i)).toBeInTheDocument();
  });
  return { onPlacementUpdated, onError };
}

function chipDansGrille(code: string): HTMLElement | null {
  return within(screen.getByRole("table")).queryByText(code);
}

function cibleGlisser(code: string): HTMLElement {
  const texte = within(screen.getByRole("table")).getByText(code);
  return (texte.closest("[draggable]") ?? texte.parentElement) as HTMLElement;
}

async function parquerVersSemaine8(code = "WR101"): Promise<void> {
  fireEvent.dragStart(cibleGlisser(code), { dataTransfer });
  fireEvent.drop(screen.getByRole("button", { name: /semaine 8/i }), { dataTransfer });
  await waitFor(() => {
    expect(chipDansGrille(code)).not.toBeInTheDocument();
  });
}

describe("PromoView park-week-move", () => {
  beforeEach(() => {
    vi.mocked(performMove).mockReset();
    vi.mocked(performMove).mockResolvedValue(true);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: RequestInfo | URL) => {
        const u = String(url);
        if (u.includes("/placements/manquantes")) {
          return { ok: true, json: async () => inventaireVide };
        }
        return { ok: true, json: async () => ({}) };
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should not POST validateMove movePlacement deposer placer or manquantes when parking via WeekBar drop", async () => {
    await rendrePromo();
    await parquerVersSemaine8();
    expect(performMove).not.toHaveBeenCalled();
    expect(aEcritVers("/validate")).toBe(false);
    expect(aEcritVers("/deposer")).toBe(false);
    expect(aEcritVers("/placer")).toBe(false);
    expect(urlsDesAppels().some((l) => l.startsWith("POST") && l.includes("manquantes"))).toBe(false);
    expect(urlsDesAppels().some((l) => l.startsWith("PATCH") && l.includes("/placements/"))).toBe(false);
  });

  it("should hide the parked chip on the Promo grid and show a parked card in À placer when dropped on another week", async () => {
    await rendrePromo();
    await parquerVersSemaine8();
    expect(chipDansGrille("WR101")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: /WR101/ })).toBeInTheDocument();
  });

  it("should switch WeekBar to the target display index and keep park unselected when a session is parked", async () => {
    await rendrePromo();
    await parquerVersSemaine8();
    expect(screen.getByRole("heading", { name: /toutes promos.*semaine 8/i })).toBeInTheDocument();
    expect(screen.queryByText(/placement en cours/i)).not.toBeInTheDocument();
  });

  it("should call performMove with displayed solver week day slot and origin when the parked card is picked then a cell is clicked", async () => {
    await rendrePromo();
    await parquerVersSemaine8();
    fireEvent.click(screen.getByRole("article", { name: /WR101/ }));
    const poser = await screen.findAllByText("+ poser ici (conflit possible)");
    fireEvent.click(poser[2]);
    await waitFor(() => {
      expect(performMove).toHaveBeenCalled();
    });
    expect(performMove).toHaveBeenCalledWith(
      "maquette-1",
      { week: 6, day: 0, slot: 2 },
      expect.objectContaining({
        session_id: "maquette-1",
        week: 0,
        day: 0,
        slot: 0,
        room_id: "h005",
        room_label: "H.005",
      }),
      expect.anything(),
      expect.anything(),
    );
  });

  it("should clear the park when performMove returns true", async () => {
    vi.mocked(performMove).mockResolvedValue(true);
    await rendrePromo();
    await parquerVersSemaine8();
    fireEvent.click(screen.getByRole("article", { name: /WR101/ }));
    fireEvent.click((await screen.findAllByText("+ poser ici (conflit possible)"))[2]);
    await waitFor(() => {
      expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    });
  });

  it("should keep the park and hide the origin slot when performMove returns false", async () => {
    vi.mocked(performMove).mockResolvedValue(false);
    await rendrePromo();
    await parquerVersSemaine8();
    fireEvent.click(screen.getByRole("article", { name: /WR101/ }));
    fireEvent.click((await screen.findAllByText("+ poser ici (conflit possible)"))[2]);
    await waitFor(() => {
      expect(performMove).toHaveBeenCalled();
    });
    expect(screen.getByRole("article", { name: /WR101/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /semaine 2 \(/i }));
    expect(chipDansGrille("WR101")).not.toBeInTheDocument();
  });

  it("should restore the origin week day slot with no /deposer when Annuler is clicked on the parked card", async () => {
    await rendrePromo();
    await parquerVersSemaine8();
    fireEvent.click(screen.getByRole("button", { name: /^annuler$/i }));
    await waitFor(() => {
      expect(chipDansGrille("WR101")).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: /toutes promos.*semaine 2/i })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    expect(performMove).not.toHaveBeenCalled();
    expect(aEcritVers("/deposer")).toBe(false);
  });

  it("should not park a locked session and should keep its chip visible", async () => {
    await rendrePromo({
      payload: emptyPayload({
        ...payloadPromo,
        rows: [placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", n: "Écriture", g: ["but1-td-ab"], locked: true })],
      }),
      placements: [placementPour("maquette-1", { locked: true })],
    });
    fireEvent.dragStart(cibleGlisser("WR101"), { dataTransfer });
    fireEvent.drop(screen.getByRole("button", { name: /semaine 8/i }), { dataTransfer });
    expect(chipDansGrille("WR101")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    expect(performMove).not.toHaveBeenCalled();
  });

  it("should navigate only and not park when the session is dropped on the week that already holds it", async () => {
    await rendrePromo();
    fireEvent.dragStart(cibleGlisser("WR101"), { dataTransfer });
    fireEvent.drop(screen.getByRole("button", { name: /semaine 2 \(/i }), { dataTransfer });
    expect(chipDansGrille("WR101")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    expect(performMove).not.toHaveBeenCalled();
    expect(screen.queryByText(/placement en cours/i)).not.toBeInTheDocument();
  });

  it("should not performMove with origin day and slot when onDropWeek parks onto another week", async () => {
    await rendrePromo();
    await parquerVersSemaine8();
    expect(performMove).not.toHaveBeenCalled();
    expect(performMove).not.toHaveBeenCalledWith(
      "maquette-1",
      { week: 6, day: 0, slot: 0 },
      expect.anything(),
      expect.anything(),
      expect.anything(),
    );
  });

  it("should replace the first parked session when a second one is parked without POST", async () => {
    await rendrePromo();
    await parquerVersSemaine8("WR101");
    fireEvent.click(screen.getByRole("button", { name: /semaine 2 \(/i }));
    await waitFor(() => {
      expect(chipDansGrille("WR102")).toBeInTheDocument();
    });
    await parquerVersSemaine8("WR102");
    fireEvent.click(screen.getByRole("button", { name: /semaine 2 \(/i }));
    await waitFor(() => {
      expect(chipDansGrille("WR101")).toBeInTheDocument();
    });
    expect(chipDansGrille("WR102")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: /WR102/ })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    expect(performMove).not.toHaveBeenCalled();
    expect(aEcritVers("/deposer")).toBe(false);
  });

  it("should not park and should hide À placer write UI when PromoView is readOnly", async () => {
    render(
      <PromoView
        payload={payloadPromo}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        readOnly
        placements={[placementPour("maquette-1")]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /séances à placer/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/séances à placer à la main/i)).not.toBeInTheDocument();
    fireEvent.dragStart(cibleGlisser("WR101"), { dataTransfer });
    fireEvent.drop(screen.getByRole("button", { name: /semaine 8/i }), { dataTransfer });
    expect(chipDansGrille("WR101")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    expect(performMove).not.toHaveBeenCalled();
  });
});
