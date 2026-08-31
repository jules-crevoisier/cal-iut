/**
 * Contrat fiche salle : id inconnu → introuvable + recherche ;
 * salle connue sans occupation cette semaine → grille vide.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SalleView } from "./SalleView";
import { catalogRoom, emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  rooms: [catalogRoom("B204", { label: "B204", capacity: 28, type: "TD" })],
});

describe("SalleView", () => {
  it("should show introuvable and a way to open search when the room id is unknown", () => {
    render(
      <SalleView
        payload={payload}
        route={testRoute({ vue: "salle", salle: "INCONNUE" })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByText(/introuvable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recherche/i })).toBeInTheDocument();
  });

  it("should still show the occupation grid when the room exists but has no sessions that week", () => {
    render(
      <SalleView
        payload={payload}
        route={testRoute({ vue: "salle", salle: "B204", sem: 0 })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("8h–9h30").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vendredi").length).toBeGreaterThan(0);
  });
});
