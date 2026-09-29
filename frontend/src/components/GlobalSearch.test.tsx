/**
 * Palette Ctrl+K (refonte du 29/09/2026) : groupes par type, navigation
 * clavier qui boucle, surlignage, derniers résultats ouverts proposés.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { catalogRoom, emptyPayload } from "../test/payloadFixture";
import { GlobalSearch } from "./GlobalSearch";

const payload = emptyPayload({
  teacherLabels: { KBR: "Kyllian Bresson", MRI: "Marine Riguet" },
  rooms: [catalogRoom("H201", { label: "H.201" })],
});

function ouvrir(onNavigate = vi.fn(), onClose = vi.fn()) {
  render(<GlobalSearch payload={payload} open onClose={onClose} onNavigate={onNavigate} />);
  return { onNavigate, onClose, champ: screen.getByRole("combobox") };
}

describe("GlobalSearch", () => {
  afterEach(() => window.localStorage.clear());

  it("groups results under a heading per type and highlights the match", () => {
    const { champ } = ouvrir();
    fireEvent.change(champ, { target: { value: "riguet" } });
    expect(screen.getByText("Enseignants")).toBeInTheDocument();
    expect(screen.getByText("Riguet").tagName).toBe("MARK");
  });

  it("moves with the arrows (wrapping around) and opens the chosen result with Enter", () => {
    const { champ, onNavigate } = ouvrir();
    fireEvent.change(champ, { target: { value: "r" } });
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(champ, { key: "ArrowUp" });
    expect(options[options.length - 1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(champ, { key: "ArrowDown" });
    fireEvent.keyDown(champ, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("offers the recently opened results when the field is empty", () => {
    const { champ } = ouvrir();
    fireEvent.change(champ, { target: { value: "H.201" } });
    fireEvent.keyDown(champ, { key: "Enter" });
    cleanup();

    ouvrir();
    expect(screen.getByText("Ouverts récemment")).toBeInTheDocument();
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("H.201");
  });

  it("finds the application screens too", () => {
    const { champ, onNavigate } = ouvrir();
    fireEvent.change(champ, { target: { value: "salles libres" } });
    fireEvent.keyDown(champ, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith({ vue: "salles-libres" });
  });
});
