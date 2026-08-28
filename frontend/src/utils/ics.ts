/**
 * Export .ics — portage direct de `buildIcs`/`downloadIcs` depuis
 * `export/templates/timetable.html`. Générique : sert aussi bien à un
 * enseignant qu'à un groupe étudiant, seule la liste de séances change.
 */

import type { AppRow } from "../types/app";
import { SLOT_TIMES } from "./slots";
import { dateForWeekDay } from "./weekDates";

export interface IcsSession extends AppRow {
  date: Date | null;
}

export function sessionsWithDates(
  payload: { weekDates: string[] },
  rows: AppRow[],
): IcsSession[] {
  return rows
    .map((r) => ({ ...r, date: dateForWeekDay(payload, r.w, r.d) }))
    .sort((a, b) => a.w - b.w || a.d - b.d || a.s - b.s);
}

function icsEscape(text: string): string {
  return String(text).replace(/([,;\\])/g, "\\$1").replace(/\n/g, "\\n");
}

function icsStamp(date: Date, hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date(date);
  d.setHours(h, m, 0, 0);
  const p = (n: number) => String(n).padStart(2, "0");
  // Heure LOCALE sans suffixe Z : les horaires de l'IUT sont des heures
  // locales, les convertir en UTC les décalerait d'une heure selon la
  // période de l'année.
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}T${p(d.getHours())}${p(d.getMinutes())}00`;
}

export function buildIcs(
  items: IcsSession[],
  calendarName: string,
  uidPrefix: string,
  groupLabels: Record<string, string>,
  teacherLabels: Record<string, string>,
): string {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//cal-iut//planning MMI//FR",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    `X-WR-CALNAME:${icsEscape("Planning MMI — " + calendarName)}`,
  ];
  for (const it of items) {
    if (!it.date) continue;
    const end = SLOT_TIMES[Math.min(5, it.s + (it.dur || 1) - 1)].end.slice(0, 5);
    const start = SLOT_TIMES[it.s].start.slice(0, 5);
    const groups = it.g.map((g) => groupLabels[g] || g).join(", ");
    const teachers = it.te.map((t) => teacherLabels[t] || t).join(", ");
    lines.push(
      "BEGIN:VEVENT",
      `UID:${uidPrefix}-${it.w}-${it.d}-${it.s}-${it.c}@cal-iut`,
      `DTSTAMP:${icsStamp(new Date(), "00:00")}`,
      `DTSTART:${icsStamp(it.date, start)}`,
      `DTEND:${icsStamp(it.date, end)}`,
      `SUMMARY:${icsEscape(it.c + (groups ? " — " + groups : ""))}`,
      `LOCATION:${icsEscape(it.r || "")}`,
      `DESCRIPTION:${icsEscape(
        [it.n || it.c, groups && "Groupes : " + groups, teachers && "Enseignant(s) : " + teachers]
          .filter(Boolean)
          .join("\n"),
      )}`,
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}

/** URL du flux .ics ABONNABLE (serveur, `GET /ics/{kind}/{code}.ics`) — à la
 * différence de `downloadIcs` ci-dessous (fichier figé au moment du clic),
 * une appli agenda qui s'abonne à cette URL la re-télécharge périodiquement
 * toute seule (retour utilisateur 28/08/2026, relayé depuis Discord : « pour
 * le ics on pourrait peut-être faire un lien qui s'update automatique ? »).
 * `token` : le même paramètre `t` public que le reste des liens personnels
 * (cf. api/auth.py) — sans lui l'appli agenda se ferait bloquer par le mot
 * de passe partagé à chaque resynchronisation. */
export function subscribeUrl(kind: "prof" | "groupe", code: string, token: string): string {
  const t = token ? `?t=${encodeURIComponent(token)}` : "";
  return `${window.location.origin}/ics/${kind}/${encodeURIComponent(code)}.ics${t}`;
}

export function downloadIcs(
  items: IcsSession[],
  calendarName: string,
  code: string,
  groupLabels: Record<string, string>,
  teacherLabels: Record<string, string>,
): void {
  const blob = new Blob([buildIcs(items, calendarName, code, groupLabels, teacherLabels)], {
    type: "text/calendar;charset=utf-8",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `planning-${code}.ics`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
