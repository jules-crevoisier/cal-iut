/**
 * Section « Doublons salle / enseignant » de l'écran « À traiter » (retour
 * Kyllian Bresson 25/09/2026) : chargement, liste groupée par semaine,
 * lien Vue Promo, état vide, état d'erreur + réessai.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Doublon } from "../api/client";
import { emptyPayload } from "../test/payloadFixture";
import { TodoView } from "./TodoView";

const payload = emptyPayload({
  weekLabels: ["Semaine 1"],
  weekDates: ["2026-09-28"],
});

function doublon(overrides: Partial<Doublon> = {}): Doublon {
  return {
    semaine: 0,
    jour: 3,
    creneau: 3,
    type: "salle",
    ressource: "H.201 / H.203",
    seances: [
      { session_id: "a", course_code: "WR101", groupes: ["g1"], salle: "H.201", enseignants: ["MRI"] },
      { session_id: "b", course_code: "WR205", groupes: ["g2"], salle: "H.203", enseignants: ["AUT"] },
    ],
    ...overrides,
  };
}

function stubFetch(reponse: { ok: true; doublons: Doublon[] } | { ok: false; message: string }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (String(url).startsWith("/controles/doublons")) {
        if (reponse.ok) {
          return Promise.resolve({ ok: true, json: async () => ({ doublons: reponse.doublons }) });
        }
        return Promise.resolve({
          ok: false,
          statusText: "Conflict",
          json: async () => ({ detail: reponse.message }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }),
  );
}

describe("TodoView — doublons salle / enseignant", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the response arrives", () => {
    stubFetch({ ok: true, doublons: [] });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    expect(screen.getByText("Chargement…")).toBeInTheDocument();
  });

  it("renders the empty state once the response confirms no doublon", async () => {
    stubFetch({ ok: true, doublons: [] });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Aucun doublon détecté.")).toBeInTheDocument());
  });

  it("groups doublons by week, shows the count badge, the resource, the dated slot and the courses in conflict", async () => {
    stubFetch({ ok: true, doublons: [doublon()] });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("H.201 / H.203")).toBeInTheDocument());
    expect(screen.getByText("Semaine 1")).toBeInTheDocument();
    expect(screen.getByText("salle")).toBeInTheDocument();
    // Date française : lundi 28/09/2026 + jour 3 (jeudi) = 1er octobre.
    expect(screen.getByText(/jeudi 1er oct\., 14h–15h30 — WR101 \/ WR205/)).toBeInTheDocument();
    expect(screen.getByLabelText("1 doublon")).toBeInTheDocument();
  });

  it("opens Vue Promo on the concerned week/day when a row is clicked", async () => {
    stubFetch({ ok: true, doublons: [doublon({ semaine: 4, jour: 2 })] });
    const setRoute = vi.fn();
    render(<TodoView payload={payload} setRoute={setRoute} />);

    await waitFor(() => expect(screen.getByText("H.201 / H.203")).toBeInTheDocument());
    fireEvent.click(screen.getByText("H.201 / H.203"));
    expect(setRoute).toHaveBeenCalledWith({ vue: "promo", sem: 4, jour: 2 });
  });

  it("shows a teacher-type row with its own label, distinct from a room row", async () => {
    stubFetch({
      ok: true,
      doublons: [
        doublon({
          type: "enseignant", ressource: "Marine Riguet",
          seances: [
            { session_id: "a", course_code: "WR101", groupes: ["g1"], salle: null, enseignants: ["MRI"] },
            { session_id: "b", course_code: "WR205", groupes: ["g2"], salle: null, enseignants: ["MRI"] },
          ],
        }),
      ],
    });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Marine Riguet")).toBeInTheDocument());
    expect(screen.getByText("enseignant")).toBeInTheDocument();
  });

  it("shows an error state with a retry button on failure, and recovers on retry", async () => {
    stubFetch({ ok: false, message: "Erreur serveur" });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Erreur serveur"));
    const bouton = screen.getByRole("button", { name: "Réessayer" });

    stubFetch({ ok: true, doublons: [] });
    fireEvent.click(bouton);

    await waitFor(() => expect(screen.getByText("Aucun doublon détecté.")).toBeInTheDocument());
  });
});
