/**
 * Contrat fiche cours : id inconnu → introuvable + recherche ;
 * matière connue sans séance cette semaine → grille vide, pas un écran « introuvable ».
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CoursView } from "./CoursView";
import { catalogCourse, emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  courses: [catalogCourse("WR106", "Écriture web")],
  teacherLabels: { KBR: "Lefèvre" },
});

describe("CoursView", () => {
  it("should show introuvable and a way to open search when the course id is unknown", () => {
    render(
      <CoursView
        payload={payload}
        route={testRoute({ vue: "cours", cours: "INCONNU" })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByText(/introuvable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recherche/i })).toBeInTheDocument();
  });

  it("should still show the week grid when the course exists but has no rows that week", () => {
    render(
      <CoursView
        payload={payload}
        route={testRoute({ vue: "cours", cours: "WR106", sem: 0 })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("8h–9h30").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vendredi").length).toBeGreaterThan(0);
  });
});
