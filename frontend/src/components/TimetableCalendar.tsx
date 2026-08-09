import { useCallback, useRef } from "react";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { EventDropArg, EventClickArg } from "@fullcalendar/core";
import frLocale from "@fullcalendar/core/locales/fr";

import type { Placement } from "../types";
import { dateToPlacement, weekStartDate } from "../utils/slots";
import { placementsToEvents } from "../utils/events";
import { movePlacement, validateMove } from "../api/client";

interface TimetableCalendarProps {
  placements: Placement[];
  displayWeek: number;
  groupLabels?: Record<string, string>;
  onPlacementUpdated: (p: Placement) => void;
  onSelect: (p: Placement | null) => void;
  onError: (msg: string) => void;
}

export function TimetableCalendar({
  placements,
  displayWeek,
  groupLabels = {},
  onPlacementUpdated,
  onSelect,
  onError,
}: TimetableCalendarProps) {
  const calendarRef = useRef<FullCalendar>(null);
  const events = placementsToEvents(placements, displayWeek, groupLabels);

  const handleEventClick = useCallback(
    (info: EventClickArg) => {
      const sid = info.event.id;
      const p = placements.find((x) => x.session_id === sid) ?? null;
      onSelect(p);
    },
    [placements, onSelect],
  );

  const handleEventDrop = useCallback(
    async (info: EventDropArg) => {
      const sessionId = info.event.id;
      const placement = placements.find((p) => p.session_id === sessionId);
      if (!placement || placement.locked) {
        info.revert();
        return;
      }

      const start = info.event.start;
      if (!start) {
        info.revert();
        return;
      }

      const { week, day, slot } = dateToPlacement(start, displayWeek);

      try {
        const validation = await validateMove(sessionId, {
          week,
          day,
          slot,
          room_id: placement.room_id,
        });

        if (!validation.valid) {
          const force = window.confirm(
            `Conflit détecté :\n${validation.hard_conflicts.join("\n")}\n\nForcer le déplacement ?`,
          );
          if (!force) {
            info.revert();
            return;
          }
          const updated = await movePlacement(sessionId, {
            week,
            day,
            slot,
            room_id: placement.room_id,
            force: true,
          });
          onPlacementUpdated(updated);
          return;
        }

        if (validation.soft_warnings.length > 0) {
          onError(`Avertissement : ${validation.soft_warnings.join(", ")}`);
        }

        const updated = await movePlacement(sessionId, { week, day, slot, room_id: placement.room_id });
        onPlacementUpdated(updated);
      } catch (err) {
        info.revert();
        onError(err instanceof Error ? err.message : "Erreur de déplacement");
      }
    },
    [placements, displayWeek, onPlacementUpdated, onError],
  );

  return (
    <div className="calendar-wrap">
      <FullCalendar
        ref={calendarRef}
        plugins={[timeGridPlugin, interactionPlugin]}
        initialView="timeGridWeek"
        locale={frLocale}
        headerToolbar={false}
        initialDate={weekStartDate(displayWeek)}
        key={displayWeek}
        weekends={false}
        allDaySlot={false}
        slotMinTime="08:00:00"
        slotMaxTime="19:00:00"
        slotDuration="00:30:00"
        snapDuration="01:30:00"
        height="auto"
        expandRows
        nowIndicator={false}
        editable
        eventDurationEditable={false}
        events={events}
        eventClick={handleEventClick}
        eventDrop={handleEventDrop}
        slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
        eventContent={(arg) => (
          <div className="fc-custom-event">
            <strong>{arg.event.title}</strong>
            {arg.event.extendedProps.roomLabel && (
              <span className="fc-event-room">{arg.event.extendedProps.roomLabel}</span>
            )}
            {arg.event.extendedProps.locked && <span className="fc-event-lock">🔒</span>}
          </div>
        )}
      />
      <div className="lunch-marker">Pause déjeuner 12h30 – 14h00</div>
    </div>
  );
}
