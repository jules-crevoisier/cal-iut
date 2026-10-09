/**
 * Création d'un évènement hors maquette avec horaire libre — retour Jules
 * 23/09/2026 (Kyllian Bresson : « m'ajouter une séance évènement [...] à
 * 13h15 jusqu'à 14h [...] sans mettre d'enseignant »).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreerEvenementModal } from "./CreerEvenementModal";
import type { Placement } from "../types";
import { emptyPayload } from "../test/payloadFixture";

const placement: Placement = {
  session_id: "evenement-1",
  week: 0,
  day: 3,
  slot: 3,
  course_code: "PRESENTATION-PAC",
  course_name: "Présentation PAC",
  session_type: "CM",
  group_ids: ["but1-promo"],
  teacher_codes: [],
  room_id: "h018",
  room_label: "H.018",
  is_eval: false,
  locked: false,
  duration_slots: 1,
  hor: "13h15–14h",
};

const payload = emptyPayload({
  groupLabels: { "but1-promo": "Promo BUT1" },
  groupParcours: { "but1-promo": "BUT1" },
  rooms: [{ id: "h018", label: "H.018", capacity: 200, type: "amphi", equipment: [], nSessions: 0 }],
  weekRows: [{ monday: "2026-09-21", label: "Semaine 5", blocked: false, weekIndex: 10 }],
});

function corpsDernierAppel(): Record<string, unknown> {
  const appels = vi.mocked(fetch).mock.calls.filter((call) => String(call[0]).includes("/placements/evenements"));
  const init = appels[appels.length - 1]?.[1];
  const corps = typeof init?.body === "string" ? init.body : "";
  return JSON.parse(corps) as Record<string, unknown>;
}

describe("CreerEvenementModal", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => placement }),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should sort the groups by parcours so that two « TD AB » can be told apart", () => {
    const deuxPromos = emptyPayload({
      ...payload,
      groupLabels: { "but1-promo": "Promo BUT1", "but1-td-ab": "TD AB", "but2-td-ab": "TD AB" },
      groupParcours: { "but1-promo": "BUT1", "but1-td-ab": "BUT1", "but2-td-ab": "BUT2-DEV-FI" },
      groupKind: { "but1-promo": "promo", "but1-td-ab": "td", "but2-td-ab": "td" },
    });
    render(<CreerEvenementModal payload={deuxPromos} onCree={vi.fn()} onCancel={vi.fn()} />);
    const but2 = screen.getByRole("group", { name: "BUT2-DEV-FI" });
    expect(within(but2).getByLabelText("TD AB")).not.toBeChecked();
    const but1 = screen.getByRole("group", { name: "BUT1" });
    expect(within(but1).getAllByRole("checkbox").map((c) => c.parentElement?.textContent)).toEqual([
      "Promo BUT1",
      "TD AB",
    ]);
  });

  it("should show the hint about the midday break and the optional time fields", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText(/heure de début/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/heure de fin/i)).toBeInTheDocument();
    expect(
      screen.getByText(/laisser vide pour utiliser le créneau.*pause méridienne/i),
    ).toBeInTheDocument();
  });

  it("should refuse to submit without a libelle", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));
    expect(screen.getByText(/donnez un libellé/i)).toBeInTheDocument();
  });

  it("should refuse to submit without at least one group", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/présentation pac/i), { target: { value: "Réunion" } });
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));
    expect(screen.getByText(/cochez au moins un groupe/i)).toBeInTheDocument();
  });

  function remplirFormulaireMinimal() {
    fireEvent.change(screen.getByPlaceholderText(/présentation pac/i), { target: { value: "Présentation PAC" } });
    fireEvent.click(screen.getByLabelText("Promo BUT1"));
  }

  it("should refuse heure_debut without heure_fin", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    remplirFormulaireMinimal();
    fireEvent.change(screen.getByLabelText(/heure de début/i), { target: { value: "13:15" } });
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));
    expect(screen.getByText(/vont ensemble/i)).toBeInTheDocument();
  });

  it("should refuse heure_fin before heure_debut", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    remplirFormulaireMinimal();
    fireEvent.change(screen.getByLabelText(/heure de début/i), { target: { value: "14:00" } });
    fireEvent.change(screen.getByLabelText(/heure de fin/i), { target: { value: "13:15" } });
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));
    expect(screen.getByText(/doit être après/i)).toBeInTheDocument();
  });

  it("should POST /placements/evenements with heure_debut/heure_fin when provided", async () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    remplirFormulaireMinimal();
    fireEvent.change(screen.getByLabelText(/heure de début/i), { target: { value: "13:15" } });
    fireEvent.change(screen.getByLabelText(/heure de fin/i), { target: { value: "14:00" } });
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));

    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]).includes("/placements/evenements"))).toBe(true);
    });
    const corps = corpsDernierAppel();
    expect(corps.libelle).toBe("Présentation PAC");
    expect(corps.group_ids).toEqual(["but1-promo"]);
    expect(corps.heure_debut).toBe("13:15");
    expect(corps.heure_fin).toBe("14:00");
  });

  it("should omit heure_debut/heure_fin from the payload when left empty", async () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    remplirFormulaireMinimal();
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));

    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]).includes("/placements/evenements"))).toBe(true);
    });
    const corps = corpsDernierAppel();
    expect(corps.heure_debut).toBeUndefined();
    expect(corps.heure_fin).toBeUndefined();
  });

  it("should call onCree with the resulting placement on success", async () => {
    const onCree = vi.fn();
    render(<CreerEvenementModal payload={payload} onCree={onCree} onCancel={vi.fn()} />);
    remplirFormulaireMinimal();
    fireEvent.click(screen.getByRole("button", { name: /créer et placer/i }));
    await waitFor(() => expect(onCree).toHaveBeenCalledWith(placement));
  });

  it("should fill 12h30–14h when « Pause méridienne » is picked as the slot", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Créneau"), { target: { value: "midi" } });
    expect(screen.getByLabelText(/heure de début/i)).toHaveValue("12:30");
    expect(screen.getByLabelText(/heure de fin/i)).toHaveValue("14:00");
  });

  it("should select « Pause méridienne » by itself for a 13h30 start", () => {
    render(<CreerEvenementModal payload={payload} onCree={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/heure de début/i), { target: { value: "13:30" } });
    expect(screen.getByLabelText("Créneau")).toHaveValue("midi");
  });

  describe("modification d'un évènement existant (tâche 16)", () => {
    const row = {
      id: "evenement-1", w: 10, d: 3, s: 3, c: "PRESENTATION-PAC", n: "Présentation PAC", t: "CM",
      g: ["but1-promo"], te: [], r: "H.018", ev: false, dur: 1, locked: false, custom: true,
      hor: "13h15–14h", midi: true, evt: { sem: "S1", note: "Amphi plein", hd: "13:15", hf: "14:00" },
    };
    const existant = { placement: { ...placement, week: 10 }, row };

    function corpsPatch(): Record<string, unknown> {
      const appel = vi.mocked(fetch).mock.calls.find((c) => String(c[0]).includes("/placements/personnalisees/"));
      return JSON.parse(String(appel?.[1]?.body ?? "{}")) as Record<string, unknown>;
    }

    it("should open pre-filled with the event's own fields", () => {
      render(<CreerEvenementModal payload={payload} evenementExistant={existant} onCree={vi.fn()} onCancel={vi.fn()} />);
      expect(screen.getByRole("heading", { name: "Modifier l'évènement" })).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/présentation pac/i)).toHaveValue("Présentation PAC");
      expect(screen.getByLabelText("Promo BUT1")).toBeChecked();
      expect(screen.getByLabelText(/note/i)).toHaveValue("Amphi plein");
      expect(screen.getByLabelText(/heure de début/i)).toHaveValue("13:15");
      expect(screen.getByLabelText("Créneau")).toHaveValue("midi");
    });

    it("should PATCH the event instead of creating a new one", async () => {
      const onCree = vi.fn();
      render(<CreerEvenementModal payload={payload} evenementExistant={existant} onCree={onCree} onCancel={vi.fn()} />);
      fireEvent.change(screen.getByPlaceholderText(/présentation pac/i), { target: { value: "Réunion PAC" } });
      fireEvent.change(screen.getByLabelText(/heure de début/i), { target: { value: "13:30" } });
      fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

      await waitFor(() => expect(onCree).toHaveBeenCalled());
      const corps = corpsPatch();
      expect(corps.libelle).toBe("Réunion PAC");
      expect(corps.heure_debut).toBe("13:30");
      expect(corps.heure_fin).toBe("14:00");
      expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]).endsWith("/placements/evenements"))).toBe(false);
    });

    it("should ask the server to drop the free time when a regular slot is chosen", async () => {
      const onCree = vi.fn();
      render(<CreerEvenementModal payload={payload} evenementExistant={existant} onCree={onCree} onCancel={vi.fn()} />);
      fireEvent.change(screen.getByLabelText("Créneau"), { target: { value: "1" } });
      fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

      await waitFor(() => expect(onCree).toHaveBeenCalled());
      const corps = corpsPatch();
      expect(corps.sans_horaire).toBe(true);
      expect(corps.slot).toBe(1);
      expect(corps.heure_debut).toBeUndefined();
    });
  });
});
