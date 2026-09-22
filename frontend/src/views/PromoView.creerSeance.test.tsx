/**
 * « + Nouvelle séance » depuis Vue Promo doit pré-remplir semaine/jour avec
 * ce qui est AFFICHÉ à l'écran — retour utilisateur, todo département,
 * Kyllian Bresson (22/09/2026) : « création de nouvelle séance à simplifier
 * (rester sur la semaine à saisir, sur le jour à saisir), car pour chaque
 * séance à créer le formulaire est long ». Avant ce correctif, la modale
 * retombait toujours sur la PREMIÈRE semaine de l'année, quel que soit le
 * jour/semaine affichés dans la grille.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromoView } from "./PromoView";
import { catalogCourse, emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  courses: [catalogCourse("WR101", "Cours existant", { parcours: "BUT1" })],
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  weekRows: [
    { monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 },
    { monday: "2026-01-12", label: "S2", blocked: false, weekIndex: 1 },
  ],
});

describe("PromoView + Nouvelle séance pre-fills the currently displayed week/day", () => {
  it("should open CreerSeanceModal with the week and day currently shown in Vue Promo, not the first week of the year", () => {
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo", jour: 3, sem: 1 })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /nouvelle séance/i }));
    expect(screen.getByLabelText("Semaine")).toHaveValue("1");
    expect(screen.getByLabelText("Jour")).toHaveValue("3");
  });
});
