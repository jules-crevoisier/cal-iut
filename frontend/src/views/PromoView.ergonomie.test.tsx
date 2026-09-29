/**
 * Vue Promo — améliorations de la refonte du 29/09/2026 : raccourcis
 * clavier, filtres mémorisés, retour visible avec « Annuler » après un
 * déplacement, carte de séance compacte (nom d'enseignant abrégé, actions
 * nommées).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContexteSemaine } from "../contexts/SemaineGlobale";
import type { Placement } from "../types";
import { emptyPayload, placedRow, testRoute } from "../test/payloadFixture";
import { performMove } from "../utils/moveSession";
import { PromoView } from "./PromoView";

vi.mock("../utils/moveSession", () => ({
  performMove: vi.fn().mockResolvedValue(true),
  performSwap: vi.fn().mockResolvedValue(true),
}));

const weekRows = [
  { monday: "2026-08-31", label: "Semaine 2 (31 août–4 sept. 2026)", blocked: false, weekIndex: 0 },
  { monday: "2026-09-07", label: "Semaine 3 (7–11 sept. 2026)", blocked: false, weekIndex: 1 },
];

const payload = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB", "but2-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1", "but2-td-ab": "BUT2-DEV-FI" },
  groupKind: { "but1-td-ab": "td", "but2-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"], "but2-td-ab": ["but2-td-ab"] },
  teacherLabels: { TPA: "THOMAS PAVIE" },
  weekDates: ["2026-08-31", "2026-09-07"],
  weekRows,
  rows: [
    placedRow({ id: "s1", w: 0, d: 0, s: 0, c: "WR101", n: "Écriture", t: "TD", g: ["but1-td-ab"], te: ["TPA"], r: "H.103 (Anglais)" }),
  ],
});

function placement(patch: Partial<Placement> = {}): Placement {
  return {
    session_id: "s1",
    week: 0,
    day: 0,
    slot: 0,
    course_code: "WR101",
    course_name: "Écriture",
    session_type: "TD",
    group_ids: ["but1-td-ab"],
    teacher_codes: ["TPA"],
    room_id: null,
    room_label: null,
    is_eval: false,
    locked: false,
    duration_slots: 1,
    ...patch,
  };
}

function rendre(extra: Record<string, unknown> = {}) {
  const onPlacementUpdated = vi.fn();
  const onError = vi.fn();
  const vue = render(
    <PromoView
      payload={payload}
      route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
      placements={[placement()]}
      onPlacementUpdated={onPlacementUpdated}
      onError={onError}
      setRoute={vi.fn()}
      {...extra}
    />,
  );
  return { ...vue, onPlacementUpdated, onError };
}

/** Jour affiché : le bouton enfoncé du contrôle segmenté des jours (la
 *  grille n'a plus de titre, gabarit v2). */
const titreGrille = () =>
  within(screen.getByRole("group", { name: "Jour affiché" })).getByRole("button", { pressed: true });

