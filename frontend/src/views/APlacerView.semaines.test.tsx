/**
 * « À placer » nomme les semaines comme LA GRILLE — libellé et dates —,
 * jamais `indice + 1`.
 *
 * Signalé par Jules Crevoisier le 10/09/2026 : « j'ai une séance à valider en
 * semaine 17 mais je ne la vois pas », puis « des fois l'outil part de la
 * semaine 18 mais l'IUT est fermé ».
 *
 * Deux numérotations coexistaient. Le solveur compte les semaines
 * d'ENSEIGNEMENT, vacances exclues : l'indice 16 est le lundi 11 janvier 2027.
 * La grille affiche les semaines du DÉPARTEMENT, vacances comprises : ce même
 * indice s'y appelle « Semaine 21 (11–15 janv. 2027) ». Cet écran affichait
 * « semaine 17 » — on cherchait la séance dans la « Semaine 17 (14–18 déc.) ».
 * Et le « S18 » du sélecteur manuel désignait le 18 janvier, pas la semaine de
 * Noël que la grille appelle « Semaine 18 ».
 *
 * Les deux symptômes étaient un seul défaut : aucune séance n'a jamais été
 * posée pendant les vacances, les indices du solveur n'en contiennent pas.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SeanceAPlacer } from "../api/client";
import { emptyPayload } from "../test/payloadFixture";
import type { WeekRow } from "../types/app";
import { APlacerView } from "./APlacerView";

// La forme réelle de 2026-2027 autour de Noël (payload de production) : deux
// semaines bloquées, sans indice solveur.
const WEEK_ROWS: WeekRow[] = [
  { monday: "2026-12-14", label: "Semaine 17 (14–18 déc. 2026)", blocked: false, weekIndex: 14 },
  { monday: "2026-12-21", label: "Semaine 18 (21–25 déc. 2026)", blocked: true, weekIndex: null },
  { monday: "2026-12-28", label: "Semaine 19 (28 déc.–1 janv. 2027)", blocked: true, weekIndex: null },
  { monday: "2027-01-04", label: "Semaine 20 (4–8 janv. 2027)", blocked: false, weekIndex: 15 },
  { monday: "2027-01-11", label: "Semaine 21 (11–15 janv. 2027)", blocked: false, weekIndex: 16 },
  { monday: "2027-01-18", label: "Semaine 22 (18–22 janv. 2027)", blocked: false, weekIndex: 17 },
];

function seance(extra: Partial<SeanceAPlacer> = {}): SeanceAPlacer {
  return {
    session_id: "WR306D-S3-TP-1-but2-dev-fi-tp-d",
    course_code: "WR306D",
    course_name: "Référencement",
    session_type: "TP",
    semestre: "S3",
    parcours: "BUT2-DEV-FI",
    annee: "BUT2",
    duration_slots: 1,
    duree_libelle: "1h30",
    group_ids: ["but2-dev-fi-tp-d"],
    groupes_libelles: ["TP D"],
    teacher_codes: ["JLE"],
    enseignants_libelles: ["JOAN LEFEVRE"],
    sequence_order: 1,
    semaines_possibles: [17],
    raison: "",
    placee_provisoirement: false,
    semaine_actuelle: null,
    jour_actuel: null,
    slot_actuel: null,
    ...extra,
  } as SeanceAPlacer;
}

function monter(s: SeanceAPlacer) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        json: async () =>
          String(url).includes("manquantes")
            ? { total_a_placer: 1, total_placees: 0, manquantes: [s], par_parcours: {}, resume: "" }
            : { session_id: s.session_id, creneaux: [], note: null },
      } as Response),
    ),
  );
  render(
    <APlacerView onPlacement={vi.fn()} payload={{ ...emptyPayload(), weekRows: WEEK_ROWS }} variante="panneau" />,
  );
}

describe("APlacerView — semaines nommées comme la grille", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should name the week of a forced placement with the grid label and its dates", async () => {
    monter(seance({ placee_provisoirement: true, semaine_actuelle: 16, jour_actuel: 4, slot_actuel: 1 }));

    fireEvent.click(await screen.findByRole("button", { name: /WR306D/ }));

    expect(await screen.findByText(/Posée en Semaine 21 \(11–15 janv\. 2027\)/)).toBeInTheDocument();
    // L'ancien libellé, celui qui envoyait chercher dans la mauvaise semaine.
    expect(screen.queryByText(/Posée en semaine 17/)).toBeNull();
  });

  it("should offer grid-labelled weeks in the manual picker, with the solver index as value", async () => {
    monter(seance());

    fireEvent.click(await screen.findByRole("button", { name: /WR306D/ }));
    fireEvent.click(await screen.findByRole("button", { name: /choisir un autre créneau/i }));

    const option = await screen.findByRole("option", { name: /Semaine 22 \(18–22 janv\. 2027\) · idéale/ });
    expect((option as HTMLOptionElement).value).toBe("17");
    // Plus de « S18 » à lire comme la semaine de Noël.
    expect(screen.queryByRole("option", { name: /^S18/ })).toBeNull();
  });

  it("should never offer a week when the IUT is closed", async () => {
    monter(seance());

    fireEvent.click(await screen.findByRole("button", { name: /WR306D/ }));
    fireEvent.click(await screen.findByRole("button", { name: /choisir un autre créneau/i }));

    await screen.findByRole("option", { name: /Semaine 20/ });
    expect(screen.queryByRole("option", { name: /Semaine 18 \(21–25 déc/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Semaine 19 \(28 déc/ })).toBeNull();
  });
});
