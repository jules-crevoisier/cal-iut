/**
 * Semaine complète d'UN parcours, en modale, avec glisser-déposer.
 *
 * Retour utilisateur 29/08/2026 : « on est dans la vue promo, on peut
 * cliquer sur l'intitulé, exemple BUT3-DEV-FC, cela ouvre une modale vue
 * semaine du parcours où l'on peut glisser-déposer les cours, on peut
 * naviguer dans les semaines aussi ».
 *
 * Le manque qu'elle comble : la Vue Promo n'affiche qu'UN jour à la fois
 * (colonnes = groupes), donc son glisser-déposer ne sait déplacer une
 * séance qu'à l'intérieur de ce jour. Il n'existait AUCUN moyen, dans toute
 * l'application, de déplacer un cours d'un jour à un autre. Ici les
 * colonnes sont les 5 jours et les lignes les 6 créneaux : le geste manquant
 * devient le geste naturel.
 *
 * Deux gestes distincts, volontairement :
 * - déposer sur une case VIDE   -> déplacement,
 * - déposer sur une SÉANCE      -> échange des deux places
 *   (`POST /placements/echanger`, qui juge les deux positions finales
 *   ensemble au lieu d'enchaîner deux déplacements forcés).
 */

import { useEffect, useMemo, useState } from "react";
import type { DragEvent as ReactDragEvent } from "react";

import type { Placement } from "../types";
import type { AppPayload, AppRow } from "../types/app";
import { performMove, performSwap } from "../utils/moveSession";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";

const SLOT_COUNT = 6;
const DAYS = [0, 1, 2, 3, 4];

interface ParcoursWeekModalProps {
  payload: AppPayload;
  parcours: string;
  /** Index dans `payload.weekRows` (pas la semaine solveur) : c'est lui qui
   *  sert à naviguer, les semaines bloquées comprises. */
  weekIndex: number;
  placements: Placement[];
  onClose: () => void;
  onPlacementUpdated: (p: Placement) => void;
  onError: (msg: string) => void;
}

