/**
 * Grille de séances en LECTURE SEULE — portage de `renderGenericCalendar`
 * depuis `export/templates/timetable.html`. Utilisée par les vues Groupe,
 * Enseignant et Promo (contrairement à la Vue Semaine éditable, qui reste sur
 * FullCalendar/TdWeekGrid pour le glisser-déposer).
 *
 * Bandes affichées, par priorité (la première qui s'applique gagne la case) :
 * séance(s) réelle(s) > jour férié/vacances > PAC verrouillé (jeudi PM, FI) >
 * jour SAE sanctuarisé > événement à horaire précis > événement indicatif
 * (jour entier) > case vide.
 */

import { Fragment, useState } from "react";

import type { AppPayload, AppRow } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";

const SLOT_COUNT = 6;
const ALL_DAYS = [0, 1, 2, 3, 4];

interface SessionGridProps {
  payload: AppPayload;
  rows: AppRow[]; // déjà filtrées à la semaine affichée
  week: number; // semaine SOLVEUR (pour les bandes SAE/férié/événement)
  /** Parcours de référence pour les bandes PAC/événement (vide = toutes). */
  parcours?: string;
  showPac?: boolean;
  /** [tpA, tpB] : bascule la colonne TP en 2 sous-colonnes (comme la Vue Semaine). */
  split?: [string, string];
  /** Un seul jour affiché (lecture mobile) ; absent = les 5 jours. */
  onlyDay?: number | null;
  onSelect?: (row: AppRow) => void;
}

