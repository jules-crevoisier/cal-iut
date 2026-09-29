import { useEffect, useState } from "react";

import type { AppPayload } from "../types/app";
import { jourOuvreAujourdhui } from "../utils/semaineCourante";
import { displayIndexForSolverWeek } from "../utils/weekDisplay";
import { useNarrowScreen } from "./useNarrowScreen";

/**
 * État commun des écrans de consultation (Enseignant, TD/TP, Cours, Salle) :
 * la semaine affichée (index d'AFFICHAGE dans `weekRows`), le jour lu sur
 * téléphone, et les sauts « aller à telle séance ».
 *
 * La semaine du lien (`sem`) reste prioritaire ; sans elle, on ouvre sur la
 * semaine EN COURS (retour de Jules, 28/09/2026) et, sur téléphone, sur le
 * jour d'aujourd'hui (retour utilisateur 08/09/2026).
 */
export function useConsultation(payload: AppPayload, routeSem: number | null) {
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, routeSem));
  const [jour, setJour] = useState(() => jourOuvreAujourdhui());
  const narrow = useNarrowScreen();

  useEffect(() => {
    if (routeSem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, routeSem));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeSem]);

  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;

  /** Affiche la semaine SOLVEUR `w` (et le jour `d` sur téléphone), puis
   *  ramène la grille à l'écran. */
  const allerA = (w: number, d?: number) => {
    const i = payload.weekRows.findIndex((r) => r.weekIndex === w);
    if (i >= 0) setDisplayWeek(i);
    if (d !== undefined) setJour(d);
    document.getElementById("planning")?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  };

  return {
    displayWeek,
    setDisplayWeek,
    solverWeek,
    jour,
    setJour,
    narrow,
    allerA,
    jourAujourdhui: () => setJour(jourOuvreAujourdhui()),
  };
}