export function ParcoursWeekModal({
  payload,
  parcours,
  weekIndex,
  placements,
  onClose,
  onPlacementUpdated,
  onError,
}: ParcoursWeekModalProps) {
  const [semaineAffichee, setSemaineAffichee] = useState(weekIndex);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [cible, setCible] = useState<{ day: number; slot: number } | null>(null);
  const [cibleEchange, setCibleEchange] = useState<string | null>(null);
  const [annonce, setAnnonce] = useState("");

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const solverWeek = payload.weekRows[semaineAffichee]?.weekIndex ?? null;

  // Groupes de ce parcours, cohortes comprises : un CM de promo doit
  // apparaître ici au même titre qu'un TP, sinon la semaine affichée est
  // fausse par omission.
  const groupesDuParcours = useMemo(() => {
    const ids = Object.keys(payload.groupLabels).filter((gid) => payload.groupParcours[gid] === parcours);
    return new Set(ids);
  }, [payload.groupLabels, payload.groupParcours, parcours]);

  const parCase = useMemo(() => {
    const m = new Map<string, AppRow[]>();
    if (solverWeek === null) return m;
    for (const r of payload.rows) {
      if (r.w !== solverWeek) continue;
      if (!r.g.some((gid) => groupesDuParcours.has(gid))) continue;
      const duree = Math.max(1, r.dur || 1);
      for (let k = 0; k < duree; k++) {
        const cle = `${r.d}-${r.s + k}`;
        if (!m.has(cle)) m.set(cle, []);
        m.get(cle)!.push(r);
      }
    }
    return m;
  }, [payload.rows, solverWeek, groupesDuParcours]);

  const bandes = useMemo(() => {
    if (solverWeek === null) return new Map<number, string>();
    const m = new Map<number, string>();
    for (const d of DAYS) {
      if (payload.holidayRows.some((h) => h.w === solverWeek && h.d === d)) m.set(d, "sessiongrid-holiday");
      else if (payload.saeRows.some((s) => s.w === solverWeek && s.d === d)) m.set(d, "sessiongrid-sae");
      else if (payload.eventRows.some((e) => e.w === solverWeek && e.d === d)) m.set(d, "sessiongrid-event");
    }
    return m;
  }, [payload.holidayRows, payload.saeRows, payload.eventRows, solverWeek]);

  const deplacer = async (jour: number, creneau: number) => {
    setCible(null);
    const sessionId = draggingId;
    setDraggingId(null);
    if (!sessionId || solverWeek === null) return;
    const placement = placements.find((p) => p.session_id === sessionId);
    if (!placement) return;
    if (placement.locked) {
      onError("Séance verrouillée : la déverrouiller avant de la déplacer.");
      return;
    }
    if (placement.week === solverWeek && placement.day === jour && placement.slot === creneau) return;
    const ok = await performMove(
      sessionId,
      { week: solverWeek, day: jour, slot: creneau },
      placement,
      onPlacementUpdated,
      onError,
    );
    if (ok) setAnnonce(`${placement.course_code} déplacé ${DAY_LABELS[jour]} ${SLOT_TIMES[creneau].label}.`);
  };

  const echanger = async (cibleId: string) => {
    setCibleEchange(null);
    const sourceId = draggingId;
    setDraggingId(null);
    if (!sourceId || sourceId === cibleId) return;
    const source = placements.find((p) => p.session_id === sourceId);
    const autre = placements.find((p) => p.session_id === cibleId);
    if (!source || !autre) return;
    if (source.locked || autre.locked) {
      onError("Séance verrouillée : la déverrouiller avant d'échanger.");
      return;
    }
    const ok = await performSwap(
      sourceId,
      cibleId,
      source.course_code,
      autre.course_code,
      onPlacementUpdated,
      onError,
    );
    if (ok) setAnnonce(`${source.course_code} et ${autre.course_code} ont échangé leurs places.`);
  };

  const caseHandlers = (jour: number, creneau: number) => ({
    onDragOver: (e: ReactDragEvent) => {
      if (!draggingId) return;
      e.preventDefault();
      if (cible?.day !== jour || cible?.slot !== creneau) setCible({ day: jour, slot: creneau });
    },
    onDragLeave: () => setCible((cur) => (cur?.day === jour && cur?.slot === creneau ? null : cur)),
    onDrop: (e: ReactDragEvent) => {
      e.preventDefault();
      void deplacer(jour, creneau);
    },
  });

  const echangeHandlers = (cibleId: string) =>
    draggingId && draggingId !== cibleId
      ? {
          // `stopPropagation` : sans lui, la case en dessous traiterait AUSSI
          // le dépôt, et ferait un déplacement en plus de l'échange.
          onDragOver: (e: ReactDragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            if (cibleEchange !== cibleId) setCibleEchange(cibleId);
          },
          onDragLeave: () => setCibleEchange((cur) => (cur === cibleId ? null : cur)),
          onDrop: (e: ReactDragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            void echanger(cibleId);
          },
        }
      : {};

  const semaine = payload.weekRows[semaineAffichee];

  return (
    <div className="parcoursmodal-overlay" role="presentation" onClick={onClose}>
      <div
        className="panel parcoursmodal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="parcoursmodal-titre"
        onClick={(e) => e.stopPropagation()}
      >
        <p role="status" aria-live="polite" className="sr-only">
          {annonce}
        </p>
        <div className="parcoursmodal-entete">
          <h3 id="parcoursmodal-titre">
            {parcours} — {semaine?.label ?? `Semaine ${semaineAffichee + 1}`}
          </h3>
          <div className="parcoursmodal-nav">
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setSemaineAffichee((w) => Math.max(0, w - 1))}
              disabled={semaineAffichee === 0}
            >
              ← Semaine précédente
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setSemaineAffichee((w) => Math.min(payload.weekRows.length - 1, w + 1))}
              disabled={semaineAffichee >= payload.weekRows.length - 1}
            >
              Semaine suivante →
            </button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
              Fermer
            </button>
          </div>
        </div>

        <p className="parcoursmodal-aide">
          Glisser une séance sur une case vide la déplace · la glisser sur une autre séance échange leurs places.
        </p>

        <div className="parcoursmodal-corps">
          {solverWeek === null ? (
            <p className="muted">Semaine bloquée (vacances/fermeture) — rien à afficher.</p>
          ) : (
            <table className="parcours-grid">
              <thead>
                <tr>
                  <th className="timecol" />
                  {DAYS.map((d) => {
                    const date = dateForWeekDay(payload, solverWeek, d);
                    return (
                      <th key={d} className={bandes.get(d) ?? ""}>
                        {DAY_LABELS[d]}
                        {date ? ` ${formatShortDate(date)}` : ""}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: SLOT_COUNT }, (_, s) => (
                  <tr key={s}>
                    <td className="timecol">{SLOT_TIMES[s].label}</td>
                    {DAYS.map((d) => {
                      const entrees = parCase.get(`${d}-${s}`) ?? [];
                      const survol = cible?.day === d && cible?.slot === s;
                      return (
                        <td key={d} className={survol ? "dropzone-hover" : ""} {...caseHandlers(d, s)}>
                          {entrees.map((r) => {
                            const source = placements.find((p) => p.session_id === r.id);
                            const glissable = Boolean(source) && !source?.locked;
                            const groupes = r.g.map((g) => payload.groupLabels[g] ?? g).join("/");
                            return (
                              <div
                                key={r.id}
                                draggable={glissable}
                                onDragStart={
                                  glissable
                                    ? (e) => {
                                        e.dataTransfer.effectAllowed = "move";
                                        setDraggingId(r.id);
                                      }
                                    : undefined
                                }
                                onDragEnd={() => {
                                  setDraggingId(null);
                                  setCibleEchange(null);
                                }}
                                {...echangeHandlers(r.id)}
                                className={`promo-chip type-${r.t.toLowerCase()} ${r.ev ? "eval" : ""} ${
                                  glissable ? "promo-chip--draggable" : ""
                                } ${draggingId === r.id ? "dragging" : ""} ${
                                  cibleEchange === r.id ? "swap-target" : ""
                                }`}
                                title={`${r.n || r.c} · ${r.te.map((t) => payload.teacherLabels[t] ?? t).join(", ")}`}
                              >
                                <span className="code">{r.c}</span>
                                <span className="ty">
                                  {r.t}
                                  {r.ev ? " · éval" : ""}
                                  {groupes ? ` · ${groupes}` : ""}
                                </span>
                                {r.r && <span className="rm">{r.r}</span>}
                              </div>
                            );
                          })}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
