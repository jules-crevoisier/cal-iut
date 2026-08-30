/**
 * Grille semaine vue TD : 2 colonnes TP par jour.
 * CM / TD = rectangle sur 2 colonnes ; TP = une colonne.
 *
 * Bandes jour (SAE sanctuarisée, férié/vacances, PAC jeudi PM, événement du
 * planning officiel) : mêmes données et même priorité que `SessionGrid`
 * (Groupe/Enseignant/Promo, lecture seule) — même classes CSS
 * (`.sessiongrid-holiday/-pac/-sae/-event`), réutilisées telles quelles.
 *
 * Lecture seule (retour utilisateur 28/08/2026 : « on enlève la
 * possibilité de drag and drop dans vue semaine [...] on veut que cela
 * soit possible dans vue promo par contre »). Le glisser-déposer HTML5 qui
 * vivait ici (via `utils/moveSession.ts::performMove`, ajouté le
 * 11/08/2026) a été retiré ; il vit maintenant dans `PromoView.tsx`.
 * Cliquer une séance ouvre toujours son détail (`onSelect`, panneau
 * latéral) — seul le déplacement disparaît d'ici.
 */
import { Fragment, useMemo, useState } from "react";

import type { GroupMeta, Placement } from "../types";
import type { AppPayload } from "../types/app";
import { dayName, slotLabel, SLOT_TIMES } from "../utils/slots";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";
import { couleursMatiere } from "../utils/couleursMatiere";
import { positionInfobulle } from "../utils/infobulle";
import { usePreferences } from "../utils/preferences";
import { shortGroupLabel } from "../utils/years";

interface TdWeekGridProps {
  placements: Placement[];
  displayWeek: number;
  tdGroupId: string;
  groups: GroupMeta[];
  groupLabels: Record<string, string>;
  onSelect: (p: Placement | null) => void;
  /** Optionnel : sans lui, la grille reste fonctionnelle mais sans bandes
      SAE/férié/PAC/événement (ex. avant le premier chargement de `/app-state`). */
  payload?: AppPayload | null;
  parcours?: string;
  /** Un seul jour affiché (lecture mobile, cf. `DayStrip`) ; absent = les 5 jours. */
  onlyDay?: number | null;
}

interface DayBands {
  holiday: { kind: string; label: string } | undefined;
  sae: string[] | undefined;
  eventsAtSlot: Map<number, string[]>;
  dayEvent: string[] | undefined;
}

interface CellEvent {
  placement: Placement;
  span: boolean;
  tpIndex: 0 | 1 | null;
  dur: number;
}

const DAY_COUNT = 5;
const SLOT_COUNT = 6;

function resolveTpPair(tdGroupId: string, groups: GroupMeta[]): [string, string] | null {
  const td = groups.find((g) => g.id === tdGroupId && g.kind === "td");
  if (!td || td.related_ids.length < 1) return null;
  if (td.related_ids.length === 1) return [td.related_ids[0], td.related_ids[0]];
  return [td.related_ids[0], td.related_ids[1]];
}

function classify(
  placement: Placement,
  tdId: string,
  tpA: string,
  tpB: string,
): CellEvent | null {
  const gids = placement.group_ids;
  const type = placement.session_type;
  const dur = Math.max(1, placement.duration_slots || 1);

  if (type === "CM" || gids.some((id) => id.includes("-promo"))) {
    return { placement, span: true, tpIndex: null, dur };
  }
  if (type === "TD" || gids.includes(tdId)) {
    return { placement, span: true, tpIndex: null, dur };
  }
  if (gids.includes(tpA)) {
    return { placement, span: false, tpIndex: 0, dur };
  }
  if (gids.includes(tpB)) {
    return { placement, span: false, tpIndex: 1, dur };
  }
  return null;
}

