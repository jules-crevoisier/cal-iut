/**
 * L'état de la file après un clic sur « Corriger ».
 *
 * Ce que ces tests protègent : une file de 38 jobs « depuis 2 secondes » et
 * « depuis 3 heures » n'appellent pas le même geste, et c'est leur
 * CROISEMENT qui alerte — une file qui ne bouge pas malgré des passages
 * réguliers est le signe d'une panne. Trois jours de « file d'attente
 * drainée » n'ont pas permis de le voir.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EtatFileCelcat } from "./EtatFileCelcat";

function stub(corps: unknown) {
  const mock = vi.fn(() => Promise.resolve({ ok: true, json: async () => corps } as Response));
  vi.stubGlobal("fetch", mock as unknown as typeof fetch);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const VIDE = {
  en_attente: 0, par_action: {}, passe_le: "2026-09-08T12:00:00+00:00",
  age_secondes: 30, reussis: 12, echecs: 0, ignores: 0, resume: "12 job(s) — 12 réussi(s)",
};

describe("État de la file Celcat", () => {
  it("annonce une file vide sans ambiguïté", async () => {
    stub(VIDE);
    render(<EtatFileCelcat />);

    expect(await screen.findByText(/file d’attente vide/i)).toBeTruthy();
  });

  it("détaille ce qui attend, par type d'action", async () => {
    // « 38 en attente » ne dit pas si ce sont des suppressions.
    stub({ ...VIDE, en_attente: 38, par_action: { update: 20, delete: 17, create: 1 } });
    render(<EtatFileCelcat />);

    const bloc = await screen.findByTestId("etat-file-celcat");
    expect(bloc.textContent).toContain("38 correction(s) en attente");
    // En français, pas en jargon d'API : « delete » ne dit pas à un
    // utilisateur que dix-sept cours vont DISPARAÎTRE de Celcat.
    expect(bloc.textContent).toContain("17 suppressions");
  });

  it("range les motifs d'échec dans un repli au lieu d'un pavé", async () => {
    // Retour utilisateur 08/09/2026, capture à l'appui : « fix moi cette
    // interface, on ne comprend rien du tout là ». Le résumé brut noyait les
    // trois chiffres qui décident sous vingt lignes de motifs.
    stub({
      ...VIDE,
      en_attente: 414,
      par_action: { create: 392, update: 22 },
      reussis: 18,
      echecs: 7,
      resume:
        "414 job(s) — 18 réussi(s) — 7 en échec — 1× matière TSBZC05M introuvable " +
        "(ex. WRA305M) | 1× matière TSBZC12M introuvable (ex. WRA312M)",
    });
    render(<EtatFileCelcat />);

    const bloc = await screen.findByTestId("etat-file-celcat");
    // Ce qui décide reste en clair, hors du repli.
    expect(bloc.textContent).toContain("18 réussi(s)");
    const motifs = await screen.findByTestId("file-motifs");
    expect(motifs.querySelectorAll("li").length).toBe(3);
    expect(motifs.textContent).toContain("TSBZC05M");
  });

  it("montre QUAND le worker est passé et ce qu'il a fait", async () => {
    // Une file qui stagne malgré des passages = panne. Sans l'âge, on ne
    // peut pas faire la différence avec « il n'est pas encore passé ».
    stub({ ...VIDE, en_attente: 38, reussis: 0, echecs: 38, resume: "38 job(s) — 0 réussi(s)" });
    render(<EtatFileCelcat />);

    const bloc = await screen.findByTestId("etat-file-celcat");
    expect(bloc.textContent).toMatch(/dernier passage du worker il y a/i);
    expect(bloc.textContent).toContain("0 réussi");
  });

  it("dit que le worker n'est pas passé plutôt que d'afficher zéro", async () => {
    // « 0 réussi » serait indiscernable d'un échec total.
    stub({ ...VIDE, en_attente: 5, passe_le: null, age_secondes: null, resume: "" });
    render(<EtatFileCelcat />);

    expect(await screen.findByText(/n’est pas encore passé/i)).toBeTruthy();
  });

  it("cesse d'interroger le serveur quand la file est vide", async () => {
    // Un écran qui interroge sans raison est un écran qu'on finit par fermer.
    const mock = stub(VIDE);
    render(<EtatFileCelcat />);

    await screen.findByText(/file d’attente vide/i);
    const appels = mock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 50));
    await waitFor(() => expect(mock.mock.calls.length).toBe(appels));
  });
});
