/**
 * Évènement à horaire libre tombé dans la pause méridienne (retour Jules
 * 23/09/2026, Kyllian Bresson : « m'ajouter une séance évènement [...] à
 * 13h15 jusqu'à 14h [...] sans mettre d'enseignant »). `r.midi`/`r.hor`
 * (`GET /app-state`, cf. `export/html_view.py`) doivent :
 *  - se rendre dans la ligne "pause" existante (entre les créneaux 2 et 3),
 *    jamais dans la cellule normale du créneau 3 où la séance est STOCKÉE ;
 *  - afficher son horaire réel et sa salle.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PromoView } from "./PromoView";
import { emptyPayload, placedRow, testRoute } from "../test/payloadFixture";

const payloadAvecPause = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  groupKind: { "but1-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"] },
  rows: [
    placedRow({
      id: "evenement-1", w: 0, d: 0, s: 3, c: "PRESENTATION-PAC", n: "Présentation PAC",
      t: "CM", g: ["but1-td-ab"], r: "H.018", hor: "13h15–14h", midi: true, custom: true,
    }),
    placedRow({ id: "cours-14h", w: 0, d: 0, s: 3, c: "WR101", n: "Cours normal", g: ["but1-td-ab"] }),
  ],
});

describe("PromoView — évènement à horaire libre (pause méridienne)", () => {
  it("should render the midi row inside the pause line, not the normal slot-3 cell", () => {
    render(
      <PromoView
        payload={payloadAvecPause}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        readOnly
      />,
    );

    const pauseRow = document.querySelector("tr.pause");
    expect(pauseRow).not.toBeNull();
    expect(within(pauseRow as HTMLElement).getByText("Présentation PAC")).toBeInTheDocument();
    expect(within(pauseRow as HTMLElement).getByText(/13h15.*14h/)).toBeInTheDocument();
    expect(within(pauseRow as HTMLElement).getByText(/H\.018/)).toBeInTheDocument();
  });

  it("should keep the normal course visible in the real slot-3 cell, unaffected by the midi row", () => {
    render(
      <PromoView
        payload={payloadAvecPause}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        readOnly
      />,
    );
    expect(screen.getByText("WR101")).toBeInTheDocument();
  });

  it("should not duplicate the midi event into the slot-3 cell", () => {
    render(
      <PromoView
        payload={payloadAvecPause}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        readOnly
      />,
    );
    // Le libellé de l'évènement n'apparaît qu'UNE fois (ligne "pause"),
    // jamais une seconde dans la cellule normale du créneau 3.
    expect(screen.getAllByText("Présentation PAC")).toHaveLength(1);
  });

  it("should render nothing extra in the pause row when no midi event exists that day", () => {
    const payloadSansPause = emptyPayload({
      groupLabels: { "but1-td-ab": "TD AB" },
      groupParcours: { "but1-td-ab": "BUT1" },
      groupKind: { "but1-td-ab": "td" },
      groupCohort: { "but1-td-ab": ["but1-td-ab"] },
      rows: [placedRow({ id: "cours-14h", w: 0, d: 0, s: 3, c: "WR101", g: ["but1-td-ab"] })],
    });
    render(
      <PromoView payload={payloadSansPause} route={testRoute({ vue: "promo", jour: 0, sem: 0 })} readOnly />,
    );
    const pauseRow = document.querySelector("tr.pause");
    expect(pauseRow).not.toBeNull();
    expect(within(pauseRow as HTMLElement).queryByText(/./)).not.toBeInTheDocument();
  });
});
