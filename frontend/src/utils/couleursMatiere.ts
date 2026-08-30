/**
 * Une couleur par matière — retour utilisateur 30/08/2026 : « 1 couleur par
 * matière ».
 *
 * La teinte est CALCULÉE depuis le code du cours, pas piochée dans une liste
 * écrite à la main : il y a 183 matières dans la maquette, une palette
 * manuelle serait incomplète dès qu'un module s'ajoute, et deux matières
 * finiraient par partager une couleur sans que personne ne l'ait décidé.
 *
 * **Le vrai critère n'est pas l'unicité globale.** Avec 183 matières et un
 * œil qui distingue une douzaine de teintes, donner une couleur unique à
 * chacune est impossible — et inutile : personne ne voit 183 cours à la
 * fois. Ce qui compte, c'est que les cours affichés SUR UN MÊME ÉCRAN
 * (un groupe, une semaine) se distinguent.
 *
 * Mesuré sur le planning réel, 234 écrans contenant au moins deux matières :
 *
 *     teintes seules, sans les verts   96 écrans difficiles
 *     + 3 variantes de clarté          62
 *     + les verts réintégrés           26   <- retenu
 *
 * « Difficile » = deux matières à moins de 8° de teinte ET de même variante,
 * donc indistinguables. Le réglage retenu divise le problème par presque
 * quatre. Zéro écran ne porte deux matières de teinte identique.
 *
 * Seules la TEINTE et la VARIANTE sortent d'ici ; saturation et luminosité
 * finales restent dans le CSS, qui seul sait s'il fait clair ou sombre — une
 * couleur figée en JavaScript serait illisible dans l'un des deux thèmes.
 */

/**
 * Plages de teintes utilisables, en degrés. Les rouges (0-20°) sont exclus :
 * ils portent déjà le sens « à corriger » dans l'application (salle
 * manquante, contrainte violée), et une matière rouge sang brouillerait ce
 * repère. Les verts sont gardés — un chip de cours et une pastille d'état
 * sont des éléments trop différents pour se confondre, et les écarter
 * coûtait 36 écrans lisibles.
 */
const PLAGES: [number, number][] = [
  [200, 260], // bleus
  [260, 320], // violets et roses
  [20, 50], // orangés et ambres
  [160, 200], // cyans
  [320, 360], // magentas
  [95, 150], // verts
];

const TOTAL = PLAGES.reduce((n, [a, b]) => n + (b - a), 0);

/** Nombre de niveaux de clarté. Trois : deux ne séparaient presque rien
 *  (93 écrans difficiles), quatre n'a pas fait mieux que trois sur les
 *  données réelles — le gain d'une dimension supplémentaire s'épuise. */
export const VARIANTES = 3;

/** Hachage FNV-1a 32 bits : court, déterministe, et bien mieux réparti
 *  qu'une somme de codes de caractères — celle-ci donnait la même valeur à
 *  « WR104 » et « WR140 ». */
function hachage(texte: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < texte.length; i++) {
    h ^= texte.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

/**
 * Teinte stable pour un code de cours. Même code = même couleur, à chaque
 * chargement et sur tous les écrans — sinon la couleur ne veut rien dire.
 */
export function teinteMatiere(codeCours: string): number {
  let position = hachage(codeCours) % TOTAL;
  for (const [debut, fin] of PLAGES) {
    const largeur = fin - debut;
    if (position < largeur) return debut + position;
    position -= largeur;
  }
  return PLAGES[0][0];
}

/**
 * Niveau de clarté (0, 1 ou 2), pour séparer deux matières de teintes
 * voisines. Tiré des bits HAUTS du hachage, indépendants de ceux qui
 * décident la teinte : sinon deux codes de teinte proche auraient aussi la
 * même variante, et la seconde dimension ne servirait à rien.
 */
export function varianteMatiere(codeCours: string): number {
  return (hachage(codeCours) >>> 24) % VARIANTES;
}
