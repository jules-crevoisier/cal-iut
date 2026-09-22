/**
 * Marqueur « hors auto » sur la liste des salles (onglet Référence) —
 * retour utilisateur 22/09/2026 : « supprimer la BU du placement
 * automatique des salles car elle est utilisée pour un seul module ».
 * Marqueur TEXTE, pas seulement couleur : une salle hors placement
 * automatique reste choisissable à la main, l'information doit être visible
 * sans dépendre de la couleur.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReferenceView } from "./ReferenceView";
import { catalogRoom, emptyPayload } from "../test/payloadFixture";

describe("ReferenceView — liste des salles", () => {
  it("should show a text marker for a room excluded from automatic placement", () => {
    const payload = emptyPayload({
      rooms: [
        catalogRoom("bu", { label: "BU / A.123", placementAuto: false }),
        catalogRoom("h101", { label: "H.101", placementAuto: true }),
      ],
    });
    render(<ReferenceView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getByText("hors auto")).toBeInTheDocument();
  });

  it("should not show the marker for a room proposed to automatic placement", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("h101", { label: "H.101", placementAuto: true })],
    });
    render(<ReferenceView payload={payload} setRoute={vi.fn()} />);
    expect(screen.queryByText("hors auto")).not.toBeInTheDocument();
  });
});
