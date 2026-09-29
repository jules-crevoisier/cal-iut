/**
 * Nom d'enseignant abrégé pour les cases de grille (« T. Pavie »).
 *
 * Les libellés viennent de la maquette dans des casses mélangées (« THOMAS
 * PAVIE », « Thomas CASTELLENGO », « Anne-Laure  Perrone ») : affichés tels
 * quels, en capitales, ils passaient sur deux ou trois lignes dans une
 * colonne TP et faisaient la moitié de la hauteur de la grille (refonte du
 * 29/09/2026). Le nom complet reste disponible au survol (`title`).
 *
 * Règle : si certains mots sont entièrement en capitales et d'autres non, les
 * capitales sont le nom de famille (« Thomas CASTELLENGO ») ; sinon le premier
 * mot est le prénom et le reste le nom (« THOMAS PAVIE », « Marc Nino »).
 */

function casseNom(mot: string): string {
  return mot
    .toLocaleLowerCase("fr")
    .replace(/(^|[-'’\s])(\p{L})/gu, (_, sep: string, lettre: string) => sep + lettre.toLocaleUpperCase("fr"));
}

function initiale(prenom: string): string {
  // « Anne-Laure » -> « A.-L. »
  return prenom
    .split("-")
    .filter(Boolean)
    .map((p) => `${p[0]!.toLocaleUpperCase("fr")}.`)
    .join("-");
}

function estEnCapitales(mot: string): boolean {
  return /\p{L}/u.test(mot) && mot === mot.toLocaleUpperCase("fr") && mot !== mot.toLocaleLowerCase("fr");
}

export function nomCourt(libelle: string): string {
  const mots = libelle.trim().split(/\s+/).filter(Boolean);
  if (mots.length <= 1) return mots[0] ? casseNom(mots[0]) : "";
  const capitales = mots.filter(estEnCapitales);
  let prenoms: string[];
  let noms: string[];
  if (capitales.length > 0 && capitales.length < mots.length) {
    noms = capitales;
    prenoms = mots.filter((m) => !estEnCapitales(m));
  } else {
    prenoms = [mots[0]!];
    noms = mots.slice(1);
  }
  return `${prenoms.map(initiale).join(" ")} ${noms.map(casseNom).join(" ")}`;
}

/** Nom complet lisible (casse normale), pour les infobulles et panneaux. */
export function nomComplet(libelle: string): string {
  return libelle.trim().split(/\s+/).filter(Boolean).map(casseNom).join(" ");
}
