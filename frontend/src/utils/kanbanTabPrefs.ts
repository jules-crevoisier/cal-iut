/**
 * Onglet actif du kanban « Tâches » (Jules, dicté 25/09/2026 : « deux petits
 * boutons qui seraient des onglets : entre les affaires par rapport à
 * l'emploi du temps [...] et les affaires à propos de la plateforme ») —
 * mémorisé pour survivre à un rechargement de page.
 *
 * `localStorage`, même idiome que `utils/preferences.ts` (lecture/écriture
 * dans un `try/catch`, jamais de plantage si le stockage est bloqué —
 * navigation privée, quota) : contrairement à `utils/creerSeancePrefs.ts`
 * (`sessionStorage`, borné à la session), ce réglage doit survivre à la
 * fermeture de l'onglet, pas seulement à un F5.
 */

const CLE = "cal-iut:kanban:onglet:v1";

export type OngletTaches = "edt" | "plateforme";

const DEFAUT: OngletTaches = "edt";

export function lireOngletTaches(): OngletTaches {
  try {
    const brut = window.localStorage.getItem(CLE);
    return brut === "edt" || brut === "plateforme" ? brut : DEFAUT;
  } catch {
    // Navigation privée, stockage bloqué : l'onglet « Emploi du temps »
    // reste affiché par défaut, l'écran reste utilisable.
    return DEFAUT;
  }
}

export function ecrireOngletTaches(valeur: OngletTaches): void {
  try {
    window.localStorage.setItem(CLE, valeur);
  } catch {
    /* réglage perdu à la fermeture, sans conséquence sur l'écran courant */
  }
}
