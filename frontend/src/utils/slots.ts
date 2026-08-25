/** Mapping créneaux IUT MMI ↔ horaires / dates calendrier. */

export const SLOT_TIMES = [
  { start: "08:00:00", end: "09:30:00", label: "8h–9h30" },
  { start: "09:30:00", end: "11:00:00", label: "9h30–11h" },
  { start: "11:00:00", end: "12:30:00", label: "11h–12h30" },
  { start: "14:00:00", end: "15:30:00", label: "14h–15h30" },
  { start: "15:30:00", end: "17:00:00", label: "15h30–17h" },
  { start: "17:00:00", end: "18:30:00", label: "17h–18h30" },
] as const;

export const DAY_LABELS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"];

export function dayName(day: number): string {
  return DAY_LABELS[day] ?? "?";
}

export function slotLabel(slot: number): string {
  return SLOT_TIMES[slot]?.label ?? "?";
}

/**
 * Lundi réel d'une semaine-solveur, depuis `payload.weekDates` (calculé côté
 * serveur depuis le calendrier académique réel — `AcademicCalendar`).
 *
 * Remplace l'ancien `SEMESTER_BASE` codé en dur (`new Date(2026, 8, 7)`, qui
 * supposait S1 et une progression de 7 jours en 7 jours) : faux dès qu'on
 * affiche un autre semestre (S3/S5 démarrent à d'autres dates) ou une semaine
 * après des vacances (le calendrier saute les semaines bloquées, il n'avance
 * pas uniformément). `weekDates[w]` peut être vide (semaine hors horizon
 * connu) : repli sur une estimation à 7 jours plutôt que planter, uniquement
 * pour ne pas casser l'affichage — ce cas ne devrait pas survenir en usage
 * normal (n_weeks dérivé des placements réels).
 */
function weekMonday(weekDates: string[], week: number): Date {
  const iso = weekDates[week];
  if (iso) return new Date(iso + "T00:00:00");
  const known = weekDates.find(Boolean);
  const knownIndex = known ? weekDates.indexOf(known) : 0;
  const base = known ? new Date(known + "T00:00:00") : new Date(2026, 7, 31);
  base.setDate(base.getDate() + (week - knownIndex) * 7);
  return base;
}

export function placementToDate(
  weekDates: string[],
  week: number,
  day: number,
  slot: number,
): { start: Date; end: Date } {
  const base = weekMonday(weekDates, week);
  base.setDate(base.getDate() + day);

  const [sh, sm] = SLOT_TIMES[slot].start.split(":").map(Number);
  const [eh, em] = SLOT_TIMES[slot].end.split(":").map(Number);

  const start = new Date(base);
  start.setHours(sh, sm, 0, 0);

  const end = new Date(base);
  end.setHours(eh, em, 0, 0);

  return { start, end };
}

export function dateToPlacement(
  weekDates: string[],
  date: Date,
  displayWeek: number,
): { week: number; day: number; slot: number } {
  const base = weekMonday(weekDates, displayWeek);
  base.setHours(0, 0, 0, 0);

  const target = new Date(date);
  target.setSeconds(0, 0);

  const dayOffset = Math.round((target.getTime() - base.getTime()) / (24 * 60 * 60 * 1000));
  const day = Math.max(0, Math.min(4, dayOffset));

  const minutes = target.getHours() * 60 + target.getMinutes();
  let slot = 0;
  let bestDist = Infinity;

  SLOT_TIMES.forEach((s, idx) => {
    const [h, m] = s.start.split(":").map(Number);
    const slotMinutes = h * 60 + m;
    const dist = Math.abs(minutes - slotMinutes);
    if (dist < bestDist) {
      bestDist = dist;
      slot = idx;
    }
  });

  return { week: displayWeek, day, slot };
}

export function weekStartDate(weekDates: string[], displayWeek: number): Date {
  return weekMonday(weekDates, displayWeek);
}
