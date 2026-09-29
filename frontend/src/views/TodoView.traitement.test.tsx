/**
 * « À traiter » rendu traitable (refonte du 29/09/2026) : sections par
 * nature avec compteurs, « à revoir » repliés par défaut, filtres mémorisés,
 * semaines passées regroupées en fin de section.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { catalogTeacher, emptyPayload, placedRow } from "../test/payloadFixture";
import { TodoView } from "./TodoView";

const payload = emptyPayload({
  weekLabels: ["Semaine A", "Semaine B", "Semaine C"],
  weekDates: ["2026-09-14", "2026-09-21", "2026-09-28"],
  weekRows: [
    { monday: "2026-09-14", label: "Semaine A", blocked: false, weekIndex: 0 },
    { monday: "2026-09-21", label: "Semaine B", blocked: false, weekIndex: 1 },
    { monday: "2026-09-28", label: "Semaine C", blocked: false, weekIndex: 2 },
  ],
  weekStatus: [
    { week: 0, status: "past" },
    { week: 1, status: "current" },
    { week: 2, status: "future" },
  ],
  groupLabels: { g1: "TP A" },
  groupParcours: { g1: "BUT1" },
  teacherLabels: { KBR: "Kyllian Bresson", MRI: "Marine Riguet" },
  seancesNonPlacees: [
    { id: "np1", code: "WR106", nom: "Expression", type: "CM", parcours: "BUT1", groupes: ["Promo"], profs: ["MARINE RIGUET"] },
  ],
  // Journée trouée pour g1 en semaine C (créneaux 0 et 4 : 3 vides).
  rows: [
    placedRow({ id: "a", w: 2, d: 1, s: 0, g: ["g1"], te: ["KBR"] }),
    placedRow({ id: "b", w: 2, d: 1, s: 4, g: ["g1"], te: ["KBR"] }),
  ],
  teachers: [
    catalogTeacher("KBR", "Kyllian Bresson", {
      violations: [
        { week: 2, day: 0, slot: 1, course_code: "WR101", reason: "declared" },
        { week: 0, day: 0, slot: 1, course_code: "WR102", reason: "declared" },
        { week: 1, day: 3, slot: 2, course_code: "WR103", reason: "declared" },
      ],
    }),
    catalogTeacher("MRI", "Marine Riguet", {
      violations: [
        { date: "2026-09-22", course_code: "WR110", reason: "sae_supervision" },
        { date: "2026-09-22", course_code: "WR110", reason: "sae_supervision" },
      ],
    }),
  ],
});

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const u = String(url);
      if (u.startsWith("/controles/doublons/hebdo")) return Promise.resolve({ ok: true, json: async () => ({ dernier: null }) });
      if (u.startsWith("/controles/doublons")) return Promise.resolve({ ok: true, json: async () => ({ doublons: [] }) });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }),
  );
}

function section(nom: string): HTMLElement {
  return screen.getByRole("heading", { name: nom }).closest("section") as HTMLElement;
}

describe("TodoView — liste traitable", () => {
  beforeEach(() => stubFetch());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("groups points by nature with a count per section", async () => {
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Aucun doublon détecté.")).toBeInTheDocument());

    expect(within(section("Séances non placées")).getByLabelText("1 point")).toBeInTheDocument();
    expect(within(section("Indisponibilités enseignant non respectées")).getByLabelText("3 points")).toBeInTheDocument();
    // Deux entrées SAE identiques (même enseignant, même jour, même cours) = une ligne ×2.
    expect(within(section("Encadrement SAE le même jour")).getByLabelText("1 point")).toBeInTheDocument();
  });

  it("keeps the 'à revoir' sections collapsed by default and opens them on click", async () => {
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    const trouees = section("Journées trouées");
    const bascule = within(trouees).getByRole("button", { expanded: false });
    expect(within(trouees).queryByText("BUT1 · TP A")).not.toBeInTheDocument();

    fireEvent.click(bascule);
    expect(within(section("Journées trouées")).getByText("BUT1 · TP A")).toBeInTheDocument();
  });

  it("sorts the current week first, then future weeks, and tucks past weeks away", async () => {
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    const corps = section("Indisponibilités enseignant non respectées");
    const codes = within(corps)
      .getAllByText(/^WR10\d$/)
      .map((el) => el.textContent);
    expect(codes).toEqual(["WR103", "WR101"]);
    expect(within(corps).getByText("cette semaine")).toBeInTheDocument();

    fireEvent.click(within(corps).getByRole("button", { name: /semaines passées \(1\)/ }));
    expect(within(corps).getByText("WR102")).toBeInTheDocument();
  });

  it("filters by teacher and remembers the filters after a reload", async () => {
    const { unmount } = render(<TodoView payload={payload} setRoute={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Enseignant"), { target: { value: "MRI" } });

    // KBR disparaît ; la séance non placée de Marine Riguet (nom en capitales) reste.
    expect(within(section("Indisponibilités enseignant non respectées")).queryByText("WR101")).not.toBeInTheDocument();
    expect(within(section("Séances non placées")).getByText("WR106 — Expression")).toBeInTheDocument();

    unmount();
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getByLabelText("Enseignant")).toHaveValue("MRI");
    fireEvent.click(screen.getByRole("button", { name: "Réinitialiser" }));
    expect(screen.getByLabelText("Enseignant")).toHaveValue("");
  });

  it("opens the place where the point is fixed when a row is clicked", async () => {
    const setRoute = vi.fn();
    render(<TodoView payload={payload} setRoute={setRoute} />);
    fireEvent.click(within(section("Séances non placées")).getByText("WR106 — Expression"));
    expect(setRoute).toHaveBeenCalledWith({ vue: "promo", panel: "aplacer", parcours: "BUT1" });
  });
});
