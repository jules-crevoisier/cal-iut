/**
 * Index d'affichage (dans `weekRows`, vacances incluses) le plus proche
 * d'une semaine SOLVEUR — liens et recherche ne connaissent que l'index solveur.
 */
import type { AppPayload } from "../types/app";

export function displayIndexForSolverWeek(payload: AppPayload, solverWeek: number | null): number {
  if (solverWeek === null) return 0;
  const idx = payload.weekRows.findIndex((w) => w.weekIndex === solverWeek);
  return idx >= 0 ? idx : 0;
}