export function TdWeekGrid({
  placements,
  displayWeek,
  tdGroupId,
  groups,
  groupLabels,
  onSelect,
  payload,
  parcours = "",
  onlyDay = null,
}: TdWeekGridProps) {
  const [hover, setHover] = useState<{ placement: Placement; x: number; y: number } | null>(null);
  const couleursParMatiere = usePreferences().couleursParMatiere;
  const days = onlyDay === null ? [0, 1, 2, 3, 4] : [onlyDay];
  const tpPair = resolveTpPair(tdGroupId, groups);
  const tpA = tpPair?.[0] ?? "";
  const tpB = tpPair?.[1] ?? "";
  const labelA = groupLabels[tpA] ?? "TP 1";
  const labelB = groupLabels[tpB] ?? "TP 2";
  const showPac = !parcours.includes("FC");

  const bandsByDay = useMemo(() => {
    const byDay: DayBands[] = Array.from({ length: DAY_COUNT }, () => ({
      holiday: undefined,
      sae: undefined,
      eventsAtSlot: new Map<number, string[]>(),
      dayEvent: undefined,
    }));
    if (!payload) return byDay;

    for (const h of payload.holidayRows) {
      if (h.w === displayWeek && h.d < DAY_COUNT && !byDay[h.d].holiday) {
        byDay[h.d].holiday = { kind: h.kind, label: h.label };
      }
    }
    for (const s of payload.saeRows) {
      if (s.w !== displayWeek || s.d >= DAY_COUNT) continue;
      if (parcours && s.p !== parcours) continue;
      byDay[s.d].sae = [...(byDay[s.d].sae ?? []), ...s.codes];
    }
    for (const e of payload.eventSlotRows) {
      if (e.w !== displayWeek || e.d >= DAY_COUNT) continue;
      if (e.parcours.length && parcours && !e.parcours.includes(parcours)) continue;
      const list = byDay[e.d].eventsAtSlot.get(e.s) ?? [];
      list.push(e.label);
      byDay[e.d].eventsAtSlot.set(e.s, list);
    }
    for (const e of payload.eventRows) {
      if (e.w === displayWeek && e.d < DAY_COUNT) byDay[e.d].dayEvent = e.labels;
    }
    return byDay;
  }, [payload, displayWeek, parcours]);

  const grid = useMemo(() => {
    const cells: CellEvent[][][] = Array.from({ length: SLOT_COUNT }, () =>
      Array.from({ length: DAY_COUNT }, () => []),
    );

    for (const p of placements) {
      if (p.week !== displayWeek) continue;
      const event = classify(p, tdGroupId, tpA, tpB);
      if (!event) continue;
      if (p.day < 0 || p.day >= DAY_COUNT || p.slot < 0 || p.slot >= SLOT_COUNT) continue;
      // Retour utilisateur (27/08/2026) : « affiche-le comme 2 blocs de
      // 1h30 » — pas UNE cellule fusionnée (`rowSpan`), mais le MÊME chip
      // répété sur chacun de ses créneaux (`duration_slots`), exactement le
      // patron déjà utilisé par `SessionGrid`/`PromoView` pour ce même cas.
      const dur = Math.max(1, event.dur);
      for (let k = 0; k < dur && p.slot + k < SLOT_COUNT; k++) {
        cells[p.slot + k][p.day].push(event);
      }
    }
    return cells;
  }, [placements, displayWeek, tdGroupId, tpA, tpB]);

  if (!tpPair) {
    return (
      <div className="empty-state">
        <p>Sélectionnez un groupe TD pour la vue 2 colonnes TP.</p>
      </div>
    );
  }

  return (
    <div className="td-grid-wrap">
      <table className={`td-grid${couleursParMatiere ? " couleurs-matiere" : ""}`}>
        <thead>
          <tr>
            <th className="td-grid-corner" scope="col">
              Créneau
            </th>
            {days.map((day) => (
              <th key={day} colSpan={2} scope="col" className="td-grid-dayhead">
                <div>
                  {dayName(day)}
                  {payload && (
                    <span className="td-grid-daydate">
                      {" "}
                      {formatShortDate(dateForWeekDay(payload, displayWeek, day))}
                    </span>
                  )}
                </div>
                <div className="td-grid-tp-labels">
                  <span>{labelA}</span>
                  <span>{labelB}</span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: SLOT_COUNT }, (_, slot) => (
            <Fragment key={slot}>
              {/* Séparateur de pause déjeuner rendu EN LIGNE, entre les
                  créneaux du matin et de l'après-midi (retour utilisateur
                  27/08/2026), même motif que `SessionGrid.tsx`
                  (`.sessiongrid-pause`), juste avec `colSpan=2` par jour
                  (2 colonnes TP ici). */}
              {slot === 3 && (
                <tr className="sessiongrid-pause">
                  <td className="td-grid-slotlabel">12h30–14h</td>
                  {days.map((day) => (
                    <td key={day} colSpan={2} />
                  ))}
                </tr>
              )}
              <tr className={slot === 2 ? "td-grid-before-lunch" : undefined}>
                <th scope="row" className="td-grid-slotlabel">
                  {SLOT_TIMES[slot].label}
                </th>
                {days.map((day) => {
                const events = grid[slot][day];
                const spans = events.filter((e) => e.span);
                const left = events.filter((e) => !e.span && e.tpIndex === 0);
                const right = events.filter((e) => !e.span && e.tpIndex === 1);
                // Un créneau étudiant = soit 1 CM/TD (2 col.), soit TP A | TP B — jamais les deux
                const primarySpan = spans[0];
                const hasSpan = Boolean(primarySpan);
                const conflict = spans.length > 1 || (hasSpan && (left.length > 0 || right.length > 0));

                if (hasSpan) {
                  return (
                    <td
                      key={day}
                      colSpan={2}
                      className={`td-grid-cell td-grid-cell--span${conflict ? " td-grid-cell--conflict" : ""}`}
                    >
                      <SessionBlock
                        key={primarySpan.placement.session_id}
                        event={primarySpan}
                        groupLabels={groupLabels}
                        onSelect={onSelect}
                        onHover={setHover}
                      />
                      {conflict && <span className="td-conflict-flag">conflit</span>}
                    </td>
                  );
                }

                // Bande jour (aucune vraie séance ici) — même priorité que
                // `SessionGrid` : férié/vacances > PAC (jeudi PM, FI) > SAE
                // sanctuarisée > événement à horaire précis > événement
                // indicatif (jour entier).
                if (!left.length && !right.length) {
                  const bands = bandsByDay[day];
                  const isPacLock = showPac && day === 3 && slot >= 3;
                  const eventsHere = bands.eventsAtSlot.get(slot);
                  if (bands.holiday) {
                    return (
                      <td key={day} colSpan={2} className="td-grid-cell">
                        <div className="sessiongrid-holiday">
                          <span className="title">{bands.holiday.kind === "vacances" ? "Vacances" : "Férié"}</span>
                          <span className="label">{bands.holiday.label}</span>
                        </div>
                      </td>
                    );
                  }
                  if (isPacLock) {
                    return (
                      <td key={day} colSpan={2} className="td-grid-cell">
                        <div className="sessiongrid-pac">PAC</div>
                      </td>
                    );
                  }
                  if (bands.sae) {
                    return (
                      <td key={day} colSpan={2} className="td-grid-cell">
                        <div className="sessiongrid-sae">
                          <span className="title">SAE</span>
                          <span className="codes">{bands.sae.join(", ")}</span>
                        </div>
                      </td>
                    );
                  }
                  if (eventsHere) {
                    return (
                      <td key={day} colSpan={2} className="td-grid-cell">
                        <div className="sessiongrid-event">
                          {eventsHere.map((e) => (
                            <span key={e} className="label">
                              {e}
                            </span>
                          ))}
                        </div>
                      </td>
                    );
                  }
                  if (bands.dayEvent) {
                    return (
                      <td key={day} colSpan={2} className="td-grid-cell">
                        <div className="sessiongrid-event">
                          {bands.dayEvent.map((e) => (
                            <span key={e} className="label">
                              {e}
                            </span>
                          ))}
                        </div>
                      </td>
                    );
                  }
                  return <td key={day} colSpan={2} className="td-grid-cell" />;
                }

                return (
                  <Fragment key={day}>
                    <td className="td-grid-cell">
                      {left.map((e) => (
                        <SessionBlock
                          key={e.placement.session_id}
                          event={e}
                          groupLabels={groupLabels}
                          onSelect={onSelect}
                          onHover={setHover}
                        />
                      ))}
                    </td>
                    <td className="td-grid-cell">
                      {right.map((e) => (
                        <SessionBlock
                          key={e.placement.session_id}
                          event={e}
                          groupLabels={groupLabels}
                          onSelect={onSelect}
                          onHover={setHover}
                        />
                      ))}
                    </td>
                  </Fragment>
                );
              })}
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>

      {/* Position bornée à l'écran, cf. `utils/infobulle.ts`. */}
      {hover && (
        <div className="td-hover" style={positionInfobulle(hover.x, hover.y)}>
          <strong>{hover.placement.course_name || hover.placement.course_code}</strong>
          <div>
            {hover.placement.course_code} · {hover.placement.session_type}
            {hover.placement.is_eval ? " · Éval" : ""}
          </div>
          <div>Groupe : {hover.placement.group_ids.map((id) => groupLabels[id] ?? id).join(", ")}</div>
          <div>Prof : {hover.placement.teacher_codes.join(", ") || "—"}</div>
          <div>Salle : {hover.placement.room_label ?? "—"}</div>
          <div>
            {dayName(hover.placement.day)} · {slotLabel(hover.placement.slot)}
          </div>
        </div>
      )}
    </div>
  );
}

function SessionBlock({
  event,
  groupLabels,
  onSelect,
  onHover,
}: {
  event: CellEvent;
  groupLabels: Record<string, string>;
  onSelect: (p: Placement | null) => void;
  onHover: (v: { placement: Placement; x: number; y: number } | null) => void;
}) {
  const p = event.placement;
  const short = shortGroupLabel(p.group_ids, groupLabels);
  const typeClass = p.session_type.toLowerCase();

  return (
    <button
      type="button"
      style={couleursMatiere(p.course_code) as React.CSSProperties}
      className={`td-block type-${typeClass} ${event.span ? "td-block--span" : ""} ${p.is_eval ? "eval" : ""} ${p.locked ? "locked" : ""}`}
      onClick={() => onSelect(p)}
      onMouseEnter={(e) => onHover({ placement: p, x: e.clientX, y: e.clientY })}
      onMouseMove={(e) => onHover({ placement: p, x: e.clientX, y: e.clientY })}
      onMouseLeave={() => onHover(null)}
    >
      <span className="td-block-code">{p.course_code}</span>
      <span className="td-block-meta">
        {p.session_type}
        {short ? ` · ${short}` : ""}
      </span>
      {p.room_label && <span className="td-block-room">{p.room_label}</span>}
      {p.locked && <span className="lockbadge" title="Verrouillée">🔒</span>}
    </button>
  );
}
