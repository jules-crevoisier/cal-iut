/**
 * Mode maquette de CreerSeanceModal : type, durée, enseignant (recherche),
 * salle, semaine/jour/créneau, éval si CM. Enregistrement PATCH `/seance`.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreerSeanceModal } from "./CreerSeanceModal";
import type { Placement } from "../types";
import { catalogCourse, emptyPayload } from "../test/payloadFixture";

const placement: Placement = {
  session_id: "maquette-1",
  week: 0,
  day: 0,
  slot: 0,
  course_code: "WR101",
  course_name: "Cours existant",
  session_type: "TD",
  group_ids: ["but1-td-ab"],
  teacher_codes: ["MRI"],
  room_id: null,
  room_label: null,
  is_eval: false,
  locked: false,
  duration_slots: 1,
};

const payload = emptyPayload({
  courses: [catalogCourse("WR101", "Cours existant", { parcours: "BUT1" })],
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  teacherLabels: { MRI: "Riguet Marine", JSA: "Sanson Jean" },
  rooms: [{ id: "h005", label: "H.005", capacity: 30, type: "standard", equipment: [], nSessions: 0 }],
  weekRows: [
    { monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 },
    { monday: "2026-01-12", label: "S2", blocked: false, weekIndex: 1 },
  ],
});

function renderMaquette(seance: Placement = placement) {
  return render(
    <CreerSeanceModal
      {...{ mode: "maquette" }}
      payload={payload}
      seanceExistante={seance}
      onCree={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
}

function dernierCorpsPatch(): Record<string, unknown> {
  const appels = vi.mocked(fetch).mock.calls.filter((call) => String(call[0]).includes("/seance"));
  const init = appels[appels.length - 1]?.[1];
  const corps = typeof init?.body === "string" ? init.body : "";
  return JSON.parse(corps) as Record<string, unknown>;
}

describe("CreerSeanceModal maquette mode", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => placement,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should show salle week and teacher search while hiding matiere groupes note", () => {
    renderMaquette();
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Durée")).toBeInTheDocument();
    expect(screen.getByText("Enseignant(s)")).toBeInTheDocument();
    expect(screen.getByLabelText("Semaine")).toBeInTheDocument();
    expect(screen.getByLabelText("Jour")).toBeInTheDocument();
    expect(screen.getByLabelText("Créneau")).toBeInTheDocument();
    expect(screen.getByLabelText("Salle")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /rechercher un enseignant/i })).toBeInTheDocument();
    expect(screen.queryByText("Matière")).not.toBeInTheDocument();
    expect(screen.queryByText("Groupe(s)")).not.toBeInTheDocument();
    expect(screen.queryByText("Évaluation")).not.toBeInTheDocument();
    expect(screen.queryByText(/note \(optionnel\)/i)).not.toBeInTheDocument();
  });

  it("should show evaluation checkbox when the maquette session is a CM", () => {
    renderMaquette({ ...placement, session_type: "CM" });
    expect(screen.getByLabelText("Évaluation")).toBeInTheDocument();
  });

  it("should call patch seance not personnalisees when maquette save succeeds", async () => {
    renderMaquette();
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0);
    });
    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
    const inits = vi.mocked(fetch).mock.calls.map((call) => call[1]);
    expect(urls.some((url) => url.includes("/placements/maquette-1/seance"))).toBe(true);
    expect(inits.some((init) => init && String(init.method).toUpperCase() === "PATCH")).toBe(true);
    expect(urls.some((url) => url.includes("/placements/personnalisees"))).toBe(false);
  });

  it("should send the chosen week in the seance patch body", async () => {
    renderMaquette();
    fireEvent.change(screen.getByLabelText("Semaine"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0);
    });
    expect(dernierCorpsPatch().week).toBe(1);
  });

  it("should send the chosen room in the seance patch body", async () => {
    renderMaquette();
    fireEvent.change(screen.getByLabelText("Salle"), { target: { value: "h005" } });
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0);
    });
    expect(dernierCorpsPatch().room_id).toBe("h005");
  });

  it("should add a searched teacher to the seance patch body", async () => {
    renderMaquette();
    fireEvent.change(screen.getByRole("combobox", { name: /rechercher un enseignant/i }), {
      target: { value: "Sans" },
    });
    fireEvent.click(screen.getByRole("option", { name: /sanson jean/i }));
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0);
    });
    expect(dernierCorpsPatch().teacher_codes).toEqual(["MRI", "JSA"]);
  });

  it("should send is_eval when a CM evaluation checkbox is checked", async () => {
    renderMaquette({ ...placement, session_type: "CM" });
    fireEvent.click(screen.getByLabelText("Évaluation"));
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0);
    });
    expect(dernierCorpsPatch().is_eval).toBe(true);
  });

  it("should keep the full create form when mode is not maquette", () => {
    render(
      <CreerSeanceModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText("Matière")).toBeInTheDocument();
    expect(screen.getByText("Groupe(s)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /créer et placer/i })).toBeInTheDocument();
  });
});
