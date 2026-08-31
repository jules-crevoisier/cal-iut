/**
 * Contrat `readOnly` de Vue Promo — retour utilisateur 31/08/2026 : « un
 * lien en plus ouvert à tout le monde [...] accès à la vue promo ».
 *
 * `readOnly` doit couper TOUTE écriture, y compris le panneau « Séances à
 * placer » et le clic-pour-placer, qui ne dépendaient auparavant que de
 * `placementActif` — jamais vérifiés contre la présence des callbacks
 * d'édition (`placements`/`onPlacementUpdated`/`onError`). Un lien public
 * qui ne les fournit pas était donc déjà protégé sur le papier, mais
 * seulement PAR OMISSION : si un futur appel les passait quand même à côté
 * de `readOnly`, rien ne les aurait empêchés de s'exécuter. Le dernier test
 * ci-dessous couvre exactement ce cas.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromoView } from "./PromoView";
import { emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
});

describe("PromoView readOnly", () => {
  it("should show the édition controls when editing callbacks are provided and readOnly is absent", () => {
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo" })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /nouvelle séance/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /séances à placer/i })).toBeInTheDocument();
  });

  it("should hide every write control when readOnly is set and no editing callback is provided", () => {
    render(<PromoView payload={payload} route={testRoute({ vue: "promo" })} readOnly />);
    expect(screen.queryByRole("button", { name: /nouvelle séance/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /séances à placer/i })).not.toBeInTheDocument();
  });

  it("should hide every write control when readOnly is set EVEN IF editing callbacks are also passed", () => {
    // Garde-fou : readOnly doit primer, pas seulement l'absence des callbacks.
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo" })}
        readOnly
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
        onAPlacerRefresh={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /nouvelle séance/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /séances à placer/i })).not.toBeInTheDocument();
  });
});
