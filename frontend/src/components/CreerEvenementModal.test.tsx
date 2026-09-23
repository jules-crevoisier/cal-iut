/**
 * Création d'un évènement hors maquette avec horaire libre — retour Jules
 * 23/09/2026 (Kyllian Bresson : « m'ajouter une séance évènement [...] à
 * 13h15 jusqu'à 14h [...] sans mettre d'enseignant »).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});
