import type { EventInput } from "@fullcalendar/core";
import type { Placement } from "../types";
import { shortGroupLabel } from "../utils/years";
import { placementToDate, slotLabel } from "../utils/slots";

const TYPE_COLORS: Record<string, { bg: string; border: string }> = {
  CM: { bg: "#1a3a2a", border: "#3d9970" },
  TD: { bg: "#1a2a3a", border: "#4a90d9" },
  TP: { bg: "#3a2a1a", border: "#d4a017" },
  PTUT: { bg: "#2a1a3a", border: "#9b59b6" },
};

export function placementsToEvents(
  placements: Placement[],
  displayWeek: number,
  groupLabels: Record<string, string> = {},
): EventInput[] {
  return placements
    .filter((p) => p.week === displayWeek)
    .map((p) => {
      const { start, end } = placementToDate(p.week, p.day, p.slot);
      const colors = TYPE_COLORS[p.session_type] ?? { bg: "#2a2a2a", border: "#666" };
      const groupShort = shortGroupLabel(p.group_ids, groupLabels);
      const groupPart = groupShort ? ` · ${groupShort}` : "";

      return {
        id: p.session_id,
        title: `${p.course_code} · ${p.session_type}${groupPart}`,
        start: start.toISOString(),
        end: end.toISOString(),
        editable: !p.locked,
        backgroundColor: colors.bg,
        borderColor: p.is_eval ? "#e74c3c" : colors.border,
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
