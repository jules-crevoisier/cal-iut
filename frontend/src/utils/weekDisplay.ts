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

/**
 * Semaine calendaire ISO-8601 (celle qui contient le jeudi) — retour
 * utilisateur (todo département, Kyllian Bresson) : « indiquer la semaine
 * calendaire en même temps que la semaine universitaire ». Norme
 * indépendante de la numérotation "semaine solveur"/"semaine universitaire"
 * déjà utilisée partout ailleurs dans l'appli (cf. mémoire "Trois
 * numérotations de semaines") — encore une troisième, purement calendaire,
 * qu'on n'affiche donc qu'en complément, jamais en remplacement.
 *
 * Algorithme ISO standard : on cherche le jeudi de la semaine du jour donné,
 * puis on compte le nombre de semaines depuis le premier jeudi de l'année de
 * CE jeudi (pas forcément l'année du jour d'origine — un lundi fin décembre
 * peut appartenir à la semaine 1 de l'année suivante, et réciproquement).
 */
export function isoWeekNumber(date: Date): number {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const jourLundiZero = (d.getUTCDay() + 6) % 7; // lundi=0 … dimanche=6
  d.setUTCDate(d.getUTCDate() - jourLundiZero + 3); // jeudi de cette semaine
  const premierJeudi = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const premierJourLundiZero = (premierJeudi.getUTCDay() + 6) % 7;
  premierJeudi.setUTCDate(premierJeudi.getUTCDate() - premierJourLundiZero + 3);
  return 1 + Math.round((d.getTime() - premierJeudi.getTime()) / (7 * 24 * 3600 * 1000));
}

/**
 * Semaine calendaire depuis le LUNDI réel d'une semaine (`weekRows[].monday`,
 * ISO `yyyy-mm-dd`) — jamais en reparsant le libellé affiché, qui peut être
 * un texte de vacances ("Vacances de Noël") sans date exploitable.
 */
export function semaineCalendaireDepuisLundi(mondayIso: string | null | undefined): number | null {
  if (!mondayIso) return null;
  const d = new Date(mondayIso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return null;
  return isoWeekNumber(d);
}
