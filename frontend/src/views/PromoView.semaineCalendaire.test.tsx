/**
 * Semaine calendaire dans le titre de Vue Promo — todo département, retour
 * Kyllian Bresson : « indiquer la semaine calendaire en même temps que la
 * semaine universitaire, exemple Lundi — Semaine 6 (28 sept.–2 oct. 2026)
 * devient [...] semaine calendaire 40 ». Calculée depuis le lundi RÉEL de
 * `weekRows[displayWeek].monday`, jamais en reparsant le libellé.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromoView } from "./PromoView";
import { emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  // 28 septembre 2026 est un lundi, semaine universitaire "S6" (libellé
  // volontairement simple ici) -> semaine calendaire ISO 40.
  weekRows: [{ monday: "2026-09-28", label: "Semaine 6 (28 sept.–2 oct. 2026)", blocked: false, weekIndex: 0 }],
});

describe("PromoView title shows the ISO calendar week", () => {
  it("should append the calendar week to the grid title, next to the university week label", () => {
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /semaine 6 \(28 sept\.–2 oct\. 2026\) · semaine calendaire 40/i }),
    ).toBeInTheDocument();
  });
});