export function SessionGrid({
  payload,
  rows,
  week,
  parcours = "",
  showPac = false,
  split,
  onlyDay = null,
  onSelect,
}: SessionGridProps) {
  const [hover, setHover] = useState<{ row: AppRow; x: number; y: number } | null>(null);
  const days = onlyDay === null ? ALL_DAYS : [onlyDay];

  const byCell = new Map<string, AppRow[]>();
  const byCellLeft = new Map<string, AppRow[]>();
  const byCellRight = new Map<string, AppRow[]>();
  for (const r of rows) {
    const dur = Math.max(1, r.dur || 1);
    for (let k = 0; k < dur; k++) {
      const key = `${r.d}-${r.s + k}`;
      if (split && r.t === "TP") {
        if (r.g.includes(split[0])) {
          push(byCellLeft, key, r);
          continue;
        }
        if (r.g.includes(split[1])) {
          push(byCellRight, key, r);
          continue;
        }
      }
      push(byCell, key, r);
    }
  }

  const saeByDay = new Map<number, string[]>();
  for (const s of payload.saeRows) {
    if (s.w !== week) continue;
    if (parcours && s.p !== parcours) continue;
    saeByDay.set(s.d, [...(saeByDay.get(s.d) ?? []), ...s.codes]);
  }
  const holidayByDay = new Map<number, { kind: string; label: string }>();
  for (const h of payload.holidayRows) {
    if (h.w === week && !holidayByDay.has(h.d)) holidayByDay.set(h.d, { kind: h.kind, label: h.label });
  }
  const eventSlotByKey = new Map<string, string[]>();
  for (const e of payload.eventSlotRows) {
    if (e.w !== week) continue;
    if (e.parcours.length && parcours && !e.parcours.includes(parcours)) continue;
    const key = `${e.d}-${e.s}`;
    eventSlotByKey.set(key, [...(eventSlotByKey.get(key) ?? []), e.label]);
  }
  const dayEventByDay = new Map<number, string[]>();
  for (const e of payload.eventRows) {
    if (e.w === week) dayEventByDay.set(e.d, e.labels);
  }

  return (
    <div className="sessiongrid-wrap">
      <table className="sessiongrid">
        <thead>
          <tr>
            <th className="sessiongrid-corner" />
            {days.map((d) => (
              <th key={d}>
                {DAY_LABELS[d]}
                <span className="sessiongrid-daydate"> {formatShortDate(dateForWeekDay(payload, week, d))}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: SLOT_COUNT }, (_, s) => (
            <Fragment key={s}>
              {s === 3 && (
                <tr className="sessiongrid-pause">
                  <td className="sessiongrid-timecell">12h30–14h</td>
                  {days.map((d) => (
                    <td key={d} />
                  ))}
                </tr>
              )}
              <tr>
                <td className="sessiongrid-timecell mono">{SLOT_TIMES[s].label}</td>
                {days.map((d) => {
                  const key = `${d}-${s}`;
                  const shared = byCell.get(key) ?? [];
                  const left = byCellLeft.get(key) ?? [];
                  const right = byCellRight.get(key) ?? [];
                  const isPacLock = showPac && d === 3 && s >= 3;
                  const sae = saeByDay.get(d);
                  const holiday = holidayByDay.get(d);
                  const eventsAtSlot = eventSlotByKey.get(key);
                  const dayEvent = dayEventByDay.get(d);

                  if (shared.length) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        {shared.map((r) => (
                          <SessionBlock key={r.id} row={r} payload={payload} onSelect={onSelect} onHover={setHover} />
                        ))}
                      </td>
                    );
                  }
                  if (split && (left.length || right.length)) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        <div className="sessiongrid-subcols">
                          <div>
                            {left.map((r) => (
                              <SessionBlock key={r.id} row={r} payload={payload} onSelect={onSelect} onHover={setHover} />
                            ))}
                          </div>
                          <div>
                            {right.map((r) => (
                              <SessionBlock key={r.id} row={r} payload={payload} onSelect={onSelect} onHover={setHover} />
                            ))}
                          </div>
                        </div>
                      </td>
                    );
                  }
                  if (holiday) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        <div className="sessiongrid-holiday">
                          <span className="title">{holiday.kind === "vacances" ? "Vacances" : "Férié"}</span>
                          <span className="label">{holiday.label}</span>
                        </div>
                      </td>
                    );
                  }
                  if (isPacLock) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        <div className="sessiongrid-pac">PAC</div>
                      </td>
                    );
                  }
                  if (sae) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        <div className="sessiongrid-sae">
                          <span className="title">SAE</span>
                          <span className="codes">{sae.join(", ")}</span>
                        </div>
                      </td>
                    );
                  }
                  if (eventsAtSlot) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        <div className="sessiongrid-event">
                          {eventsAtSlot.map((e) => (
                            <span key={e} className="label">
                              {e}
                            </span>
                          ))}
                        </div>
                      </td>
                    );
                  }
                  if (dayEvent) {
                    return (
                      <td key={d} className="sessiongrid-cell">
                        <div className="sessiongrid-event">
                          {dayEvent.map((e) => (
                            <span key={e} className="label">
                              {e}
                            </span>
                          ))}
                        </div>
                      </td>
                    );
                  }
                  return <td key={d} className="sessiongrid-cell" />;
                })}
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
      <p className="sessiongrid-lunch">Pause déjeuner 12h30 – 14h00</p>

      {hover && (
        <div className="sessiongrid-hover" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <strong>{hover.row.n || hover.row.c}</strong>
          <div>
            {hover.row.c} · {hover.row.t}
            {hover.row.ev ? " · Éval" : ""}
          </div>
          <div>Groupe : {hover.row.g.map((g) => payload.groupLabels[g] ?? g).join(", ")}</div>
          <div>Prof : {hover.row.te.map((t) => payload.teacherLabels[t] ?? t).join(", ") || "—"}</div>
          <div>Salle : {hover.row.r || "—"}</div>
          <div>
            {DAY_LABELS[hover.row.d]} · {SLOT_TIMES[hover.row.s]?.label}
          </div>
        </div>
      )}
    </div>
  );
}

function push(map: Map<string, AppRow[]>, key: string, row: AppRow): void {
  const list = map.get(key);
  if (list) list.push(row);
  else map.set(key, [row]);
}

function SessionBlock({
  row,
  payload,
  onSelect,
  onHover,
}: {
  row: AppRow;
  payload: AppPayload;
  onSelect?: (row: AppRow) => void;
  onHover: (v: { row: AppRow; x: number; y: number } | null) => void;
}) {
  const groupShort = row.g
    .map((g) => (payload.groupLabels[g] ?? g).replace(/^(TD|TP|Promo)\s+/i, "").trim())
    .join("/");
  return (
    <button
      type="button"
      className={`sessiongrid-block type-${row.t.toLowerCase()} ${row.ev ? "eval" : ""} ${row.locked ? "locked" : ""}`}
      onClick={() => onSelect?.(row)}
      onMouseEnter={(e) => onHover({ row, x: e.clientX, y: e.clientY })}
      onMouseMove={(e) => onHover({ row, x: e.clientX, y: e.clientY })}
      onMouseLeave={() => onHover(null)}
    >
      <span className="code">{row.c}</span>
      <span className="meta">
        {row.t}
        {groupShort ? ` · ${groupShort}` : ""}
      </span>
      {row.r && <span className="room">{row.r}</span>}
    </button>
  );
}
