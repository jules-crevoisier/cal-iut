/**
 * Contrat fiche enseignant : prof inconnu → introuvable + recherche ;
 * enseignant connu sans séance cette semaine → grille vide.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EnseignantView } from "./EnseignantView";
import { catalogTeacher, emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  teacherLabels: { KBR: "Lefèvre Kevin" },
  teachers: [catalogTeacher("KBR", "Lefèvre Kevin")],
});

describe("EnseignantView", () => {
  it("should show introuvable and a way to open search when the teacher code is unknown", () => {
    render(
      <EnseignantView
        payload={payload}
        route={testRoute({ vue: "prof", prof: "ZZZ" })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByText(/introuvable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recherche/i })).toBeInTheDocument();
  });

  it("should still show the week grid when the teacher exists but has no rows that week", () => {
    render(
      <EnseignantView
        payload={payload}
        route={testRoute({ vue: "prof", prof: "KBR", sem: 0 })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("8h–9h30").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vendredi").length).toBeGreaterThan(0);
  });
});
