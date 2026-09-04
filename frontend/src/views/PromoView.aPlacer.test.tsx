/**
 * Bug remonté par l'utilisateur (04/09/2026, verbatim) : « dans à placer
 * quand l'on clique sur placer sur la grille, et ensuite que l'on clique
 * sur la grille cela ne place pas la séance ». Cause : `placementActif`
 * arrive avec le parcours de LA séance choisie, mais si le filtre
 * année/parcours affiché à l'écran pointait encore sur un AUTRE parcours
 * (navigation précédente), la colonne de la séance n'existe plus du tout
 * dans la grille — aucune case n'est cliquable nulle part, sans erreur.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SeanceAPlacer } from "../api/client";
import { emptyPayload, testRoute } from "../test/payloadFixture";
import { PromoView } from "./PromoView";

const placerSeance = vi.fn().mockResolvedValue({ session_id: "s-manquante" });
vi.mock("../api/client", async (importOriginal) => {
  const reel = await importOriginal<typeof import("../api/client")>();
  return { ...reel, placerSeance: (...args: unknown[]) => placerSeance(...args) };
});
vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const payload = emptyPayload({
  groupLabels: {
    "but1-td-ab": "TD AB",
    "but2-dev-fi-td-ab": "TD AB DEV",
  },
  groupParcours: {
    "but1-td-ab": "BUT1",
    "but2-dev-fi-td-ab": "BUT2-DEV-FI",
  },
  groupKind: {
    "but1-td-ab": "td",
    "but2-dev-fi-td-ab": "td",
  },
  groupCohort: {
    "but1-td-ab": ["but1-td-ab"],
    "but2-dev-fi-td-ab": ["but2-dev-fi-td-ab"],
  },
  teacherLabels: { MRI: "Riguet" },
  weekRows: [{ monday: "2026-08-31", label: "Semaine 2", blocked: false, weekIndex: 0 }],
  weekLabels: ["S2"],
  weekDates: ["2026-08-31"],
  weekStatus: [{ week: 0, status: "current" }],
  rows: [],
});

function manquante(overrides: Partial<SeanceAPlacer> = {}): SeanceAPlacer {
  return {
    session_id: "s-manquante",
    course_code: "WR311D",
    course_name: "Dev avancé",
    session_type: "TD",
    semestre: "S3",
    parcours: "BUT2-DEV-FI",
    annee: "BUT2",
    duration_slots: 1,
    duree_libelle: "1h30",
    group_ids: ["but2-dev-fi-td-ab"],
    groupes_libelles: ["TD AB DEV"],
    teacher_codes: ["MRI"],
    enseignants_libelles: ["Riguet"],
    sequence_order: null,
    semaines_possibles: [0],
    raison: "manquante",
    placee_provisoirement: false,
    semaine_actuelle: null,
    jour_actuel: null,
    slot_actuel: null,
    ...overrides,
  };
}

describe("PromoView à-placer sous filtre différent", () => {
  it("should place the missing session on click even when the year filter still points at another year", async () => {
    const { rerender } = render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo", jour: 0 })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
        placementActif={null}
      />,
    );

    // L'utilisateur navigue sur BUT1 (autre chose que le parcours de la
    // manquante qu'il va choisir juste après, BUT2-DEV-FI) AVANT d'ouvrir
    // « À placer ».
    fireEvent.change(screen.getByLabelText(/^année$/i), { target: { value: "BUT1" } });
    expect(screen.getByLabelText(/^année$/i)).toHaveValue("BUT1");

    // Il clique « Placer sur la grille » sur une manquante BUT2-DEV-FI —
    // `placementActif` change de null à cette séance, exactement comme
    // `setChoixAPlacer(seance)` dans le flux réel.
    rerender(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo", jour: 0 })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
        placementActif={manquante()}
      />,
    );

    // Sans le correctif, le filtre restait bloqué sur "BUT1" et la colonne
    // BUT2-DEV-FI (et donc toute case cliquable) n'existait plus du tout.
    expect(screen.getByLabelText(/^année$/i)).toHaveValue("Tout");
    // Toutes les cases vides de la colonne BUT2-DEV-FI ce jour-là sont
    // devenues cliquables — on cible la première (8h–9h30 = slot 0) pour
    // que l'appel serveur porte un slot précis et vérifiable.
    const table = screen.getByRole("table");
    const cell = within(table).getAllByText("+ poser ici")[0];
    fireEvent.click(cell);

    await vi.waitFor(() => expect(placerSeance).toHaveBeenCalledTimes(1));
    expect(placerSeance).toHaveBeenCalledWith("s-manquante", { week: 0, day: 0, slot: 0 });
  });
});
