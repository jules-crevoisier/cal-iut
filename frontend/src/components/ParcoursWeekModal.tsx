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
 * colonnes sont les 5 jours et les lignes les 6 créneaux : le geste
 * manquant devient le geste naturel.
 *
 * La grille est `SessionGrid`, celle des vues Groupe/Enseignant, rendue
 * éditable (`edition`) — PAS un tableau parallèle. Une copie recommençait à
 * dériver dès le premier jour (retour utilisateur : « le style du tableau
 * dans la popup n'est pas bon [...] il faut toutes les infos sur les cours »)
 * et perdait au passage les cartes complètes, l'infobulle, les bandes
 * férié/PAC/SAE/événement et la pause déjeuner.
 *
 * Deux gestes distincts, volontairement :
 * - déposer sur une CASE   -> déplacement,
 * - déposer sur une SÉANCE -> échange des deux places
 *   (`POST /placements/echanger`, qui juge les deux positions finales
 *   ensemble au lieu d'enchaîner deux déplacements forcés).
 */

import { useEffect, useMemo, useState } from "react";

import type { Placement } from "../types";
import type { AppPayload } from "../types/app";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import { performMove, performSwap } from "../utils/moveSession";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { DayStrip, todayIndex } from "./DayStrip";
import { SessionGrid, type EditionGrille } from "./SessionGrid";

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
  const [cibleCase, setCibleCase] = useState<{ day: number; slot: number } | null>(null);
  const [cibleEchange, setCibleEchange] = useState<string | null>(null);
  const [annonce, setAnnonce] = useState("");
  const narrow = useNarrowScreen();
  const [mobileDay, setMobileDay] = useState(todayIndex());

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const solverWeek = payload.weekRows[semaineAffichee]?.weekIndex ?? null;

  // Groupes de ce parcours, groupe promo compris : un CM de promotion doit
  // apparaître ici au même titre qu'un TP, sinon la semaine affichée est
  // fausse par omission.
  const groupesDuParcours = useMemo(
    () => new Set(Object.keys(payload.groupLabels).filter((gid) => payload.groupParcours[gid] === parcours)),
    [payload.groupLabels, payload.groupParcours, parcours],
  );

  const rowsSemaine = useMemo(
    () =>
      solverWeek === null
        ? []
        : payload.rows.filter((r) => r.w === solverWeek && r.g.some((gid) => groupesDuParcours.has(gid))),
    [payload.rows, solverWeek, groupesDuParcours],
  );

  const placementsParId = useMemo(
    () => new Map(placements.map((p) => [p.session_id, p])),
    [placements],
  );

  const reinitialiserGlisser = () => {
    setDraggingId(null);
    setCibleCase(null);
    setCibleEchange(null);
  };

  const deplacer = async (jour: number, creneau: number) => {
    const sessionId = draggingId;
    reinitialiserGlisser();
    if (!sessionId || solverWeek === null) return;
    const placement = placementsParId.get(sessionId);
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
    const sourceId = draggingId;
    reinitialiserGlisser();
    if (!sourceId || sourceId === cibleId) return;
    const source = placementsParId.get(sourceId);
    const autre = placementsParId.get(cibleId);
    if (!source || !autre) return;
    if (source.locked || autre.locked) {
      onError("Séance verrouillée : la déverrouiller avant d'échanger.");
      return;
    }
    const ok = await performSwap(sourceId, cibleId, source.course_code, autre.course_code, onPlacementUpdated, onError);
    if (ok) setAnnonce(`${source.course_code} et ${autre.course_code} ont échangé leurs places.`);
  };

  const edition: EditionGrille = {
    draggingId,
    cibleCase,
    cibleEchange,
    estGlissable: (id) => {
      const p = placementsParId.get(id);
      return Boolean(p) && !p?.locked;
    },
    onDebutGlisser: setDraggingId,
    onFinGlisser: reinitialiserGlisser,
    onSurvolCase: setCibleCase,
    onSurvolSeance: setCibleEchange,
    onDeposerCase: (d, s) => void deplacer(d, s),
    onDeposerSeance: (id) => void echanger(id),
  };

  const semaine = payload.weekRows[semaineAffichee];
  const derniere = payload.weekRows.length - 1;

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
              onClick={() => setSemaineAffichee((w) => Math.min(derniere, w + 1))}
              disabled={semaineAffichee >= derniere}
            >
              Semaine suivante →
            </button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
              Fermer
            </button>
          </div>
        </div>

        <p className="parcoursmodal-aide">
          Glisser une séance sur une case libre la déplace · la glisser sur une autre séance échange leurs places.
        </p>

        {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

        <div className="parcoursmodal-corps">
          {solverWeek === null ? (
            <p className="muted">Semaine bloquée (vacances/fermeture) — rien à afficher.</p>
          ) : (
            <SessionGrid
              payload={payload}
              rows={rowsSemaine}
              week={solverWeek}
              parcours={parcours}
              showPac={!parcours.includes("FC")}
              onlyDay={narrow ? mobileDay : null}
              showPromo
              edition={edition}
            />
          )}
        </div>
      </div>
    </div>
  );
}
