/**
 * Parcage dans la modale parcours : zone À placer, nav semaines,
 * clic case → performMove, Annuler / Fermer restaure, jamais /deposer.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { emptyPayload, placedRow } from "../test/payloadFixture";
import { performMove } from "../utils/moveSession";
import { ParcoursWeekModal } from "./ParcoursWeekModal";

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const weekRows = [
  { monday: "2026-08-31", label: "Semaine 2 (31 août–4 sept. 2026)", blocked: false, weekIndex: 0 },
  { monday: "2026-10-12", label: "Semaine 8 (12–16 oct. 2026)", blocked: false, weekIndex: 6 },
];

const payload = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  groupKind: { "but1-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"] },
  teacherLabels: { MRI: "Riguet Marine" },
  weekLabels: ["S2", "S8"],
  weekDates: ["2026-08-31", "2026-10-12"],
  weekRows,
  weekStatus: [
    { week: 0, status: "current" },
    { week: 6, status: "future" },
  ],
  rows: [placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", n: "Écriture", g: ["but1-td-ab"], te: ["MRI"], r: "H.005" })],
});

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

const dataTransfer = { effectAllowed: "move", setData: vi.fn(), getData: vi.fn() };

function urlsDesAppels(): string[] {
  return vi.mocked(fetch).mock.calls.map(([url, init]) => `${(init?.method ?? "GET").toUpperCase()} ${String(url)}`);
}

function rendreModale(extra: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onPlacementUpdated = vi.fn();
  const onError = vi.fn();
  render(
    <ParcoursWeekModal
      payload={payload}
      parcours="BUT1"
      weekIndex={0}
      placements={[origin]}
      onClose={onClose}
      onPlacementUpdated={onPlacementUpdated}
      onError={onError}
      {...extra}
    />,
  );
  return { onClose, onPlacementUpdated, onError };
}

function chipGrille(): HTMLElement | null {
  const dialog = screen.getByRole("dialog");
  const table = within(dialog).queryByRole("table");
  return table ? within(table).queryByText("WR101") : null;
}

async function parquerDepuisLaGrille(): Promise<void> {
  const chip = screen.getByRole("button", { name: /WR101/ });
  fireEvent.dragStart(chip, { dataTransfer });
  fireEvent.drop(screen.getByRole("region", { name: /à placer/i }), { dataTransfer });
  await waitFor(() => {
    expect(chipGrille()).not.toBeInTheDocument();
  });
}

describe("ParcoursWeekModal park-week-move", () => {
  beforeEach(() => {
    vi.mocked(performMove).mockReset();
    vi.mocked(performMove).mockResolvedValue(true);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({}),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should park on the modal À placer zone without POST when a session is dropped there", async () => {
    rendreModale();
    await parquerDepuisLaGrille();
    expect(performMove).not.toHaveBeenCalled();
    expect(urlsDesAppels().some((l) => l.includes("/deposer"))).toBe(false);
    expect(urlsDesAppels().some((l) => l.includes("/validate"))).toBe(false);
    expect(urlsDesAppels().some((l) => l.includes("/placer"))).toBe(false);
    expect(screen.getByRole("article", { name: /WR101/ })).toBeInTheDocument();
  });

  it("should hide the parked id in the grid and performMove to the displayed week day slot after pick then cell click", async () => {
    rendreModale();
    await parquerDepuisLaGrille();
    expect(chipGrille()).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /semaine suivante/i }));
    fireEvent.click(screen.getByRole("article", { name: /WR101/ }));
    fireEvent.click(screen.getByRole("button", { name: "Mardi 9h30–11h" }));
    await waitFor(() => {
      expect(performMove).toHaveBeenCalled();
    });
    expect(performMove).toHaveBeenCalledWith(
      "maquette-1",
      { week: 6, day: 1, slot: 1 },
      expect.objectContaining({
        session_id: "maquette-1",
        week: 0,
        day: 0,
        slot: 0,
      }),
      expect.anything(),
      expect.anything(),
    );
  });

  it("should restore the origin and skip /deposer when Annuler is clicked while parked", async () => {
    rendreModale();
    await parquerDepuisLaGrille();
    fireEvent.click(screen.getByRole("button", { name: /^annuler$/i }));
    await waitFor(() => {
      expect(chipGrille()).toBeInTheDocument();
    });
    expect(screen.queryByRole("article", { name: /WR101/ })).not.toBeInTheDocument();
    expect(performMove).not.toHaveBeenCalled();
    expect(urlsDesAppels().some((l) => l.includes("/deposer"))).toBe(false);
  });

  it("should restore the origin and skip /deposer when Fermer is clicked while parked", async () => {
    const { onClose } = rendreModale();
    await parquerDepuisLaGrille();
    fireEvent.click(screen.getByRole("button", { name: /^fermer$/i }));
    expect(onClose).toHaveBeenCalled();
    expect(performMove).not.toHaveBeenCalled();
    expect(urlsDesAppels().some((l) => l.includes("/deposer"))).toBe(false);
  });
});
