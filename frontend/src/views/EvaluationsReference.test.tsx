import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { ContexteDroits } from "../contexts/Droits";
import { EvaluationsReference } from "./EvaluationsReference";

const base = {
  cours_nom: "Anglais",
  parcours: "BUT1",
  semestre: "S1",
  groupes_libelles: ["Promo BUT1"],
  salle_libelle: "A.018 (Évaluation)",
  placee: true,
  jour_nom: "lundi",
  debut: "11:00",
  fin: "12:30",
};

afterEach(() => vi.restoreAllMocks());

describe("EvaluationsReference", () => {
  it("should list Eval, last CM to confirm and unplaced ones with their teacher", async () => {
    vi.spyOn(client, "fetchEvaluations").mockResolvedValue({
      total: 3,
      nb_eval: 1,
      nb_a_confirmer: 1,
      nb_non_placees: 1,
      evaluations: [
        { ...base, id: "a", cours_code: "WR101", date: "2026-10-19", enseignants: ["TPA"], enseignants_noms: ["Thomas Pavie"], evaluation: true, dernier_cm: true, statut: "eval" },
        { ...base, id: "b", cours_code: "WR104", date: "2026-09-16", enseignants: ["MMA"], enseignants_noms: ["Martial Martin"], evaluation: false, dernier_cm: true, statut: "a_confirmer" },
        { ...base, id: "c", cours_code: "WS302D", date: null, placee: false, debut: "", fin: "", jour_nom: "", enseignants: ["ARA"], enseignants_noms: ["Anthony Rageul"], evaluation: true, dernier_cm: false, statut: "non_placee" },
      ],
    });
    render(<EvaluationsReference />);
    expect(await screen.findByText("WR101")).toBeInTheDocument();
    expect(screen.getByText("Thomas Pavie")).toBeInTheDocument();
    expect(screen.getByText("19/10/2026", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("À confirmer", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Non placée", { selector: "span" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Statut"), { target: { value: "a_confirmer" } });
    await waitFor(() => expect(screen.queryByText("WR101")).not.toBeInTheDocument());
    expect(screen.getByText("WR104")).toBeInTheDocument();
  });

  it("should let an editor confirm a last CM, then undo it", async () => {
    const ligne = { ...base, id: "b", cours_code: "WR104", date: "2026-09-16", enseignants: ["MMA"], enseignants_noms: ["Martial Martin"], evaluation: false, dernier_cm: true };
    const reponse = (statut: "a_confirmer" | "confirmee") => ({
      total: 1,
      nb_eval: 0,
      nb_a_confirmer: statut === "a_confirmer" ? 1 : 0,
      nb_non_placees: 0,
      nb_confirmees: statut === "confirmee" ? 1 : 0,
      evaluations: [{ ...ligne, statut, validation: statut === "confirmee" ? ("eval" as const) : null }],
    });
    const fetch = vi.spyOn(client, "fetchEvaluations").mockResolvedValue(reponse("a_confirmer"));
    const valider = vi.spyOn(client, "validerEvaluation").mockResolvedValue({ session_id: "b", decision: "eval" });
    const apres = vi.fn();
    render(
      <ContexteDroits.Provider value={{ role: "edit", revision: 1, apresEnregistrement: apres }}>
        <EvaluationsReference />
      </ContexteDroits.Provider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "C'est une Éval" }));
    fetch.mockResolvedValue(reponse("confirmee"));
    await waitFor(() => expect(valider).toHaveBeenCalledWith("b", "eval"));
    fireEvent.click(await screen.findByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(valider).toHaveBeenCalledWith("b", null));
    expect(apres).toHaveBeenCalled();
  });

  it("should not offer the answer buttons to a read-only account", async () => {
    vi.spyOn(client, "fetchEvaluations").mockResolvedValue({
      total: 1,
      nb_eval: 0,
      nb_a_confirmer: 1,
      nb_non_placees: 0,
      evaluations: [
        { ...base, id: "b", cours_code: "WR104", date: "2026-09-16", enseignants: ["MMA"], enseignants_noms: ["Martial Martin"], evaluation: false, dernier_cm: true, statut: "a_confirmer" },
      ],
    });
    render(<EvaluationsReference />);
    expect(await screen.findByText("WR104")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "C'est une Éval" })).not.toBeInTheDocument();
  });
});
