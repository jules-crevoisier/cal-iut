/**
 * Écran Celcat : « Occupations hors MMI » tient en UNE ligne de résumé et un
 * bouton « Relire maintenant » (retour de Jules, 02/10/2026 soir : la vue
 * « Occupé ailleurs » disparaît). Contrat :
 * `.orchestrator/contract-occupations-sur-le-planning.md`, décision 2.
 * N = nombre d'évènements du relevé (`evenements.length`).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  fetchOccupationsHorsMmi: vi.fn(),
  rafraichirOccupationsHorsMmi: vi.fn(),
}));

import * as client from "../api/client";
import { OccupationsHorsMmi } from "./OccupationsHorsMmi";

const fetchMock = vi.mocked(client.fetchOccupationsHorsMmi);
const rafraichirMock = vi.mocked(client.rafraichirOccupationsHorsMmi);

function evenement(code: string) {
  return {
    t: "enseignant",
    code,
    date: "2026-11-09",
    debut: "09:00",
    fin: "11:00",
    dep: "TC",
    lib: "RR113 Numérique",
    cat: "TD",
  };
}

function donnees(partiel: Record<string, unknown> = {}) {
  return {
    releveLe: new Date().toISOString(),
    ageSecondes: 60,
    absent: false,
    perime: false,
    fraicheurHeures: 6,
    strict: false,
    erreur: null,
    demandeEnCours: false,
    lectureActive: true,
    periode: {},
    base: "",
    ignores: {},
    erreurs: [],
    ressources: [],
    evenements: [evenement("AFR"), evenement("RHU")],
    conflits: [],
    ...partiel,
  } as never;
}

beforeEach(() => {
  fetchMock.mockReset();
  rafraichirMock.mockReset();
});

describe("OccupationsHorsMmi", () => {
  it("should summarize the count and the date of the reading when a reading exists", async () => {
    fetchMock.mockResolvedValue(donnees());
    render(<OccupationsHorsMmi />);

    expect(await screen.findByText(/^2 à venir · relevé /)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Occupations hors MMI" })).toBeInTheDocument();
  });

  it("should say aucun relevé when no reading was ever made", async () => {
    fetchMock.mockResolvedValue(donnees({ absent: true, releveLe: null, evenements: [] }));
    render(<OccupationsHorsMmi />);

    expect(await screen.findByText(/aucun relevé/)).toBeInTheDocument();
  });

  it("should explain where occupations appear when the panel is shown", async () => {
    fetchMock.mockResolvedValue(donnees());
    render(<OccupationsHorsMmi />);
    await screen.findByText(/à venir/);

    expect(screen.getByText(/Salles et enseignants pris hors MMI\./)).toBeInTheDocument();
    expect(screen.getByText(/apparaissent en grisé dans les Vues Enseignant et Salle/)).toBeInTheDocument();
    expect(screen.getByText(/l.appli prévient quand on pose une séance dessus/)).toBeInTheDocument();
  });

  it("should not offer any way to open an Occupé ailleurs view", async () => {
    fetchMock.mockResolvedValue(donnees());
    render(<OccupationsHorsMmi />);
    await screen.findByText(/à venir/);

    expect(screen.queryByRole("button", { name: /occupé ailleurs/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /occupé ailleurs/i })).toBeNull();
    expect(screen.queryByText(/Ouvrir Occupé ailleurs/i)).toBeNull();
  });

  it("should ask for a new reading and show the returned message when Relire maintenant is clicked", async () => {
    fetchMock.mockResolvedValue(donnees());
    rafraichirMock.mockResolvedValue({ demande: true, message: "Relecture demandée, le robot passe dans 2 minutes." });
    render(<OccupationsHorsMmi />);
    await screen.findByText(/à venir/);

    fireEvent.click(screen.getByRole("button", { name: "Relire maintenant" }));

    expect(rafraichirMock).toHaveBeenCalledTimes(1);
    const statut = await screen.findByRole("status");
    expect(statut).toHaveTextContent("Relecture demandée, le robot passe dans 2 minutes.");
  });

  it("should label the button Relecture demandée and disable it while the request is running", async () => {
    fetchMock.mockResolvedValue(donnees());
    rafraichirMock.mockReturnValue(new Promise(() => {}));
    render(<OccupationsHorsMmi />);
    await screen.findByText(/à venir/);

    fireEvent.click(screen.getByRole("button", { name: "Relire maintenant" }));

    const bouton = await screen.findByRole("button", { name: /Relecture demandée/ });
    expect(bouton).toBeDisabled();
  });

  it("should disable Relire maintenant when the reading is switched off", async () => {
    fetchMock.mockResolvedValue(donnees({ lectureActive: false }));
    render(<OccupationsHorsMmi />);
    await screen.findByText(/à venir/);

    expect(screen.getByRole("button", { name: /relire|relecture/i })).toBeDisabled();
  });

  it("should disable Relire maintenant when a request is already pending on the server", async () => {
    fetchMock.mockResolvedValue(donnees({ demandeEnCours: true }));
    render(<OccupationsHorsMmi />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await screen.findByText(/à venir/);

    expect(screen.getByRole("button", { name: /relire|relecture/i })).toBeDisabled();
  });

  it("should enable Relire maintenant when reading is on and nothing is pending", async () => {
    fetchMock.mockResolvedValue(donnees());
    render(<OccupationsHorsMmi />);
    await screen.findByText(/à venir/);

    expect(screen.getByRole("button", { name: "Relire maintenant" })).toBeEnabled();
  });
});
