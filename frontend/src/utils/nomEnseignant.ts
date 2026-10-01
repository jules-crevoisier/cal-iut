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

/** Prénoms et noms d'un libellé, selon la règle ci-dessus. */
function decouper(libelle: string): { prenoms: string[]; noms: string[] } {
  const mots = libelle.trim().split(/\s+/).filter(Boolean);
  if (mots.length <= 1) return { prenoms: [], noms: mots };
  const capitales = mots.filter(estEnCapitales);
  if (capitales.length > 0 && capitales.length < mots.length) {
    return { prenoms: mots.filter((m) => !estEnCapitales(m)), noms: capitales };
  }
  return { prenoms: [mots[0]!], noms: mots.slice(1) };
}

export function nomCourt(libelle: string): string {
  const { prenoms, noms } = decouper(libelle);
  if (prenoms.length === 0) return noms[0] ? casseNom(noms[0]) : "";
  return `${prenoms.map(initiale).join(" ")} ${noms.map(casseNom).join(" ")}`;
}

/** Un prénom « KYLLIAN » ou « anne-laure » remis en casse normale ; un
 *  prénom déjà en casse mixte (« McKenzie ») est gardé tel quel. */
function cassePrenom(mot: string): string {
  if (mot !== mot.toLocaleUpperCase("fr") && mot !== mot.toLocaleLowerCase("fr")) return mot;
  return casseNom(mot);
}

/**
 * Prénom et NOM d'un nom complet (onglet « Enseignants & vacataires »,
 * 01/10/2026) — MÊME règle que le serveur
 * (`ingestion/identite_enseignants.py::separer_nom`) : prénom en casse
 * normale, nom en capitales. Un libellé qui n'est que le code rend deux
 * chaînes vides.
 */
export function separerNom(libelle: string, code?: string): { prenom: string; nom: string } {
  const propre = libelle.trim().split(/\s+/).filter(Boolean).join(" ");
  if (!propre || (code && propre.toUpperCase() === code.trim().toUpperCase())) return { prenom: "", nom: "" };
  const { prenoms, noms } = decouper(propre);
  return {
    prenom: prenoms.map(cassePrenom).join(" "),
    nom: noms.join(" ").toLocaleUpperCase("fr"),
  };
}

/** Nom complet lisible (casse normale), pour les infobulles et panneaux. */
export function nomComplet(libelle: string): string {
  return libelle.trim().split(/\s+/).filter(Boolean).map(casseNom).join(" ");
}
