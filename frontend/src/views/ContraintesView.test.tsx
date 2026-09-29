/**
 * Contraintes (refonte du 29/09/2026) : échecs d'abord, règles respectées
 * repliées, verdict enseignant distinguant conflit réel et compromis SAE.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { catalogTeacher, emptyPayload } from "../test/payloadFixture";
import { ContraintesView } from "./ContraintesView";

const payload = emptyPayload({
  ruleChecks: [
    { id: "a", label: "Règle cassée", status: "fail", detail: "3 cas" },
    { id: "b", label: "Règle tenue", status: "pass", detail: "0 cas" },
  ],
  teachers: [
    catalogTeacher("KBR", "Kyllian Bresson", {
      hasConstraint: true,
      rawIndisponibilites: "jeudi matin",
      violations: [
        { week: 1, day: 3, slot: 0, course_code: "WR101", reason: "declared" },
        { date: "2026-10-01", course_code: "WR110", reason: "sae_supervision" },
      ],
    }),
    catalogTeacher("MRI", "Marine Riguet"),
  ],
});

describe("ContraintesView", () => {
  afterEach(() => window.localStorage.clear());

  it("lists failing rules first and folds the passing ones", () => {
    render(<ContraintesView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getByText("Règle cassée")).toBeInTheDocument();
    expect(screen.queryByText("Règle tenue")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Afficher la règle respectée/ }));
    expect(screen.getByText("Règle tenue")).toBeInTheDocument();
  });

  it("separates a real conflict from an accepted SAE compromise, and shows the declared text", () => {
    render(<ContraintesView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getByText("1 séance en conflit")).toBeInTheDocument();
    expect(screen.getByText("1 compromis SAE")).toBeInTheDocument();
    expect(screen.getByText("Indisponible : jeudi matin")).toBeInTheDocument();
  });

  it("hides teachers without constraint until asked, and opens a teacher's view on click", () => {
    const setRoute = vi.fn();
    render(<ContraintesView payload={payload} setRoute={setRoute} />);
    expect(screen.queryByText("Marine Riguet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Afficher aussi 1 enseignant sans contrainte/));
    expect(screen.getByText("Marine Riguet")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Kyllian Bresson"));
    expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "KBR" });
  });
});
