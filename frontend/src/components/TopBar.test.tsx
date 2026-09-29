/**
 * Barre supérieure : la semaine y est partagée par toutes les vues ; la
 * liste des semaines permet de sauter loin ; le compte y vit (Clé API,
 * déconnexion).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopBar } from "./TopBar";
import { emptyPayload } from "../test/payloadFixture";

function barre(extra: Partial<Parameters<typeof TopBar>[0]> = {}) {
  const payload = emptyPayload({
    weekRows: [
      { monday: "2026-09-21", label: "Semaine 5 (21–25 sept. 2026)", blocked: false, weekIndex: 3 },
      { monday: "2026-09-28", label: "Semaine 6 (28 sept.–2 oct. 2026)", blocked: false, weekIndex: 4 },
      { monday: "2026-10-05", label: "Semaine 7 (5–9 oct. 2026)", blocked: false, weekIndex: 5 },
    ],
  });
  const props = {
    vue: "promo" as const,
    payload,
    semaine: 1,
    onSemaine: vi.fn(),
    onOuvrirRecherche: vi.fn(),
    onOuvrirNavigation: vi.fn(),
    email: "jules.crevoisier@univ-reims.fr",
    onCle: vi.fn(),
    onDeconnexion: vi.fn(),
    panne: false,
    ...extra,
  };
  render(<TopBar {...props} />);
  return props;
}

describe("TopBar", () => {
  it("should move the shared week with the arrows", () => {
    const p = barre();
    fireEvent.click(screen.getByRole("button", { name: "Semaine suivante" }));
    expect(p.onSemaine).toHaveBeenCalledWith(2);
    fireEvent.click(screen.getByRole("button", { name: "Semaine précédente" }));
    expect(p.onSemaine).toHaveBeenCalledWith(0);
  });

  it("should jump to any week from the list", () => {
    const p = barre();
    fireEvent.click(screen.getByRole("button", { expanded: false, name: /semaine/i }));
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(p.payload.weekRows.length);
    fireEvent.click(options[0]!);
    expect(p.onSemaine).toHaveBeenCalledWith(0);
  });

  it("should hide the week navigation on screens without a week", () => {
    barre({ vue: "reference" });
    expect(screen.queryByRole("button", { name: "Semaine suivante" })).not.toBeInTheDocument();
  });

  it("should offer the API key and logout in the account menu", () => {
    const p = barre();
    fireEvent.click(screen.getByRole("button", { name: /compte/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /clé api/i }));
    expect(p.onCle).toHaveBeenCalled();
  });

  it("should say when the server cannot be reached", () => {
    barre({ panne: true });
    expect(screen.getByRole("status")).toHaveTextContent("Hors ligne");
  });
});
