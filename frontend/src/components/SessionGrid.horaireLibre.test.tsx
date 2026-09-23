/**
 * `SessionGrid` est la grille partagée des vues Groupe/Enseignant/Salle
 * (« Vue Semaine grid » du contrat) — un évènement à horaire libre (retour
 * Jules 23/09/2026, `row.hor`) y reste affiché dans sa case de STOCKAGE
 * (créneau 3), donc l'heure RÉELLE doit au moins être écrite à côté, sans
 * quoi rien ne dit que 14h-15h30 est faux.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionGrid } from "./SessionGrid";
import { emptyPayload, placedRow } from "../test/payloadFixture";

const PAYLOAD = emptyPayload({ weekDates: ["2026-09-14"] });

describe("SessionGrid — horaire réel d'un évènement à horaire libre", () => {
  it("affiche `hor` à côté du type de séance quand il est présent", () => {
    const row = placedRow({
      id: "evenement-1", d: 0, s: 3, c: "PRESENTATION-PAC", n: "Présentation PAC",
      t: "CM", hor: "13h15–14h",
    });
    render(<SessionGrid payload={PAYLOAD} rows={[row]} week={0} />);
    expect(screen.getByText(/13h15.*14h/)).toBeInTheDocument();
  });

  it("n'affiche rien de plus pour une séance normale, sans `hor`", () => {
    const row = placedRow({ id: "normal-1", d: 0, s: 0, c: "WR101", n: "Cours normal", t: "TD" });
    render(<SessionGrid payload={PAYLOAD} rows={[row]} week={0} />);
    const bloc = screen.getByText("Cours normal").closest("button");
    expect(bloc).not.toBeNull();
    // Le bloc porte code/type/groupe, jamais un horaire libre inexistant.
    expect(bloc?.textContent).toBe("Cours normalA100WR101 · TD");
  });
});
