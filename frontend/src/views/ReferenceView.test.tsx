/**
 * Marqueur « hors auto » sur la liste des salles (onglet Référence) —
 * retour utilisateur 22/09/2026 : « supprimer la BU du placement
 * automatique des salles car elle est utilisée pour un seul module ».
 * Marqueur TEXTE, pas seulement couleur : une salle hors placement
 * automatique reste choisissable à la main, l'information doit être visible
 * sans dépendre de la couleur.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReferenceView } from "./ReferenceView";
import { catalogRoom, emptyPayload } from "../test/payloadFixture";

afterEach(() => window.localStorage.clear());

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

/**
 * Lien public « Salles libres » (retour utilisateur 25/09/2026, Jules,
 * dicté : « on met ça en lien public, comme ça les gens peuvent consulter »)
 * — annuaire « Liens & partage », même mécanisme que le lien Vue Promo déjà
 * présent (`mode=salles` au lieu de `mode=promo`).
 */
describe("ReferenceView — lien public Salles libres", () => {
  it("should offer a public, read-only link to the room occupancy table in Liens & partage", () => {
    const payload = emptyPayload({ rooms: [catalogRoom("h101", { label: "H.101" })] });
    render(<ReferenceView payload={payload} setRoute={vi.fn()} />);

    fireEvent.click(screen.getByRole("tab", { name: /liens & partage/i }));

    const bloc = screen.getByText(/occupation des salles — accès public/i).closest("div.ref-lien-public");
    if (!bloc) throw new Error("bloc lien salles introuvable");
    const lien = within(bloc as HTMLElement).getByRole("link", { name: /ouvrir dans un nouvel onglet/i });
    expect(lien).toHaveAttribute("href", expect.stringContaining("vue=salles-libres"));
    expect(lien).toHaveAttribute("href", expect.stringContaining("mode=salles"));
  });
});

/** Refonte du 29/09/2026 : onglets mémorisés, filtre et tri des tableaux. */
describe("ReferenceView — onglets, filtres et tri", () => {
  const payload = emptyPayload({
    rooms: [
      catalogRoom("h101", { label: "H.101", capacity: 35, type: "tp_standard" }),
      catalogRoom("a018", { label: "A.018", capacity: 150, type: "amphi" }),
      catalogRoom("h005", { label: "H.005", capacity: 15, type: "tp_standard" }),
    ],
  });

  it("should reopen the last tab used", () => {
    const { unmount } = render(<ReferenceView payload={payload} setRoute={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /calendrier/i }));
    unmount();
    render(<ReferenceView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getByRole("tab", { name: /calendrier/i })).toHaveAttribute("aria-selected", "true");
  });

  it("should show readable room types and filter rooms by text", () => {
    render(<ReferenceView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getAllByRole("cell", { name: "TP standard" })).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Filtrer les salles"), { target: { value: "a.0" } });
    expect(screen.getByText("A.018")).toBeInTheDocument();
    expect(screen.queryByText("H.101")).not.toBeInTheDocument();
  });

  it("should sort rooms by capacity when the column header is clicked twice", () => {
    render(<ReferenceView payload={payload} setRoute={vi.fn()} />);
    const bouton = screen.getByRole("button", { name: /places/i });
    fireEvent.click(bouton);
    fireEvent.click(bouton);
    const noms = screen.getAllByTitle("Ouvrir la Vue Salle").map((b) => b.textContent);
    expect(noms).toEqual(["A.018", "H.101", "H.005"]);
    expect(bouton.closest("th")).toHaveAttribute("aria-sort", "descending");
  });
});
