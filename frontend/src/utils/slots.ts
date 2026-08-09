/** Mapping créneaux IUT MMI ↔ horaires / dates calendrier. */

export const SLOT_TIMES = [
  { start: "08:00:00", end: "09:30:00", label: "8h–9h30" },
  { start: "09:30:00", end: "11:00:00", label: "9h30–11h" },
  { start: "11:00:00", end: "12:30:00", label: "11h–12h30" },
  { start: "14:00:00", end: "15:30:00", label: "14h–15h30" },
  { start: "15:30:00", end: "17:00:00", label: "15h30–17h" },
  { start: "17:00:00", end: "18:30:00", label: "17h–18h30" },
] as const;

/** Lundi de la semaine 0 du semestre (référence affichage). */
export const SEMESTER_BASE = new Date(2026, 8, 7);

const DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"];

export function dayName(day: number): string {
  return DAY_NAMES[day] ?? "?";
}

export function slotLabel(slot: number): string {
  return SLOT_TIMES[slot]?.label ?? "?";
}

export function placementToDate(week: number, day: number, slot: number): { start: Date; end: Date } {
  const base = new Date(SEMESTER_BASE);
  base.setDate(base.getDate() + week * 7 + day);

  const [sh, sm] = SLOT_TIMES[slot].start.split(":").map(Number);
  const [eh, em] = SLOT_TIMES[slot].end.split(":").map(Number);

  const start = new Date(base);
  start.setHours(sh, sm, 0, 0);

  const end = new Date(base);
  end.setHours(eh, em, 0, 0);

  return { start, end };
}

export function dateToPlacement(date: Date, displayWeek: number): { week: number; day: number; slot: number } {
  const base = new Date(SEMESTER_BASE);
  base.setDate(base.getDate() + displayWeek * 7);
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

export function weekStartDate(displayWeek: number): Date {
  const d = new Date(SEMESTER_BASE);
  d.setDate(d.getDate() + displayWeek * 7);
  return d;
}
