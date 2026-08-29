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
import type { DragEvent as ReactDragEvent } from "react";

import type { AppPayload, AppRow } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { groupLabelWithParcours } from "../utils/years";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";

const SLOT_COUNT = 6;
const ALL_DAYS = [0, 1, 2, 3, 4];

/**
 * Glisser-déposer optionnel — fourni uniquement par la modale semaine par
 * parcours (`ParcoursWeekModal`). Absent partout ailleurs : les vues Groupe
 * et Enseignant restent en lecture seule, comme avant.
 *
 * Deux dépôts distincts et volontairement différents : sur une CASE, la
 * séance se déplace ; sur une SÉANCE, les deux échangent leurs places.
 */
export interface EditionGrille {
  draggingId: string | null;
  cibleCase: { day: number; slot: number } | null;
  cibleEchange: string | null;
  estGlissable: (sessionId: string) => boolean;
  onDebutGlisser: (sessionId: string) => void;
  onFinGlisser: () => void;
  onSurvolCase: (cible: { day: number; slot: number } | null) => void;
  onSurvolSeance: (sessionId: string | null) => void;
  onDeposerCase: (day: number, slot: number) => void;
  onDeposerSeance: (sessionId: string) => void;
}

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
  /** Préfixe chaque groupe de sa promotion (« BUT1 TP A »). Vrai en Vue
   *  Enseignant, où le même libellé de groupe existe dans plusieurs
   *  promotions — cf. `groupLabelWithParcours`. */
  showPromo?: boolean;
  onSelect?: (row: AppRow) => void;
  /** Absent = grille en lecture seule (comportement historique). */
  edition?: EditionGrille;
}

