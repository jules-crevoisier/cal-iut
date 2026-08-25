import type { EventInput } from "@fullcalendar/core";
import type { Placement } from "../types";
import { shortGroupLabel } from "../utils/years";
import { placementToDate, slotLabel } from "../utils/slots";

// Même mapping type -> couleur que l'export HTML (`.session.type-CM/TP`,
// `export/templates/timetable.html`) : TD (par défaut) = accent, CM =
// ink-soft (gris neutre), TP = teal. `var(--xxx)` résolu par le navigateur
// contre les tokens du thème (clair/sombre) — pas de couleur figée ici,
// contrairement à l'ancienne palette or/vert/bleu propre au React.
// PTUT n'existe pas côté HTML (catégorie propre à cette vue éditable) :
// teinte dédiée, cohérente avec la palette mais sans réutiliser un token
// déjà porteur d'un autre sens.
const TYPE_COLORS: Record<string, { bg: string; border: string }> = {
  CM: { bg: "color-mix(in srgb, var(--ink-soft) 10%, var(--surface))", border: "var(--ink-soft)" },
  TD: { bg: "color-mix(in srgb, var(--accent) 10%, var(--surface))", border: "var(--accent)" },
  TP: { bg: "color-mix(in srgb, var(--teal) 12%, var(--surface))", border: "var(--teal)" },
  PTUT: { bg: "color-mix(in srgb, #8e44ad 12%, var(--surface))", border: "#8e44ad" },
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
      // Éval : même override que `.session.eval` côté HTML (accent2/copper
      // sur la bordure ET le fond, pas seulement un liseré rouge).
      const evalColors = { bg: "color-mix(in srgb, var(--accent2) 14%, var(--surface))", border: "var(--accent2)" };
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
