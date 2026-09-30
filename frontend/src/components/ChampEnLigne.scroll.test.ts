/**
 * Défilement de Référence → Codes Celcat (30/09/2026) : « petits problèmes
 * de scroll », la barre latérale décrochait en bas de la liste des cours.
 *
 * Cause : l'annonce `aria-live` de chaque champ en ligne (`.sr-only`, en
 * position absolue) avait la PAGE pour bloc conteneur. Dans un tableau qui
 * défile dans sa carte, les annonces des lignes masquées débordaient quand
 * même du document (8 361 px pour un écran de 742). jsdom ne calcule pas de
 * mise en page : on vérifie la règle qui l'empêche.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const lire = (chemin: string) => readFileSync(new URL(chemin, import.meta.url), "utf-8");
const champ = lire("./ChampEnLigne.css");
const codes = lire("../views/CodesCelcat.css");

function regle(css: string, selecteur: string): string {
  const debut = css.indexOf(`${selecteur} {`);
  expect(debut, `règle ${selecteur} introuvable`).toBeGreaterThanOrEqual(0);
  return css.slice(debut, css.indexOf("}", debut));
}

describe("Champ en ligne — ne déborde pas de son tableau", () => {
  it("contient son annonce aria-live (position relative)", () => {
    expect(regle(champ, ".champ-en-ligne-hote")).toMatch(/position:\s*relative/);
  });

  it("Codes Celcat : la carte tient dans l'écran (un seul défilement)", () => {
    expect(regle(codes, ".codes-celcat .panel.carte-tableau.carte-tableau--haute")).toMatch(/max-height:.*100dvh/);
  });
});
