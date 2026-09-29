/**
 * Contrat fiche salle : id inconnu → introuvable + recherche ;
 * salle connue sans occupation cette semaine → grille vide.
 */
import { fireEvent, render, screen } from "@testing-library/react";
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

  it("should show the room directory, not « introuvable », when the route carries none", () => {
    // Signalement du 22/09/2026 en production : l'entrée « Vue Salle » du menu
    // n'ayant aucune salle en route, la fiche affichait « Salle « ? »
    // introuvable » au lieu d'un écran utilisable. Refonte v2 (29/09/2026) :
    // l'écran utilisable est l'annuaire des salles ; un clic ouvre la fiche.
    const deuxSalles = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101" }), catalogRoom("h018", { label: "H.018" })],
    });
    const setRoute = vi.fn();

    render(<SalleView payload={deuxSalles} route={testRoute({ vue: "salle", salle: "" })} setRoute={setRoute} />);

    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Annuaire des salles" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "H.018" }));
    expect(setRoute).toHaveBeenCalledWith({ vue: "salle", salle: "h018" });
  });
});
