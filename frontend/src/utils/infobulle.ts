/**
 * Placer une infobulle sans qu'elle sorte de l'écran.
 *
 * Bug signalé le 30/08/2026 : « sur mobile, la boîte d'info qui s'ouvre sort
 * du cadre si t'appuies trop à droite, ce qui est chiant comme je navigue
 * surtout avec mon pouce droit ». L'ancienne position était `left: x + 12`
 * en `position: fixed` — donc au-delà de `largeur écran − 12 − largeur
 * boîte`, la boîte partait hors champ, et sans moyen de la ramener.
 *
 * Deux règles :
 *
 * 1. **Basculer plutôt que déborder.** Trop à droite, la boîte passe à
 *    GAUCHE du doigt ; trop bas, elle passe AU-DESSUS. On garde ainsi le
 *    point touché visible, au lieu de simplement coller la boîte au bord.
 * 2. **Toujours borner.** Après bascule, la position est ramenée de force
 *    dans l'écran : sur un écran très étroit, une boîte de 260 px peut ne
 *    tenir d'aucun côté, et il vaut mieux qu'elle soit lisible que
 *    parfaitement placée.
 */

const MARGE = 12;

export interface PositionInfobulle {
  left: number;
  top: number;
}

export function positionInfobulle(
  x: number,
  y: number,
  largeur = 260,
  hauteur = 170,
): PositionInfobulle {
  // `window` peut manquer au rendu serveur ; on retombe alors sur la
  // position naïve, qui était le comportement d'avant.
  const ecranL = typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerWidth;
  const ecranH = typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerHeight;

  let left = x + MARGE;
  if (left + largeur > ecranL - MARGE) left = x - MARGE - largeur;

  let top = y + MARGE;
  if (top + hauteur > ecranH - MARGE) top = y - MARGE - hauteur;

  return {
    left: Math.max(MARGE, Math.min(left, ecranL - largeur - MARGE)),
    top: Math.max(MARGE, Math.min(top, ecranH - hauteur - MARGE)),
  };
}
