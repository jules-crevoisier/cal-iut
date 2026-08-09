/**
 * Grille semaine vue TD : 2 colonnes TP par jour.
 * CM / TD = rectangle sur 2 colonnes ; TP = une colonne.
 */
import { Fragment, useMemo, useState } from "react";

import type { GroupMeta, Placement } from "../types";
import { dayName, slotLabel, SLOT_TIMES } from "../utils/slots";
import { shortGroupLabel } from "../utils/years";

interface TdWeekGridProps {
  placements: Placement[];
  displayWeek: number;
  tdGroupId: string;
  groups: GroupMeta[];
  groupLabels: Record<string, string>;
  onSelect: (p: Placement | null) => void;
}

interface CellEvent {
  placement: Placement;
  span: boolean;
  tpIndex: 0 | 1 | null;
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

  if (type === "CM" || gids.some((id) => id.includes("-promo"))) {
    return { placement, span: true, tpIndex: null };
  }
  if (type === "TD" || gids.includes(tdId)) {
    return { placement, span: true, tpIndex: null };
  }
  if (gids.includes(tpA)) {
    return { placement, span: false, tpIndex: 0 };
  }
  if (gids.includes(tpB)) {
    return { placement, span: false, tpIndex: 1 };
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
}: TdWeekGridProps) {
  const [hover, setHover] = useState<{ placement: Placement; x: number; y: number } | null>(null);
  const tpPair = resolveTpPair(tdGroupId, groups);
  const tpA = tpPair?.[0] ?? "";
  const tpB = tpPair?.[1] ?? "";
  const labelA = groupLabels[tpA] ?? "TP 1";
  const labelB = groupLabels[tpB] ?? "TP 2";

  const grid = useMemo(() => {
    const cells: CellEvent[][][] = Array.from({ length: SLOT_COUNT }, () =>
      Array.from({ length: DAY_COUNT }, () => []),
    );

    for (const p of placements) {
      if (p.week !== displayWeek) continue;
      const event = classify(p, tdGroupId, tpA, tpB);
      if (!event) continue;
      if (p.day < 0 || p.day >= DAY_COUNT || p.slot < 0 || p.slot >= SLOT_COUNT) continue;
      cells[p.slot][p.day].push(event);
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
      <table className="td-grid">
        <thead>
          <tr>
            <th className="td-grid-corner" scope="col">
              Créneau
            </th>
            {Array.from({ length: DAY_COUNT }, (_, day) => (
              <th key={day} colSpan={2} scope="col" className="td-grid-dayhead">
                <div>{dayName(day)}</div>
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
            <tr key={slot} className={slot === 2 ? "td-grid-before-lunch" : undefined}>
              <th scope="row" className="td-grid-slotlabel">
                {SLOT_TIMES[slot].label}
              </th>
              {Array.from({ length: DAY_COUNT }, (_, day) => {
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
          ))}
        </tbody>
      </table>

      <p className="lunch-marker">Pause déjeuner 12h30 – 14h00</p>

      {hover && (
        <div className="td-hover" style={{ left: hover.x + 12, top: hover.y + 12 }}>
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
    </button>
  );
}
