/**
 * Mode maquette de CreerSeanceModal : type, durée, enseignant (recherche),
 * salle, semaine/jour/créneau, éval si CM. Enregistrement PATCH `/seance`.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreerSeanceModal } from "./CreerSeanceModal";
import type { Placement } from "../types";
import { catalogCourse, emptyPayload } from "../test/payloadFixture";
import { ecrireDernierWeekDay } from "../utils/creerSeancePrefs";

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

  it("should not show a retirer button when creating (no onRetiree, no seanceExistante)", () => {
    render(<CreerSeanceModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /retirer du planning/i })).not.toBeInTheDocument();
  });

  it("should not show a retirer button when onRetiree is not given, even editing an existing session", () => {
    renderMaquette();
    expect(screen.queryByRole("button", { name: /retirer du planning/i })).not.toBeInTheDocument();
  });

  it("should call deposer and onRetiree, not onCree, when retirer is clicked", async () => {
    // Retour utilisateur (03/09/2026) : "enlever un cours de l'EDT pour le
    // mettre dans à placer" — endpoint POST /placements/{id}/deposer déjà
    // là côté serveur, jamais relié à l'interface jusqu'ici.
    const onRetiree = vi.fn();
    const onCree = vi.fn();
    render(
      <CreerSeanceModal
        mode="maquette"
        payload={payload}
        seanceExistante={placement}
        onCree={onCree}
        onCancel={vi.fn()}
        onRetiree={onRetiree}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /retirer du planning/i }));

    await waitFor(() => expect(onRetiree).toHaveBeenCalledWith("maquette-1"));
    const appel = vi.mocked(fetch).mock.calls.find((call) => String(call[0]).includes("/deposer"));
    expect(appel).toBeDefined();
    expect(appel?.[1]?.method).toBe("POST");
    expect(onCree).not.toHaveBeenCalled();
  });
});

/**
 * Simplification du formulaire de création — todo département, retour
 * Kyllian Bresson (22/09/2026) : « création de nouvelle séance à simplifier
 * (rester sur la semaine à saisir, sur le jour à saisir), car pour chaque
 * séance à créer le formulaire est long ».
 */
describe("CreerSeanceModal creation shortcuts", () => {
  const payloadCreation = emptyPayload({
    courses: [catalogCourse("WR101", "Cours existant", { parcours: "BUT1" })],
    groupLabels: { "but1-td-ab": "TD AB" },
    groupParcours: { "but1-td-ab": "BUT1" },
    teacherLabels: { MRI: "Riguet Marine" },
    rooms: [{ id: "h005", label: "H.005", capacity: 30, type: "standard", equipment: [], nSessions: 0 }],
    weekRows: [
      { monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 },
      { monday: "2026-01-12", label: "S2", blocked: false, weekIndex: 1 },
    ],
  });

  const placementCree: Placement = {
    session_id: "creee-1",
    week: 1,
    day: 2,
    slot: 0,
    course_code: "WR101",
    course_name: "Cours existant",
    session_type: "TD",
    group_ids: ["but1-td-ab"],
    teacher_codes: ["MRI"],
    room_id: "h005",
    room_label: "H.005",
    is_eval: false,
    locked: false,
    duration_slots: 1,
  };

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => placementCree,
      }),
    );
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("should pre-fill semaine and jour from the suggestion (week/day currently displayed in Vue Promo)", () => {
    render(
      <CreerSeanceModal
        payload={payloadCreation}
        suggestion={{ week: 1, day: 2 }}
        onCree={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Semaine")).toHaveValue("1");
    expect(screen.getByLabelText("Jour")).toHaveValue("2");
  });

  it("should fall back to the last remembered week/day when no suggestion is given (opened outside Vue Promo)", () => {
    ecrireDernierWeekDay({ week: 1, day: 3 });
    render(<CreerSeanceModal payload={payloadCreation} onCree={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText("Semaine")).toHaveValue("1");
    expect(screen.getByLabelText("Jour")).toHaveValue("3");
  });

  it("should default to the first week/day when there is neither a suggestion nor a remembered value", () => {
    render(<CreerSeanceModal payload={payloadCreation} onCree={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText("Semaine")).toHaveValue("0");
    expect(screen.getByLabelText("Jour")).toHaveValue("0");
  });

  it('should show "Créer et en ajouter une autre" only when creating a brand new session', () => {
    render(<CreerSeanceModal payload={payloadCreation} onCree={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: /créer et en ajouter une autre/i })).toBeInTheDocument();
  });

  it('should hide "Créer et en ajouter une autre" when editing an existing personalised session', () => {
    render(
      <CreerSeanceModal
        payload={payloadCreation}
        seanceExistante={placementCree}
        onCree={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /créer et en ajouter une autre/i })).not.toBeInTheDocument();
  });

  it('should hide "Créer et en ajouter une autre" in maquette mode', () => {
    render(
      <CreerSeanceModal
        payload={payloadCreation}
        mode="maquette"
        seanceExistante={placementCree}
        onCree={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /créer et en ajouter une autre/i })).not.toBeInTheDocument();
  });

  it("should create, keep the modal open, reset the room, and advance the slot when clicking the secondary button", async () => {
    const onCree = vi.fn();
    render(
      <CreerSeanceModal
        payload={payloadCreation}
        suggestion={{ week: 1, day: 2 }}
        onCree={onCree}
        onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText("TD AB"));
    fireEvent.change(screen.getByLabelText("Salle"), { target: { value: "h005" } });
    fireEvent.change(screen.getByRole("combobox", { name: /rechercher un enseignant/i }), {
      target: { value: "Rigu" },
    });
    fireEvent.click(screen.getByRole("option", { name: /riguet marine/i }));

    fireEvent.click(screen.getByRole("button", { name: /créer et en ajouter une autre/i }));

    await waitFor(() => {
      expect(onCree).toHaveBeenCalledWith(placementCree, { garderOuverte: true });
    });

    // La modale reste ouverte (le formulaire de création, pas le message
    // "matière" qui disparaîtrait si elle se refermait).
    expect(screen.getByText("Matière")).toBeInTheDocument();
    // Semaine/jour et enseignant sont conservés, la salle est réinitialisée,
    // le créneau avance d'un cran (9h30 -> 11h, cf. slots.ts).
    expect(screen.getByLabelText("Semaine")).toHaveValue("1");
    expect(screen.getByLabelText("Jour")).toHaveValue("2");
    expect(screen.getByLabelText("Créneau")).toHaveValue("1");
    expect(screen.getByLabelText("Salle")).toHaveValue("");
    // Confirmation courte affichée (jour 2 = Mercredi, cf. slots.ts::DAY_LABELS).
    expect(screen.getByText(/WR101 créée mercredi/i)).toBeInTheDocument();
  });

  it("should not close nor call the default onCree callback when using the secondary button", async () => {
    const onCree = vi.fn();
    render(
      <CreerSeanceModal payload={payloadCreation} suggestion={{ week: 0, day: 0 }} onCree={onCree} onCancel={vi.fn()} />,
    );
    fireEvent.click(screen.getByLabelText("TD AB"));
    fireEvent.click(screen.getByRole("button", { name: /créer et en ajouter une autre/i }));
    await waitFor(() => {
      expect(onCree).toHaveBeenCalledTimes(1);
    });
    expect(onCree).toHaveBeenCalledWith(placementCree, { garderOuverte: true });
  });
});
