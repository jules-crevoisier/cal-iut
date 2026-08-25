/**
 * Résout la vraie date d'une (semaine, jour) depuis `payload.weekDates`
 * (lundi ISO de chaque semaine-solveur, calculé côté serveur depuis le
 * calendrier réel — cf. `AcademicCalendar`).
 *
 * Remplace `utils/slots.ts::placementToDate`, qui calculait la date à partir
 * d'un `SEMESTER_BASE` codé en dur (`new Date(2026, 8, 7)`) — faux dès qu'on
 * regarde un autre semestre (S3/S5 démarrent à des dates différentes) ou une
 * semaine après des vacances (le calendrier n'avance pas de 7 jours en 7
 * jours, il saute les semaines bloquées).
 */

import type { AppPayload } from "../types/app";

export function dateForWeekDay(payload: Pick<AppPayload, "weekDates">, week: number, day: number): Date | null {
  const monday = payload.weekDates[week];
  if (!monday) return null;
  const d = new Date(monday + "T00:00:00");
  d.setDate(d.getDate() + day);
  return d;
}

const DATE_FMT = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });

export function formatSessionDate(d: Date | null, fallbackDay: string): string {
  return d ? DATE_FMT.format(d) : fallbackDay;
}

// Compact (pas de jour de semaine : déjà affiché séparément dans les
// en-têtes "Lundi"/"Mardi") — retour utilisateur 11/08/2026 : "afficher des
// date de chaque jour" sur les grilles.
const SHORT_DATE_FMT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });

export function formatShortDate(d: Date | null): string {
  return d ? SHORT_DATE_FMT.format(d) : "";
}
