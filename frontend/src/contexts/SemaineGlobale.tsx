/**
 * Semaine affichée, PARTAGÉE par toutes les vues de l'application connectée
 * (refonte du 29/09/2026 : « on choisit la semaine une fois, chaque vue
 * suit »). Avant, chaque vue gardait sa propre semaine : passer de la Vue
 * Promo à la Vue Enseignant ramenait à la semaine en cours, et chaque écran
 * dessinait sa propre barre de navigation.
 *
 * `index` est l'index d'AFFICHAGE dans `payload.weekRows` (semaines
 * bloquées comprises) — jamais l'index solveur (`weekRows[i].weekIndex`).
 *
 * Absent (valeur `null`) sur les liens publics : chaque page y garde sa
 * propre navigation, faute de barre supérieure.
 */

import { createContext, useContext } from "react";

export interface SemaineGlobale {
  index: number;
  setIndex: (index: number) => void;
}

export const ContexteSemaine = createContext<SemaineGlobale | null>(null);

export function useSemaineGlobale(): SemaineGlobale | null {
  return useContext(ContexteSemaine);
}