export function SessionGrid({
  payload,
  rows,
  week,
  parcours = "",
  showPac = false,
  split,
  onlyDay = null,
  showPromo = false,
  onSelect,
  edition,
}: SessionGridProps) {
  const [hover, setHover] = useState<{ row: AppRow; x: number; y: number } | null>(null);
  const days = onlyDay === null ? ALL_DAYS : [onlyDay];

  /** Props d'une case : classe de base + zone de dépôt quand la grille est
   *  éditable. Factorisé parce que la grille rend HUIT variantes de case
   *  (séances, sous-colonnes TP, férié, PAC, SAE, événement, jour entier,
   *  vide) — les oublier une par une ferait des trous où le dépôt ne marche
   *  pas, sans que rien ne le signale. */
  const propsCase = (d: number, s: number) => {
    const survol = edition?.cibleCase?.day === d && edition?.cibleCase?.slot === s;
    if (!edition) return { className: "sessiongrid-cell" };
    return {
      className: `sessiongrid-cell${survol ? " dropzone-hover" : ""}`,
      onDragOver: (e: ReactDragEvent) => {
        if (!edition.draggingId) return;
        e.preventDefault();
        if (!survol) edition.onSurvolCase({ day: d, slot: s });
      },
      onDragLeave: () => {
        if (survol) edition.onSurvolCase(null);
      },
      onDrop: (e: ReactDragEvent) => {
        e.preventDefault();
        edition.onDeposerCase(d, s);
      },
    };
  };

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
                  {/* Étiquette DANS la grille, au milieu de la journée — pas
                      sous tout le tableau (retour utilisateur 28/08/2026,
                      relayé depuis Discord : « pourquoi le texte "Pause
                      déjeuner" est en bas, au lieu d'être au centre ? »). */}
                  <td colSpan={days.length} className="sessiongrid-pause-label">
                    Pause déjeuner
                  </td>
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
                      <td key={d} {...propsCase(d, s)}>
                        {/* Wrapper DÉDIÉ pour la mise en page flex (lecture
                            seule : carte(s) étirée(s) sur toute la case) —
                            jamais sur le <td> lui-même. Bug réel trouvé le
                            28/08/2026 (capture à l'appui) : `display: flex`
                            posé directement sur `.sessiongrid-cell` cassait
                            la synchronisation de hauteur entre cellules
                            D'UNE MÊME LIGNE que fait normalement un
                            <table> — chaque colonne se remettait à
                            grandir indépendamment, décalant tout
                            visuellement. */}
                        <div className="sessiongrid-cell-inner">
                          {shared.map((r) => (
                            <SessionBlock key={r.id} row={r} payload={payload} showPromo={showPromo} onSelect={onSelect} onHover={setHover} edition={edition} />
                          ))}
                        </div>
                      </td>
                    );
                  }
                  if (split && (left.length || right.length)) {
                    return (
                      <td key={d} {...propsCase(d, s)}>
                        <div className="sessiongrid-subcols">
                          <div>
                            {left.map((r) => (
                              <SessionBlock key={r.id} row={r} payload={payload} showPromo={showPromo} onSelect={onSelect} onHover={setHover} edition={edition} />
                            ))}
                          </div>
                          <div>
                            {right.map((r) => (
                              <SessionBlock key={r.id} row={r} payload={payload} showPromo={showPromo} onSelect={onSelect} onHover={setHover} edition={edition} />
                            ))}
                          </div>
                        </div>
                      </td>
                    );
                  }
                  if (holiday) {
                    return (
                      <td key={d} {...propsCase(d, s)}>
                        <div className="sessiongrid-holiday">
                          <span className="title">{holiday.kind === "vacances" ? "Vacances" : "Férié"}</span>
                          <span className="label">{holiday.label}</span>
                        </div>
                      </td>
                    );
                  }
                  if (isPacLock) {
                    return (
                      <td key={d} {...propsCase(d, s)}>
                        <div className="sessiongrid-pac">PAC</div>
                      </td>
                    );
                  }
                  if (sae) {
                    return (
                      <td key={d} {...propsCase(d, s)}>
                        <div className="sessiongrid-sae">
                          <span className="title">SAE</span>
                          <span className="codes">{sae.join(", ")}</span>
                        </div>
                      </td>
                    );
                  }
                  if (eventsAtSlot) {
                    return (
                      <td key={d} {...propsCase(d, s)}>
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
                      <td key={d} {...propsCase(d, s)}>
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
                  return <td key={d} {...propsCase(d, s)} />;
                })}
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>

      {hover && (
        <div className="sessiongrid-hover" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <strong>{hover.row.n || hover.row.c}</strong>
          <div>
            {hover.row.c} · {hover.row.t}
            {hover.row.ev ? " · Éval" : ""}
          </div>
          <div>
            Groupe :{" "}
            {showPromo
              ? groupLabelWithParcours(hover.row.g, payload.groupLabels, payload.groupParcours)
              : hover.row.g.map((g) => payload.groupLabels[g] ?? g).join(", ")}
          </div>
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
  showPromo,
  onSelect,
  onHover,
  edition,
}: {
  row: AppRow;
  payload: AppPayload;
  showPromo: boolean;
  onSelect?: (row: AppRow) => void;
  onHover: (v: { row: AppRow; x: number; y: number } | null) => void;
  edition?: EditionGrille;
}) {
  const glissable = Boolean(edition?.estGlissable(row.id));
  const cibleEchange = edition?.cibleEchange === row.id;
  // `stopPropagation` : sans lui, la CASE en dessous traiterait aussi le
  // dépôt, et ferait un déplacement en plus de l'échange.
  const propsEchange =
    edition && edition.draggingId && edition.draggingId !== row.id
      ? {
          onDragOver: (e: ReactDragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            if (!cibleEchange) edition.onSurvolSeance(row.id);
          },
          onDragLeave: () => {
            if (cibleEchange) edition.onSurvolSeance(null);
          },
          onDrop: (e: ReactDragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            edition.onDeposerSeance(row.id);
          },
        }
      : {};
  // Avec la promotion, le libellé COMPLET est gardé (« BUT1 TD AB ») : c'est
  // le préfixe TD/TP qui distingue un groupe de TD d'un groupe de TP, et sans
  // lui « BUT1 AB » ne dit plus de quoi il s'agit.
  const groupShort = showPromo
    ? groupLabelWithParcours(row.g, payload.groupLabels, payload.groupParcours)
    : row.g.map((g) => (payload.groupLabels[g] ?? g).replace(/^(TD|TP|Promo)\s+/i, "").trim()).join("/");
  return (
    <button
      type="button"
      draggable={glissable}
      onDragStart={
        glissable
          ? (e) => {
              e.dataTransfer.effectAllowed = "move";
              edition?.onDebutGlisser(row.id);
            }
          : undefined
      }
      onDragEnd={edition ? () => edition.onFinGlisser() : undefined}
      {...propsEchange}
      className={`sessiongrid-block type-${row.t.toLowerCase()} ${row.ev ? "eval" : ""} ${row.locked ? "locked" : ""}${
        glissable ? " sessiongrid-block--draggable" : ""
      }${edition?.draggingId === row.id ? " dragging" : ""}${cibleEchange ? " swap-target" : ""}`}
      onClick={() => onSelect?.(row)}
      onMouseEnter={(e) => onHover({ row, x: e.clientX, y: e.clientY })}
      onMouseMove={(e) => onHover({ row, x: e.clientX, y: e.clientY })}
      onMouseLeave={() => onHover(null)}
    >
      {/* Nom du cours + salle en tête, tous deux mis en avant — retour
          utilisateur 28/08/2026 (relayé depuis Discord) : « c'est 95% du
          temps pour savoir dans quelle salle je suis » (la salle mérite la
          même importance que le nom) et « WSA501D ça me parle pas » (le nom
          du cours doit primer sur son code). Le code reste affiché, mais
          rétrogradé en petit sous le nom plutôt qu'en tête. */}
      <span className="head">
        <span className="name">{row.n || row.c}</span>
        {/* Salle absente = manque VISIBLE, pas un vide discret. Un CM dont
            aucune grande salle n'était libre reste volontairement sans salle
            (cf. `solver/rooms.py::_pick`) ; encore faut-il le remarquer. */}
        {row.r ? (
          <span className="room">{row.r}</span>
        ) : (
          <span className="room room--absente">salle à définir</span>
        )}
      </span>
      <span className="meta">
        <span className="code">{row.c}</span> · {row.t}
        {groupShort ? ` · ${groupShort}` : ""}
      </span>
    </button>
  );
}