describe("PromoView raccourcis clavier", () => {
  it("should go to the next day with → and back with ←", () => {
    rendre();
    expect(titreGrille()).toHaveAccessibleName(/^Lundi/);
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(titreGrille()).toHaveAccessibleName(/^Mardi/);
    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(titreGrille()).toHaveAccessibleName(/^Lundi/);
  });

  it("should roll over to the next week after Friday", () => {
    rendre({ route: testRoute({ vue: "promo", jour: 4, sem: 0 }) });
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(screen.getByRole("heading", { name: /^semaine 3 \(/i })).toBeInTheDocument();
    expect(titreGrille()).toHaveAccessibleName(/^Lundi/);
  });

  it("should change week with Maj + →", () => {
    rendre();
    fireEvent.keyDown(document.body, { key: "ArrowRight", shiftKey: true });
    expect(screen.getByRole("heading", { name: /^semaine 3 \(/i })).toBeInTheDocument();
    expect(titreGrille()).toHaveAccessibleName(/^Lundi/);
  });

  it("should ignore arrows typed inside a field", () => {
    rendre();
    fireEvent.keyDown(screen.getByLabelText("Enseignant"), { key: "ArrowRight" });
    expect(titreGrille()).toHaveAccessibleName(/^Lundi/);
  });
});

describe("PromoView filtres mémorisés", () => {
  it("should restore the chosen year after a reload of the view", () => {
    const { unmount } = rendre();
    fireEvent.click(within(screen.getByRole("group", { name: "Année" })).getByRole("button", { name: "BUT2" }));
    unmount();
    rendre();
    expect(within(screen.getByRole("group", { name: "Année" })).getByRole("button", { name: "BUT2" })).toHaveAttribute("aria-pressed", "true");
    // Un seul filtre : il se défait d'un clic sur « Toutes », pas de « Tout afficher ».
    expect(screen.queryByRole("button", { name: /tout afficher/i })).not.toBeInTheDocument();
  });

  it("should reset every filter with « Tout afficher »", () => {
    rendre();
    fireEvent.click(within(screen.getByRole("group", { name: "Année" })).getByRole("button", { name: "BUT2" }));
    fireEvent.change(screen.getByLabelText("Enseignant"), { target: { value: "TPA" } });
    fireEvent.click(screen.getByRole("button", { name: /tout afficher/i }));
    expect(within(screen.getByRole("group", { name: "Année" })).getByRole("button", { name: "Toutes" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Enseignant")).toHaveValue("");
  });
});

describe("PromoView carte de séance", () => {
  it("should show the teacher's short name, the full name on hover, and the short room", () => {
    rendre();
    const table = screen.getByRole("table");
    const prof = within(table).getByText("T. Pavie");
    expect(prof).toHaveAttribute("title", "Thomas Pavie");
    expect(within(table).getByText("H.103")).toBeInTheDocument();
  });

  it("should name its actions for assistive technologies", () => {
    rendre();
    expect(screen.getByRole("button", { name: "Modifier WR101" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer WR101 du planning" })).toBeInTheDocument();
  });
});

describe("PromoView annuler un déplacement", () => {
  beforeEach(() => {
    vi.mocked(performMove).mockReset();
    vi.mocked(performMove).mockResolvedValue(true);
  });

  const dataTransfer = { effectAllowed: "move", setData: vi.fn(), getData: vi.fn() };

  it("should offer « Annuler » after a drop, and move the session back to its origin", async () => {
    const { onPlacementUpdated, onError } = rendre();
    const chip = within(screen.getByRole("table")).getByText("WR101").closest("[draggable]") as HTMLElement;
    fireEvent.dragStart(chip, { dataTransfer });
    // Case vide du créneau 9h30 (colonne de la séance) : déplacement.
    const ligne = screen.getByRole("rowheader", { name: "9h30–11h" }).closest("tr") as HTMLElement;
    const cible = ligne.querySelectorAll("td")[0] as HTMLElement;
    fireEvent.dragOver(cible, { dataTransfer });
    fireEvent.drop(cible, { dataTransfer });

    await waitFor(() => expect(performMove).toHaveBeenCalledTimes(1));
    expect(vi.mocked(performMove).mock.calls[0]![1]).toEqual({ week: 0, day: 0, slot: 1 });
    const annuler = await screen.findByRole("button", { name: /^annuler$/i });
    expect(screen.getByText(/WR101 déplacée : lun\. 31 août 8h → lun\. 31 août 9h30/)).toBeInTheDocument();

    fireEvent.click(annuler);
    await waitFor(() => expect(performMove).toHaveBeenCalledTimes(2));
    expect(vi.mocked(performMove).mock.calls[1]).toEqual([
      "s1",
      { week: 0, day: 0, slot: 0 },
      expect.objectContaining({ session_id: "s1" }),
      onPlacementUpdated,
      onError,
    ]);
  });

  it("should undo with Ctrl + Z", async () => {
    rendre();
    const chip = within(screen.getByRole("table")).getByText("WR101").closest("[draggable]") as HTMLElement;
    fireEvent.dragStart(chip, { dataTransfer });
    const ligne = screen.getByRole("rowheader", { name: "9h30–11h" }).closest("tr") as HTMLElement;
    const cible = ligne.querySelectorAll("td")[0] as HTMLElement;
    fireEvent.drop(cible, { dataTransfer });
    await screen.findByRole("button", { name: /^annuler$/i });

    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    await waitFor(() => expect(performMove).toHaveBeenCalledTimes(2));
  });
});

describe("PromoView semaine partagée (barre supérieure)", () => {
  /** Enveloppe qui tient la semaine comme `App.tsx` : un seul état, lu par
   *  la barre supérieure et par toutes les vues. */
  function AvecSemaine({ onIndex }: { onIndex: (i: number) => void }) {
    const [index, setIndex] = useState(0);
    return (
      <ContexteSemaine.Provider
        value={{
          index,
          setIndex: (i) => {
            onIndex(i);
            setIndex(i);
          },
        }}
      >
        <PromoView
          payload={payload}
          route={testRoute({ vue: "promo", sem: 0, jour: 4 })}
          placements={[placement()]}
          onPlacementUpdated={vi.fn()}
          onError={vi.fn()}
          setRoute={vi.fn()}
        />
      </ContexteSemaine.Provider>
    );
  }

  it("should move the SHARED week with Maj + → / ← and after Friday, without a week navigation of its own", () => {
    const onIndex = vi.fn();
    render(<AvecSemaine onIndex={onIndex} />);
    // Pas de second sélecteur de semaine : c'est la barre supérieure qui l'a.
    expect(screen.queryByRole("group", { name: "Semaine affichée" })).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "ArrowRight", shiftKey: true });
    expect(onIndex).toHaveBeenLastCalledWith(1);
    fireEvent.keyDown(document.body, { key: "ArrowLeft", shiftKey: true });
    expect(onIndex).toHaveBeenLastCalledWith(0);

    // Vendredi + → : lundi de la semaine suivante, dans la semaine partagée.
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(onIndex).toHaveBeenLastCalledWith(1);
    expect(titreGrille()).toHaveAccessibleName(/^Lundi/);
  });
});

describe("PromoView barre d'outils", () => {
  it("should keep the four actions: « Séances à placer » in the toolbar, creation ones with the primary last", () => {
    rendre({ onSeanceChangee: vi.fn() });
    expect(screen.getByRole("button", { name: "Séances à placer" })).toHaveAttribute("aria-pressed", "false");
    // Sans barre supérieure (test), `ActionsDePage` les garde sur place.
    const actions = screen.getByRole("button", { name: "Nouvelle séance" }).parentElement as HTMLElement;
    const noms = within(actions)
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(noms).toEqual(["Nouvel évènement", "Lisser une promo…", "Nouvelle séance"]);
    expect(within(actions).getByRole("button", { name: "Nouvelle séance" })).toHaveClass("btn--primary");
  });

  it("should date each day button in full for assistive technologies", () => {
    rendre();
    const jours = within(screen.getByRole("group", { name: "Jour affiché" })).getAllByRole("button");
    expect(jours.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Lundi 31 août",
      "Mardi 1 sept.",
      "Mercredi 2 sept.",
      "Jeudi 3 sept.",
      "Vendredi 4 sept.",
    ]);
  });
});
