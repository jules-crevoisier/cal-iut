/**
 * Occupations hors MMI sur le planning (retour de Jules, 02/10/2026 soir) :
 * « les évènements qui prennent les salles : on peut les afficher sur le
 * planning en grisé ». Contrat : `.orchestrator/contract-occupations-sur-le-planning.md`.
 *
 * Contrat du module (voir `utils/occupationsExternes.test.ts`) : la prop
 * `externes` de `SessionGrid` devient `Map<string, LigneOccupation[]>`, clé
 * « jour-créneau », avec
 * `LigneOccupation = { qui: string; quoi: string; horaire: string; detail: string }`.
 *  - case vide : bloc grisé, « hors MMI » une seule fois en tête, puis par
 *    occupation « qui » et « quoi · horaire » ; `title` = `detail` ;
 *  - case avec une séance : mention neutre « Aussi pris ailleurs : qui,
 *    horaire » (jamais « Conflit Celcat »).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionGrid } from "./SessionGrid";
import { emptyPayload, placedRow } from "../test/payloadFixture";

interface LigneOccupation {
  qui: string;
  quoi: string;
  horaire: string;
  detail: string;
}

const PAYLOAD = emptyPayload({ weekDates: ["2026-11-09"] });

const TC: LigneOccupation = {
  qui: "TC",
  quoi: "RR113 Numérique",
  horaire: "09h00–11h00",
  detail: "TD · RR113 Numérique · 09h00–11h00 · TC",
};
const ADMIN: LigneOccupation = {
  qui: "Administration",
  quoi: "Conseil de département",
  horaire: "14h00–17h00",
  detail: "Réunion · Conseil de département · 14h00–17h00 · Administration",
};
const CJ: LigneOccupation = {
  qui: "CJ",
  quoi: "Droit du numérique",
  horaire: "09h00–11h00",
  detail: "CM · Droit du numérique · 09h00–11h00 · CJ",
};

function grille(externes: Map<string, LigneOccupation[]>, rows = [] as ReturnType<typeof placedRow>[]) {
  return render(<SessionGrid payload={PAYLOAD} rows={rows} week={0} externes={externes as never} />);
}

describe("SessionGrid — occupations hors MMI", () => {
  it("should show a grey block saying hors MMI once, with who and what when a free cell is occupied elsewhere", () => {
    grille(new Map([["0-1", [TC, CJ]]]));

    expect(screen.getAllByText(/hors MMI/i)).toHaveLength(1);
    expect(screen.getByText("TC")).toBeInTheDocument();
    expect(screen.getByText("CJ")).toBeInTheDocument();
    expect(screen.getByText("RR113 Numérique · 09h00–11h00")).toBeInTheDocument();
    expect(screen.getByText("Droit du numérique · 09h00–11h00")).toBeInTheDocument();
  });

  it("should write Administration as the who when the department is empty", () => {
    grille(new Map([["1-3", [ADMIN]]]));

    expect(screen.getByText("Administration")).toBeInTheDocument();
    expect(screen.getByText("Conseil de département · 14h00–17h00")).toBeInTheDocument();
  });

  it("should carry the full detail in the title when the block is hovered", () => {
    grille(new Map([["0-1", [TC]]]));

    expect(screen.getAllByTitle(TC.detail).length).toBeGreaterThan(0);
  });

  it("should say Aussi pris ailleurs, not Conflit Celcat, when a placed session shares the cell", () => {
    const row = placedRow({ id: "td-afr", d: 0, s: 1, c: "WR101", n: "Culture numérique", t: "TD" });
    grille(new Map([["0-1", [TC]]]), [row]);

    expect(screen.getByText("Culture numérique")).toBeInTheDocument();
    expect(screen.getByText(/Aussi pris ailleurs : TC, 09h00–11h00/)).toBeInTheDocument();
    expect(screen.queryByText(/Conflit Celcat/i)).toBeNull();
    // Le bloc grisé « hors MMI » est réservé aux cases vides.
    expect(screen.queryByText(/^hors MMI$/i)).toBeNull();
  });

  it("should carry the detail in the title of the mention when a placed session shares the cell", () => {
    const row = placedRow({ id: "td-afr", d: 0, s: 1, c: "WR101", n: "Culture numérique", t: "TD" });
    grille(new Map([["0-1", [TC]]]), [row]);

    expect(screen.getAllByTitle(TC.detail).length).toBeGreaterThan(0);
  });

  it("should list every occupier in the mention when two occupations share a cell with a session", () => {
    const row = placedRow({ id: "td-afr", d: 0, s: 1, c: "WR101", n: "Culture numérique", t: "TD" });
    grille(new Map([["0-1", [TC, CJ]]]), [row]);

    const mention = screen.getByText(/Aussi pris ailleurs/);
    expect(mention.textContent).toContain("TC");
    expect(mention.textContent).toContain("CJ");
  });

  it("should show nothing about Celcat when no occupation is given", () => {
    grille(new Map());

    expect(screen.queryByText(/hors MMI/i)).toBeNull();
    expect(screen.queryByText(/Aussi pris ailleurs/)).toBeNull();
  });
});

// Ajout du lead après le contrôle visuel (02/10/2026) : en semaine de SAE, la
// Vue Salle d'A.018 montrait « SAE » dans chaque case et cachait les 14
// occupations de la salle, alors que la version téléphone les affichait.
describe("SessionGrid — une occupation passe devant les bandes MMI", () => {
  it("shows the booking of the room instead of the SAE band on a SAE day", () => {
    const payload = emptyPayload({
      weekDates: ["2026-11-09"],
      saeRows: [{ w: 0, d: 0, p: "BUT1", codes: ["WS101"] }] as never,
    });
    render(<SessionGrid payload={payload} rows={[]} week={0} externes={new Map([["0-1", [TC]]]) as never} />);

    expect(screen.getByText("RR113 Numérique · 09h00–11h00")).toBeInTheDocument();
    // Les autres créneaux du jour gardent la bande SAE.
    expect(screen.getAllByText("WS101").length).toBeGreaterThan(0);
  });
});
