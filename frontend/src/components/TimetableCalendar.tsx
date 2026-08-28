import { useCallback, useRef } from "react";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
// Toujours nécessaire même en lecture seule : `eventClick` (clic sur une
// séance pour voir son détail) en dépend, pas seulement le glisser-déposer
// désactivé ci-dessous (`editable={false}`).
import interactionPlugin from "@fullcalendar/interaction";
import type { EventClickArg } from "@fullcalendar/core";
import frLocale from "@fullcalendar/core/locales/fr";

import type { Placement } from "../types";
import { weekStartDate } from "../utils/slots";
import { placementsToEvents } from "../utils/events";

interface TimetableCalendarProps {
  placements: Placement[];
  displayWeek: number;
  weekDates: string[];
  groupLabels?: Record<string, string>;
  onSelect: (p: Placement | null) => void;
}

/** Lecture seule (retour utilisateur 28/08/2026 : « on enlève la
 * possibilité de drag and drop dans vue semaine ») — utilisée pour les
 * vues par enseignant/salle de la Vue Semaine. Le glisser-déposer qui
 * vivait ici (`interactionPlugin`/`editable`/`eventDrop`, via
 * `utils/moveSession.ts::performMove`) a été retiré ; il vit maintenant
 * dans `PromoView.tsx`. Cliquer une séance ouvre toujours son détail. */
export function TimetableCalendar({
  placements,
  displayWeek,
  weekDates,
  groupLabels = {},
  onSelect,
}: TimetableCalendarProps) {
  const calendarRef = useRef<FullCalendar>(null);
  const events = placementsToEvents(placements, displayWeek, weekDates, groupLabels);

  const handleEventClick = useCallback(
    (info: EventClickArg) => {
      const sid = info.event.id;
      const p = placements.find((x) => x.session_id === sid) ?? null;
      onSelect(p);
    },
    [placements, onSelect],
  );

  return (
    <div className="calendar-wrap">
      <FullCalendar
        ref={calendarRef}
        plugins={[timeGridPlugin, interactionPlugin]}
        initialView="timeGridWeek"
        locale={frLocale}
        headerToolbar={false}
        initialDate={weekStartDate(weekDates, displayWeek)}
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
        editable={false}
        events={events}
        eventClick={handleEventClick}
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
