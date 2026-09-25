/**
 * Contrat Vue « Salles libres » (todo département 22/09/2026, Kyllian
 * Bresson). Recentré le 25/09/2026 (retour utilisateur Jules, dicté : « on
 * peut garder uniquement [...] le tableau occupation qui est très bien [...]
 * on enlève les deux onglets [...] et on met ça en lien public [...] on met
 * uniquement le tableau que tu as fait qui est très bien avec les salles ») :
 * le sélecteur de créneau et la liste des salles libres disparaissent, seul
 * le tableau salles × créneaux reste, à toutes les largeurs, et un mode
 * lecture seule (`readOnly`, lien public `mode=salles`) coupe le clic
 * "fiche salle".
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SallesLibresView } from "./SallesLibresView";
import { catalogRoom, emptyPayload, placedRow, testRoute } from "../test/payloadFixture";

const WEEK_ROWS_OUVERTE = [{ monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 }];

function grille(container: HTMLElement) {
  const el = container.querySelector(".salleslibres-grille");
  if (!el) throw new Error("tableau d'occupation introuvable");
  return within(el as HTMLElement);
}

describe("SallesLibresView — tableau seul", () => {
  it("should render the occupancy table with every room, without the old slot selector or free-room list", () => {
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

    expect(grille(container).getByText("H.101")).toBeInTheDocument();
    expect(grille(container).getByText("H.201")).toBeInTheDocument();
    // Sélecteur de créneau et liste de salles libres retirés (doublonnaient
    // le tableau) — plus aucune trace de ces classes dans le DOM.
    expect(container.querySelector(".salleslibres-slots")).toBeNull();
    expect(container.querySelector(".salleslibres-liste")).toBeNull();
    expect(screen.queryByRole("button", { name: /9h30–11h/i })).not.toBeInTheDocument();
  });

  it("should show the room's occupied slot with the course code in the table cell", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" })],
      rows: [placedRow({ id: "s1", w: 0, d: 0, s: 1, dur: 1, r: "H.101", c: "WR108", t: "TD" })],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres", jour: 0 })} setRoute={vi.fn()} />,
    );

    expect(grille(container).getByText("WR108")).toBeInTheDocument();
  });

  it("should filter the table rows by minimum capacity", () => {
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

    expect(grille(container).queryByText("H.101")).not.toBeInTheDocument();
    expect(grille(container).getByText("H.201")).toBeInTheDocument();
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

    expect(container.querySelector(".salleslibres-grille")).toBeNull();
    expect(screen.getByText(/aucune salle ne correspond aux filtres/i)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/hors placement automatique/i));

    expect(grille(container).getByText("BU / A.123")).toBeInTheDocument();
  });

  it("should show an explicit message for a blocked week instead of the table", () => {
    const payload = emptyPayload({
      weekRows: [{ monday: "2026-01-05", label: "Vacances de Noël", blocked: true, weekIndex: null }],
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={vi.fn()} />,
    );

    expect(screen.getByText(/bloquée/i)).toBeInTheDocument();
    expect(container.querySelector(".salleslibres-grille")).toBeNull();
  });

  it("should show an explicit message for a holiday day instead of the table", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [catalogRoom("h101", { label: "H.101" })],
      rows: [],
      holidayRows: [{ w: 0, d: 0, kind: "ferie", label: "Jour férié" }],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres", jour: 0 })} setRoute={vi.fn()} />,
    );

    expect(screen.getByText(/jour férié/i)).toBeInTheDocument();
    expect(container.querySelector(".salleslibres-grille")).toBeNull();
  });
});

describe("SallesLibresView — readOnly (lien public mode=salles)", () => {
  it("should show the room name as a clickable link to its sheet when not readOnly", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" })],
      rows: [],
    });
    const setRoute = vi.fn();

    render(<SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={setRoute} />);

    fireEvent.click(screen.getByRole("button", { name: "H.101" }));
    expect(setRoute).toHaveBeenCalledWith({ vue: "salle", salle: "h101", sem: 0 });
  });

  it("should render the room name as plain text, with no navigation affordance, when readOnly", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" })],
      rows: [],
    });
    const setRoute = vi.fn();

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={setRoute} readOnly />,
    );

    expect(grille(container).getByText("H.101")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "H.101" })).not.toBeInTheDocument();
  });

  it("should keep filters and the table itself usable when readOnly", () => {
    const payload = emptyPayload({
      weekRows: WEEK_ROWS_OUVERTE,
      rooms: [
        catalogRoom("h101", { label: "H.101", capacity: 24, type: "standard" }),
        catalogRoom("h201", { label: "H.201", capacity: 40, type: "standard" }),
      ],
      rows: [],
    });

    const { container } = render(
      <SallesLibresView payload={payload} route={testRoute({ vue: "salles-libres" })} setRoute={vi.fn()} readOnly />,
    );

    fireEvent.change(screen.getByLabelText(/capacité minimum/i), { target: { value: "30" } });

    expect(grille(container).queryByText("H.101")).not.toBeInTheDocument();
    expect(grille(container).getByText("H.201")).toBeInTheDocument();
  });
});
