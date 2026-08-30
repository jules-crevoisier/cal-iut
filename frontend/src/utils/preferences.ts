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
 * UNE SEULE SOURCE DE VÉRITÉ (corrigé le 30/08/2026, retour utilisateur :
 * « j'ai pas l'impression que cela se mette à jour quand je clique »). La
 * première version laissait chaque grille relire `localStorage` de son côté
 * pendant que le bouton, lui, vivait dans l'état de React : deux sources qui
 * divergent dès que l'écriture échoue (navigation privée, quota) — le
 * réglage changeait à l'écran sans que rien ne se repeigne. Le contexte
 * ci-dessous est désormais le seul point de lecture ; `localStorage` ne sert
 * plus qu'à retrouver la valeur au chargement suivant.
 */

import { createContext, useContext } from "react";

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

/** Valeur courante, partagée par tout l'écran. Fournie une fois dans
 *  `App.tsx` ; c'est elle que lisent les grilles, jamais `localStorage`
 *  directement — sinon un clic peut changer l'une sans l'autre. */
export const ContextePreferences = createContext<Preferences>(DEFAUTS);

export function usePreferences(): Preferences {
  return useContext(ContextePreferences);
}
