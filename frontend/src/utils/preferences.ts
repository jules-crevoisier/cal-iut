/**
 * Préférences d'affichage, gardées sur l'appareil de la personne.
 *
 * Retour utilisateur 30/08/2026 : « ça serait cool des couleurs pour chaque
 * cours [...] il faut que cela soit une option ; pour les liens des groupes
 * je vois cela comme un popup qui s'affiche et qui demande les préférences,
 * et on stocke cela et on garde en mémoire pour ne pas que l'on redemande à
 * chaque fois ».
 *
 * `localStorage` plutôt qu'un cookie : le réglage ne concerne QUE
 * l'affichage, il n'a aucune raison de partir vers le serveur à chaque
 * requête — un lien enseignant est déjà public, y ajouter un cookie
 * n'apporterait rien et alourdirait chaque appel. Il survit à la fermeture
 * de l'onglet exactement pareil.
 *
 * Le stockage peut ÉCHOUER (navigation privée, cookies bloqués, quota) :
 * chaque accès est donc protégé, et l'échec se traduit par « on garde les
 * valeurs par défaut », jamais par une page cassée.
 */

const CLE = "cal-iut:preferences:v1";

export interface Preferences {
  /** Une couleur par matière plutôt qu'une couleur par type de séance. */
  couleursParMatiere: boolean;
  /** Vrai une fois que la personne a répondu — c'est lui qui évite de
   *  reposer la question à chaque visite, y compris si elle a répondu non. */
  repondu: boolean;
}

const DEFAUTS: Preferences = { couleursParMatiere: false, repondu: false };

export function lirePreferences(): Preferences {
  try {
    const brut = window.localStorage.getItem(CLE);
    if (!brut) return { ...DEFAUTS };
    const lu = JSON.parse(brut) as Partial<Preferences>;
    return {
      couleursParMatiere: Boolean(lu.couleursParMatiere),
      repondu: Boolean(lu.repondu),
    };
  } catch {
    // Navigation privée, stockage bloqué, JSON abîmé : on affiche
    // normalement avec les valeurs par défaut.
    return { ...DEFAUTS };
  }
}

export function ecrirePreferences(patch: Partial<Preferences>): Preferences {
  const suivant = { ...lirePreferences(), ...patch };
  try {
    window.localStorage.setItem(CLE, JSON.stringify(suivant));
  } catch {
    /* réglage perdu à la fermeture, mais l'écran reste utilisable */
  }
  return suivant;
}
