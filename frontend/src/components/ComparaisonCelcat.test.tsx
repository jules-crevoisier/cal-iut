/**
 * Celcat vs cal-iut côte à côte.
 *
 * Ce que ces tests protègent : l'écran ne doit jamais laisser croire que
 * tout va bien quand il ne sait rien, ni noyer un écart parmi cent lignes
 * vertes. C'est la leçon des trois derniers jours — un worker qui annonçait
 * « file d'attente drainée » sans rien écrire, des compteurs à zéro
 * incapables de bouger, et un CM resté à la mauvaise heure pendant des jours
 * sans que rien ne le signale.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ComparaisonCelcat } from "./ComparaisonCelcat";

function jsonOk(data: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, json: async () => data } as Response);
}

const ECART = {
  statut: "ecart" as const,
  session_id: "WR116-S1-CM-1",
  course_code: "WR116",
  caliut: { jour: 1, heure: "15:30", salle: "Amphi 3 MMI", semaine: 1 },
  celcat: {
    event_id: 1931709, jour: 1, heure: "13:50", salle: "Amphi 3 MMI",
    categorie: "[CM]", module: "WR116 Traitement Info", groupe: "BUT MMI S1 CM",
  },
  ecarts: ["heure"],
};

const IDENTIQUE = {
  statut: "identique" as const,
  session_id: "WR101-S1-TD-1",
  course_code: "WR101",
  caliut: { jour: 0, heure: "08:00", salle: "H.103", semaine: 1 },
  celcat: {
    event_id: 111, jour: 0, heure: "07:50", salle: "H.103",
    categorie: "[TD]", module: "WR101 Anglais", groupe: "BUT MMI S1 TD AB",
  },
  ecarts: [],
};

function stub(corps: unknown) {
  const mock = vi.fn(() => jsonOk(corps));
  vi.stubGlobal("fetch", mock as unknown as typeof fetch);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const BASE = {
  semaine: 1, semaine_celcat: 3,
  releve_le: "2026-09-08T10:00:00+00:00", age_secondes: 300, perime: false,
};

describe("Comparaison Celcat / cal-iut", () => {
  it("montre les deux côtés d'un écart", async () => {
    stub({ ...BASE, lignes: [ECART] });
    render(<ComparaisonCelcat semaine={1} />);

    const bloc = await screen.findByTestId("comparaison-celcat");
    expect(within(bloc).getByText(/15:30/)).toBeTruthy(); // cal-iut
    expect(within(bloc).getByText(/13:50/)).toBeTruthy(); // Celcat
    expect(within(bloc).getByText(/heure/)).toBeTruthy(); // la nature de l'écart
  });

  it("replie les séances identiques au lieu de les étaler", async () => {
    // Chercher un problème parmi cent lignes vertes, c'est ne pas le trouver.
    stub({ ...BASE, lignes: [ECART, IDENTIQUE] });
    render(<ComparaisonCelcat semaine={1} />);

    await screen.findByTestId("comparaison-celcat");
    expect(screen.queryByTestId("comparaison-identiques")).toBeNull();
    expect(screen.getByText(/WR116-S1-CM-1/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /afficher les 1 séance/i }));
    expect(await screen.findByTestId("comparaison-identiques")).toBeTruthy();
  });

  it("dit qu'il n'y a rien à comparer plutôt que d'afficher un écran vide", async () => {
    // Sans relevé, tout paraîtrait absent de Celcat : un écran vide se
    // lirait « rien à signaler », exactement le contraire de la vérité.
    stub({ ...BASE, releve_le: null, age_secondes: null, perime: true, lignes: [] });
    render(<ComparaisonCelcat semaine={1} />);

    expect(await screen.findByTestId("comparaison-sans-releve")).toBeTruthy();
  });

  it("signale un relevé périmé", async () => {
    stub({ ...BASE, age_secondes: 10800, perime: true, lignes: [ECART] });
    render(<ComparaisonCelcat semaine={1} />);

    const bloc = await screen.findByTestId("comparaison-celcat");
    expect(within(bloc).getByText(/périmé/i)).toBeTruthy();
  });

  it("annonce quand tout concorde, sans ambiguïté", async () => {
    stub({ ...BASE, lignes: [IDENTIQUE] });
    render(<ComparaisonCelcat semaine={1} />);

    const bloc = await screen.findByTestId("comparaison-celcat");
    expect(within(bloc).getByText(/tout concorde/i)).toBeTruthy();
  });

  it("permet de copier les écarts", async () => {
    const ecrit = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: ecrit } });
    stub({ ...BASE, lignes: [ECART] });
    render(<ComparaisonCelcat semaine={1} />);

    fireEvent.click(await screen.findByRole("button", { name: /copier les écarts/i }));

    await waitFor(() => expect(ecrit).toHaveBeenCalled());
    const copie = String(ecrit.mock.calls[0][0]);
    expect(copie).toContain("WR116-S1-CM-1");
    expect(copie).toContain("event_id=1931709");
  });
});

describe("Bouton « Corriger tous les écarts »", () => {
  it("demande confirmation en disant COMBIEN de suppressions", async () => {
    // Créer en trop se rattrape, supprimer non : c'est le nombre qu'il faut
    // voir avant de valider.
    const confirmer = vi.fn(() => Promise.resolve(false));
    vi.doMock("../utils/confirmDialog", () => ({ confirmAsync: confirmer }));
    const mock = stub({
      ...BASE,
      lignes: [ECART, { ...ECART, statut: "en_trop_celcat" as const, caliut: null }],
    });
    render(<ComparaisonCelcat semaine={1} />);

    fireEvent.click(await screen.findByRole("button", { name: /corriger tous les écarts/i }));

    // Rien n'est envoyé tant que l'utilisateur n'a pas confirmé.
    await waitFor(() =>
      expect(
        mock.mock.calls.some(([u]) => String(u).includes("/comparaison/corriger")),
      ).toBe(false),
    );
  });

  it("compte à part les séances sans équivalent Celcat", async () => {
    // Retour utilisateur : « il faut bien sûr ignorer les cours que l'on a
    // créés, exemple BU ». Les mêler aux écarts noierait les vrais.
    stub({
      ...BASE,
      lignes: [
        ECART,
        {
          ...ECART,
          statut: "hors_celcat" as const,
          session_id: "WR100BU-S1-TD-1",
          course_code: "WR100BU",
          celcat: null,
        },
      ],
    });
    render(<ComparaisonCelcat semaine={1} />);

    const bloc = await screen.findByTestId("comparaison-celcat");
    expect(within(bloc).getByText(/1 écart\(s\)/)).toBeTruthy();
    expect(within(bloc).getByText(/sans équivalent dans Celcat/i)).toBeTruthy();
  });
});
