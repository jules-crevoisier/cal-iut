/**
 * L'état de la file vers Celcat.
 *
 * Une file de 38 jobs « depuis 2 secondes » et « depuis 3 heures »
 * n'appellent pas le même geste, et c'est leur CROISEMENT qui alerte — une
 * file qui ne bouge pas malgré des passages réguliers est le signe d'une
 * panne. Trois jours de « file d'attente drainée » n'ont pas permis de le voir.
 *
 * Depuis le 16/09/2026 le composant n'interroge plus le serveur (la vue le
 * fait une fois pour tout l'écran) ; il doit en revanche DIRE quand l'appel a
 * échoué, au lieu de disparaître.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CelcatFile } from "../api/client";
import { EtatFileCelcat } from "./EtatFileCelcat";

const VIDE: CelcatFile = {
  en_attente: 0,
  par_action: {},
  passe_le: "2026-09-08T12:00:00+00:00",
  age_secondes: 30,
  reussis: 12,
  echecs: 0,
  ignores: 0,
  differes: 0,
  resume: "12 job(s) — 12 réussi(s)",
};

describe("État de la file Celcat", () => {
  it("annonce une file vide sans ambiguïté", () => {
    render(<EtatFileCelcat file={VIDE} />);
    expect(screen.getByText(/file d’attente vide — tout est poussé/i)).toBeTruthy();
  });

  it("détaille ce qui attend, par type d'action", () => {
    render(<EtatFileCelcat file={{ ...VIDE, en_attente: 3, par_action: { update: 2, delete: 1 } }} />);
    expect(screen.getByText(/3 corrections en attente : 2 modifications, 1 suppression/)).toBeTruthy();
  });

  it("montre QUAND le worker est passé et ce qu'il a fait, échecs en évidence", () => {
    render(<EtatFileCelcat file={{ ...VIDE, echecs: 2 }} />);
    const bloc = screen.getByTestId("etat-file-celcat");
    expect(bloc.textContent).toContain("il y a moins d’une minute");
    expect(bloc.textContent).toContain("12 réussies");
    expect(within(bloc).getByText("2 échecs").className).toContain("celcat-texte-panne");
  });

  it("dit que le worker n'est pas passé plutôt que d'afficher zéro", () => {
    render(<EtatFileCelcat file={{ ...VIDE, passe_le: null, age_secondes: null, reussis: 0 }} />);
    expect(screen.getByText(/pas encore passé/)).toBeTruthy();
  });

  it("range les motifs d'échec dans un repli au lieu d'un pavé", () => {
    render(
      <EtatFileCelcat
        file={{ ...VIDE, en_attente: 2, echecs: 2, resume: "2 job(s) — 0 réussi(s) — 2 en échec — 2× groupe introuvable (ex. s1)" }}
      />,
    );
    const repli = screen.getByTestId("file-motifs");
    expect(repli.tagName).toBe("DETAILS");
    expect(repli.textContent).toContain("groupe introuvable");
    expect(repli.textContent).not.toContain("0 réussi(s)");
  });

  it("dit à part ce qui attend une semaine non posée, et que c'est normal", () => {
    render(<EtatFileCelcat file={{ ...VIDE, en_attente: 4, differes: 4 }} />);
    expect(screen.getByTestId("file-differes").textContent).toMatch(/normal, rien à faire/);
  });

  it("dit que l'état est indisponible au lieu de disparaître", () => {
    render(<EtatFileCelcat file={null} erreur="serveur injoignable" />);
    expect(screen.getByTestId("etat-file-celcat").textContent).toContain("serveur injoignable");
  });
});
