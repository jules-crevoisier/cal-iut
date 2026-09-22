/**
 * Contrat Vue « Salles libres » (todo département 22/09/2026, Kyllian
 * Bresson : « Planning des salles disponibles »). Rouge d'abord : le
 * composant n'existe pas encore.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SallesLibresView } from "./SallesLibresView";
import { catalogRoom, emptyPayload, placedRow, testRoute } from "../test/payloadFixture";

const WEEK_ROWS_OUVERTE = [{ monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 }];

// La grille (≥768px) reste dans le DOM en test (jsdom ne simule pas les media
// queries que `useNarrowScreen` interroge, cf. SalleView/PromoView — même
// contrainte). Les assertions sur la LISTE (contenu mobile-first) sont donc
// systématiquement scopées à `.salleslibres-liste`, jamais à `screen` entier,
// pour ne pas confondre une salle listée et la même salle en tête de grille.
function liste(container: HTMLElement) {
  const el = container.querySelector(".salleslibres-liste");
  if (!el) throw new Error("liste des salles libres introuvable");
  return within(el as HTMLElement);
}

describe("SallesLibresView", () => {
  it("should list the free rooms for the preselected slot with a status count", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [
        catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" }),
        catalogRoom("h201", { label: "H.201", capacity: 40, type: "standard" }),
      ],
      rows: [],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={vi.fn()} />,
    );

    expect(liste(container).getByText("H.101")).toBeInTheDocument();
    expect(liste(container).getByText("H.201")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/2 salle/i);
  });

  it("should move a room out of the free list once its slot is selected as occupied", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" })],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 1, dur: 1, r: "H.101", c: "WR108", t: "TD" })],
    });

    const { container } = render(
      <SallesLibresView
        payload={payload}
        route={testRoute({ vue: "salles-libres", jour: 0 })}
        setRoute={vi.fn()}
      />,
    );

    // Créneau 0 par défaut, la salle y est libre (la séance occupe le 1).
    expect(liste(container).getByText("H.101")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /9h30–11h/i }));

    expect(container.querySelector(".salleslibres-liste")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/occupée/i);
  });

  it("should filter free rooms by minimum capacity", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [
        catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" }),
        catalogRoom("h201", { label: "H.201", capacity: 40, type: "standard" }),
      ],
      rows: [],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={vi.fn()} />,
    );

    fireEvent.change(screen.getByLabelText(/capacité minimum/i), { target: { value: "30" } });

    expect(liste(container).queryByText("H.101")).not.toBeInTheDocument();
    expect(liste(container).getByText("H.201")).toBeInTheDocument();
  });

  it("should exclude a room outside automatic placement by default, then show it once included", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [catalogRoom("bu", { label: "BU / A.123", capacity: 12, type: "reserve", placementAuto: false })],
      rows: [],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={vi.fn()} />,
    );

    expect(container.querySelector(".salleslibres-liste")).toBeNull();

    fireEvent.click(screen.getByLabelText(/hors placement automatique/i));

    expect(liste(container).getByText("BU / A.123")).toBeInTheDocument();
  });

  it("should show an explicit message for a blocked week instead of the room list", () => {
    const payload = emptyPayload({
      weekRows: [{ monday: "2026-01-05", label: "Vacances de Noël", blocked: true, weekIndex: null }],
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={vi.fn()} />,
    );

    expect(screen.getByText(/bloquée/i)).toBeInTheDocument();
    expect(container.querySelector(".salleslibres-liste")).toBeNull();
  });
});
