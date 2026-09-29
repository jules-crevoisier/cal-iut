import type { EventInput } from "@fullcalendar/core";
import type { Placement } from "../types";
import { shortGroupLabel } from "../utils/years";
import { placementToDate, slotLabel } from "../utils/slots";

// Aplats pastel de la direction « Lumière / Nuit » (mêmes jetons que les
// cartes de la Vue Promo : `--cm-*`, `--td-*`, `--tp-*`, `--ev-*`), résolus
// par le navigateur selon le thème. Le texte prend `--*-fg` via la classe
// `type-*` (cf. `TimetableCalendar.css`). PTUT (propre à cette vue) : gris.
const TYPE_COLORS: Record<string, { bg: string; border: string }> = {
  CM: { bg: "var(--cm-bg)", border: "var(--cm-bd)" },
  TD: { bg: "var(--td-bg)", border: "var(--td-bd)" },
  TP: { bg: "var(--tp-bg)", border: "var(--tp-bd)" },
  PTUT: { bg: "var(--cm-bg)", border: "var(--cm-bd)" },
};

export function placementsToEvents(
  placements: Placement[],
  displayWeek: number,
  weekDates: string[],
  groupLabels: Record<string, string> = {},
): EventInput[] {
  return placements
    .filter((p) => p.week === displayWeek)
    .map((p) => {
      const { start, end } = placementToDate(weekDates, p.week, p.day, p.slot);
      const colors = TYPE_COLORS[p.session_type] ?? { bg: "var(--surface-2)", border: "var(--border)" };
      // Éval / SAE : aplat ambre (`--ev-*`), fond ET bord.
      const evalColors = { bg: "var(--ev-bg)", border: "var(--ev-bd)" };
      const resolved = p.is_eval ? evalColors : colors;
      const groupShort = shortGroupLabel(p.group_ids, groupLabels);
      const groupPart = groupShort ? ` · ${groupShort}` : "";

      return {
        id: p.session_id,
        title: `${p.course_code} · ${p.session_type}${groupPart}`,
        start: start.toISOString(),
        end: end.toISOString(),
        editable: !p.locked,
        backgroundColor: resolved.bg,
        borderColor: resolved.border,
        classNames: [
          "session-event",
          `type-${p.session_type.toLowerCase()}`,
          p.locked ? "locked" : "",
          p.is_eval ? "eval" : "",
        ],
        extendedProps: {
          sessionId: p.session_id,
          courseCode: p.course_code,
          courseName: p.course_name,
          sessionType: p.session_type,
          groupIds: p.group_ids,
          roomLabel: p.room_label,
          teacherCodes: p.teacher_codes,
          isEval: p.is_eval,
          locked: p.locked,
          week: p.week,
          day: p.day,
          slot: p.slot,
        },
      };
    });
}

export function eventTooltip(props: Record<string, unknown>): string {
  const teachers = (props.teacherCodes as string[])?.join(", ") ?? "";
  const room = (props.roomLabel as string) ?? "—";
  const groups = (props.groupIds as string[])?.join(", ") ?? "";
  const slot = slotLabel(props.slot as number);
  return [
    props.courseName as string,
    `${props.courseCode} · ${props.sessionType}`,
    groups ? `Groupe : ${groups}` : "",
    `Créneau : ${slot}`,
    `Prof : ${teachers}`,
    `Salle : ${room}`,
    props.isEval ? "⚠ Évaluation" : "",
    props.locked ? "🔒 Verrouillé" : "",
  ]
    .filter(Boolean)
    .join("\n");
}
