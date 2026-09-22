/**
 * Vue Promo : un TD n'occupe qu'UNE case pour ses deux groupes TP, un CM une
 * seule case pour toute la promo.
 *
 * Demande du 22/09/2026 : « que les TD soient vus comme des TD, ça veut dire
 * que ce soit qu'une case pour les deux groupes […] Pareil pour les CM ».
 *
 * Les colonnes restent les groupes TP (cf. l'en-tête de `PromoView.tsx`) :
 * c'est le niveau le plus fin, celui où deux TP différents peuvent avoir cours
 * au même créneau. On ne fusionne donc qu'à l'AFFICHAGE, créneau par créneau :
 * des colonnes VOISINES, du MÊME parcours, qui montrent EXACTEMENT les mêmes
 * séances ne forment qu'une case.
 *
 * « Exactement les mêmes » est la règle qui garde l'affichage honnête : si le
 * TP A a en plus un autre cours au même créneau (un conflit), les colonnes ne
 * se ressemblent plus et restent séparées — le conflit reste visible au lieu
 * d'être absorbé dans une case commune. Une case vide ne fusionne jamais :
 * chaque colonne vide reste une cible de dépôt distincte.
 */

/**
 * Rend, pour chaque colonne, sa largeur : `n >= 1` pour la première colonne
 * d'une case (qui s'étend sur `n` colonnes), `0` pour une colonne absorbée
 * par la case précédente.
 *
 * `cle(i)` décrit le contenu de la colonne `i` (null = rien à fusionner) ;
 * `parcours(i)` empêche une case de déborder sur le parcours voisin.
 */
export function fusionnerColonnes(
  nombre: number,
  cle: (i: number) => string | null,
  parcours: (i: number) => string,
): number[] {
  const largeurs = new Array<number>(nombre).fill(1);
  let debut = 0;
  while (debut < nombre) {
    const k = cle(debut);
    let fin = debut + 1;
    if (k !== null) {
      while (fin < nombre && cle(fin) === k && parcours(fin) === parcours(debut)) {
        largeurs[fin] = 0;
        fin += 1;
      }
    }
    largeurs[debut] = fin - debut;
    debut = fin;
  }
  return largeurs;
}

/** Clé d'une cellule : les séances qu'elle affiche, dans un ordre stable. */
export function cleSeances(ids: readonly string[]): string | null {
  return ids.length ? [...ids].sort().join("|") : null;
}
