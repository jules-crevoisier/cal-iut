/**
 * Les évènements de planning affichés dans la grille — et SEULEMENT ceux qui
 * concernent qui regarde.
 *
 * Signalement de Romain Delon, relayé par Kyllian Bresson le 09/09/2026 :
 * « sur les lundis, je pense d'un parcours en particulier, les créneaux de
 * rentrée en format texte noir ».
 *
 * LE DÉFAUT. `EnseignantView` appelait `SessionGrid` SANS `parcours`, et le
 * filtre s'écrit :
 *
 *     if (e.parcours.length && parcours && !e.parcours.includes(parcours))
 *
 * Sans `parcours`, la condition est fausse et le filtre ne s'applique
 * jamais : chaque enseignant voyait les rentrées de TOUS les parcours,
 * y compris ceux où il n'enseigne pas. Le lundi 14 septembre porte deux
 * « Rentrée » (BUT2-DEV-FC et BUT2-CREACOM-FC) sur le même créneau, d'où
 * plusieurs lignes empilées dans une case qui n'aurait dû en montrer
 * aucune.
 *
 * POURQUOI UN ENSEMBLE ET NON UNE CHAÎNE. Un enseignant n'a pas UN parcours,
 * il en a autant que de cours qu'il donne. Passer « le » parcours n'aurait
 * pas de sens ; on passe donc ceux réellement présents dans sa semaine, ce
 * qui marche aussi pour la vue Groupe (un seul parcours) sans rien changer.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionGrid } from "./SessionGrid";
import { emptyPayload } from "../test/payloadFixture";

const PAYLOAD = emptyPayload({
  weekDates: ["2026-09-14"],
  eventSlotRows: [
    { w: 0, d: 0, s: 1, label: "9h30–11h00 Rentrée", parcours: ["BUT2-DEV-FC"], room: null },
    { w: 0, d: 0, s: 1, label: "9h30–11h00 Rentrée", parcours: ["BUT2-CREACOM-FC"], room: null },
    { w: 0, d: 1, s: 1, label: "9h30 Réunion", parcours: [], room: null },
  ],
});

function grille(props: Record<string, unknown>) {
  return render(<SessionGrid payload={PAYLOAD} rows={[]} week={0} {...props} />);
}

describe("Évènements de planning dans la grille", () => {
  it("n'affiche pas la rentrée d'un parcours où l'on n'enseigne pas", () => {
    // LE cas de Romain Delon : il n'a aucun cours en BUT2 FC.
    grille({ parcours: ["BUT1"] });

    expect(screen.queryByText(/Rentrée/)).toBeNull();
  });

  it("affiche la rentrée du parcours concerné", () => {
    grille({ parcours: ["BUT2-DEV-FC"] });

    expect(screen.getAllByText(/Rentrée/).length).toBeGreaterThan(0);
  });

  it("n'affiche qu'une ligne quand deux parcours partagent le même libellé", () => {
    // Deux « Rentrée » sur le même créneau, pour deux parcours qu'un même
    // enseignant peut avoir : le lire deux fois n'apprend rien de plus.
    grille({ parcours: ["BUT2-DEV-FC", "BUT2-CREACOM-FC"] });

    expect(screen.getAllByText(/Rentrée/)).toHaveLength(1);
  });

  it("garde les évènements sans parcours, qui concernent tout le monde", () => {
    grille({ parcours: ["BUT1"] });

    expect(screen.getByText(/Réunion/)).toBeTruthy();
  });

  it("sans parcours du tout, tout est affiché — comme avant", () => {
    // Non-régression : les vues qui ne filtrent pas (aperçu global) ne
    // doivent pas se mettre à cacher des évènements.
    grille({});

    expect(screen.getAllByText(/Rentrée/).length).toBeGreaterThan(0);
  });

  it("accepte encore un parcours en chaîne", () => {
    // La vue Groupe passe une chaîne depuis toujours ; changer sa signature
    // en même temps que le reste ferait deux corrections là où une suffit.
    grille({ parcours: "BUT2-DEV-FC" });

    expect(screen.getAllByText(/Rentrée/).length).toBeGreaterThan(0);
  });
});
