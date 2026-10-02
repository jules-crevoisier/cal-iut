/**
 * Cartes de séance : une carte ne déborde jamais et ses lignes ne se
 * recouvrent jamais (retour utilisateur 29/09/2026 : textes de deux cartes
 * l'un sur l'autre en Vue TD / TP, nom écrasé sous la 3e ligne en Vue
 * Semaine). jsdom ne met rien en page : on vérifie que les règles qui le
 * garantissent sont bien présentes dans les feuilles de style.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// Lu sur disque : Vitest ne charge pas le CSS (même en `?raw`). Fins de ligne
// ramenées à `\n` : sous Windows (`core.autocrlf`), le fichier arrive en CRLF
// et un sélecteur sur deux lignes n'était plus retrouvé (01/10/2026).
const lire = (chemin: string) => readFileSync(new URL(chemin, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const promoCss = lire("../views/PromoView.css");
const sessionGridCss = lire("./SessionGrid.css");
const tdWeekGridCss = lire("./TdWeekGrid.css");

/** Corps de la première règle dont le sélecteur est exactement `selecteur`. */
function regle(css: string, selecteur: string): string {
  const echappe = selecteur.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = new RegExp(`(?:^|\\n)${echappe}\\s*\\{([^}]*)\\}`).exec(css);
  if (!m) throw new Error(`règle introuvable : ${selecteur}`);
  return m[1];
}

describe("cartes de séance : pas de débordement ni de chevauchement", () => {
  it("SessionGrid : carte rognée, lignes incompressibles, nom sur deux lignes au plus", () => {
    expect(regle(sessionGridCss, ".sessiongrid-block")).toMatch(/overflow:\s*hidden/);
    expect(regle(sessionGridCss, ".sessiongrid-block > *")).toMatch(/flex-shrink:\s*0/);
    const nom = regle(sessionGridCss, ".sessiongrid-block .name");
    expect(nom).toMatch(/-webkit-line-clamp:\s*2/);
    expect(nom).toMatch(/overflow:\s*hidden/);
    for (const s of [".sessiongrid-block .room", ".sessiongrid-block .meta"]) {
      expect(regle(sessionGridCss, s)).toMatch(/text-overflow:\s*ellipsis/);
      expect(regle(sessionGridCss, s)).toMatch(/white-space:\s*nowrap/);
    }
  });

  it("SessionGrid, lien public : la case grandit avec ses cartes (pas de hauteur imposée)", () => {
    const interieur = regle(sessionGridCss, ".read-only-mode .sessiongrid-cell-inner,\n.read-only-mode .sessiongrid-subcols > div");
    expect(interieur).toMatch(/min-height:\s*100%/);
    expect(interieur).not.toMatch(/(^|[^-])height:\s*100%/);
    expect(regle(sessionGridCss, ".read-only-mode .sessiongrid-block")).toMatch(/flex:\s*1 0 auto/);
  });

  it("Vue Semaine : carte assez haute pour trois lignes, lignes incompressibles", () => {
    const carte = regle(tdWeekGridCss, ".td-block");
    expect(carte).toMatch(/overflow:\s*hidden/);
    expect(carte).toMatch(/min-height:\s*5\.25em/);
    expect(regle(tdWeekGridCss, ".td-block > *")).toMatch(/flex-shrink:\s*0/);
    expect(regle(tdWeekGridCss, ".td-block-nom")).toMatch(/text-overflow:\s*ellipsis/);
  });

  it("Vue Promo : carte rognée, lignes incompressibles", () => {
    expect(regle(promoCss, ".promo-chip")).toMatch(/overflow:\s*hidden/);
    expect(regle(promoCss, ".promo-chip > :not(.promo-chip__actions)")).toMatch(/flex-shrink:\s*0/);
  });
});
