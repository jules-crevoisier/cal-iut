/**
 * Barre d'outils de la Vue Semaine (refonte du 29/09/2026).
 *
 * Deux lignes au lieu de sept champs en capitales sur deux lignes :
 * 1. QUOI : année, parcours, « afficher par » (groupe / enseignant / salle)
 *    et la cible correspondante ; le réglage des couleurs à droite.
 * 2. QUAND : semaine précédente / suivante / aujourd'hui, et l'histogramme
 *    des semaines (`WeekBar`), qui a enfin la largeur pour ses libellés.
 *
 * Le sélecteur « Semestre » a disparu : il ne filtrait rien (seule l'année
 * compte pour la liste des parcours, et elle a déjà son sélecteur). Ses
 * props restent acceptées pour ne pas toucher à la logique d'`App.tsx`.
 */
import { useEffect, useRef } from "react";

import type { ViewMode, YearMeta } from "../types";
import type { GroupMeta, RoomMeta } from "../types";
import type { WeekRow } from "../types/app";
import { nomComplet } from "../utils/nomEnseignant";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { DEFAULT_YEARS } from "../utils/years";
import { WeekBar } from "./WeekBar";
import { WeekStepper } from "./WeekStepper";
import "./Toolbar.css";

interface ToolbarProps {
  year: number;
  parcours: string;
  /** Ignoré à l'affichage (cf. en-tête). */
  semestre?: string;
  years: YearMeta[];
  parcoursList: string[];
  displayWeek: number;
  maxWeeks: number;
  weekRows: WeekRow[];
  weekCounts: Map<number, number>;
  viewMode: ViewMode;
  groupId: string;
  teacherCode: string;
  roomId: string;
  groups: GroupMeta[];
  teachers: string[];
  rooms: RoomMeta[];
  loading: boolean;
  /** Noms des enseignants (sinon, seuls les codes sont connus). */
  teacherLabels?: Record<string, string>;
  /** Couleurs par matière : un réglage d'affichage comme les autres, il
   *  appartient à la barre qui les porte tous (retour utilisateur
   *  30/08/2026). */
  couleursParMatiere: boolean;
  onYearChange: (v: number) => void;
  onParcoursChange: (v: string) => void;
  /** Ignoré (cf. en-tête). */
  onSemestreChange?: (v: string) => void;
  onWeekChange: (v: number) => void;
  onViewModeChange: (v: ViewMode) => void;
  onCouleursChange: (parMatiere: boolean) => void;
  onGroupChange: (v: string) => void;
  onTeacherChange: (v: string) => void;
  onRoomChange: (v: string) => void;
}

/** « TD AB (TP A, TP B + CM) » : ce que contient vraiment la vue du groupe. */
function groupOptionLabel(g: GroupMeta, all: GroupMeta[]): string {
  if (g.kind === "td" && g.related_ids.length) {
    const tpLabels = g.related_ids.map((id) => all.find((x) => x.id === id)?.label ?? id).join(", ");
    return `${g.label} (${tpLabels} + CM)`;
  }
  if (g.kind === "promo") {
    return `${g.label} (CM seulement)`;
  }
  return `${g.label} (${g.kind.toUpperCase()})`;
}

const MODES: { id: ViewMode; label: string }[] = [
  { id: "group", label: "Groupe" },
  { id: "teacher", label: "Enseignant" },
  { id: "room", label: "Salle" },
];

export function Toolbar(props: ToolbarProps) {
  const years = props.years.length ? props.years : DEFAULT_YEARS;
  const yearMeta = years.find((y) => y.id === props.year) ?? years[0];
  const parcoursForYear = yearMeta?.parcours?.length
    ? yearMeta.parcours
    : props.parcoursList.filter((p) => p === `BUT${props.year}` || p.startsWith(`BUT${props.year}-`));

  const filteredGroups = props.groups
    .filter((g) => g.parcours === props.parcours)
    .filter((g) => g.kind === "td" || g.kind === "promo")
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "td" ? -1 : 1;
      return a.label.localeCompare(b.label, "fr");
    });
  const nomProf = (code: string) =>
    props.teacherLabels?.[code] ? `${nomComplet(props.teacherLabels[code]!)} (${code})` : code;
  const teachersTries = [...props.teachers].sort((a, b) => nomProf(a).localeCompare(nomProf(b), "fr"));
  // Raccourcis (mêmes touches que la Vue Promo) : Maj + ← / → change de
  // semaine, T revient à la semaine en cours. Ignorés pendant une saisie ou
  // quand une fenêtre est ouverte.
  const clavier = useRef<(e: KeyboardEvent) => void>(() => undefined);
  clavier.current = (e: KeyboardEvent) => {
    const cible = e.target instanceof HTMLElement ? e.target : null;
    if (cible?.closest("input, select, textarea, [contenteditable='true']")) return;
    if (document.querySelector("[role='dialog'], [role='alertdialog']")) return;
    if (e.ctrlKey || e.metaKey || e.altKey || !props.weekRows.length) return;
    if (e.shiftKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      e.preventDefault();
      const suivante = props.displayWeek + (e.key === "ArrowLeft" ? -1 : 1);
      if (suivante >= 0 && suivante < props.weekRows.length) props.onWeekChange(suivante);
    } else if (!e.shiftKey && (e.key === "t" || e.key === "T")) {
      props.onWeekChange(indexSemaineCourante(props.weekRows));
    }
  };
  useEffect(() => {
    const ecoute = (e: KeyboardEvent) => clavier.current(e);
    document.addEventListener("keydown", ecoute);
    return () => document.removeEventListener("keydown", ecoute);
  }, []);

  // Année et parcours ne servent qu'à la vue par groupe : en vue enseignant
  // ou salle, ils ne changeaient rien à la grille et semaient le doute.
  const parGroupe = props.viewMode === "group";

  return (
    <div className="panel semaine-barre">
      <div className="semaine-barre-ligne">
        <div className="semaine-modes" role="group" aria-label="Afficher le planning par">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={props.viewMode === m.id ? "active" : undefined}
              aria-pressed={props.viewMode === m.id}
              onClick={() => props.onViewModeChange(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>

        {parGroupe && (
          <>
            <label className="semaine-champ">
              <span>Année</span>
              <select
                value={props.year}
                onChange={(e) => props.onYearChange(Number(e.target.value))}
                disabled={props.loading}
              >
                {years.map((y) => (
                  <option key={y.id} value={y.id}>
                    {y.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="semaine-champ">
              <span>Parcours</span>
              <select
                value={props.parcours}
                onChange={(e) => props.onParcoursChange(e.target.value)}
                disabled={props.loading}
              >
                {parcoursForYear.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className="semaine-champ">
              <span>Groupe</span>
              <select value={props.groupId} onChange={(e) => props.onGroupChange(e.target.value)}>
                <option value="">Tous</option>
                {filteredGroups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {groupOptionLabel(g, props.groups)}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}

        {props.viewMode === "teacher" && (
          <label className="semaine-champ">
            <span>Enseignant</span>
            <select value={props.teacherCode} onChange={(e) => props.onTeacherChange(e.target.value)}>
              {/* « Tous » empilait 180 séances illisibles : on demande un choix. */}
              <option value="">Choisir un enseignant…</option>
              {teachersTries.map((t) => (
                <option key={t} value={t}>
                  {nomProf(t)}
                </option>
              ))}
            </select>
          </label>
        )}

        {props.viewMode === "room" && (
          <label className="semaine-champ">
            <span>Salle</span>
            <select value={props.roomId} onChange={(e) => props.onRoomChange(e.target.value)}>
              <option value="">Choisir une salle…</option>
              {props.rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="semaine-barre-ligne">
        {props.weekRows.length > 0 ? (
          <>
            <WeekStepper
              weekRows={props.weekRows}
              selected={props.displayWeek}
              onSelect={props.onWeekChange}
              raccourcis
            />
            <div className="semaine-weekbar">
              <WeekBar
                weekRows={props.weekRows}
                countByWeekIndex={props.weekCounts}
                selected={props.displayWeek}
                onSelect={props.onWeekChange}
              />
            </div>
          </>
        ) : (
          // Repli avant le premier chargement de `/app-state` (pas encore de
          // `weekRows` : la `WeekBar` n'aurait rien à afficher).
          <label className="semaine-champ">
            <span>Semaine</span>
            <select value={props.displayWeek} onChange={(e) => props.onWeekChange(Number(e.target.value))}>
              {Array.from({ length: props.maxWeeks }, (_, i) => (
                <option key={i} value={i}>
                  Semaine {i + 1}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="semaine-champ semaine-couleurs">
          <span>Couleurs</span>
          <select
            value={props.couleursParMatiere ? "matiere" : "type"}
            onChange={(e) => props.onCouleursChange(e.target.value === "matiere")}
          >
            <option value="type">Par type de séance</option>
            <option value="matiere">Par matière</option>
          </select>
        </label>
      </div>
      {/* « Charger données » / « Générer » / « Recalculer tout » retirés
          (retour utilisateur 27/08/2026 : génération toujours faite en CLI). */}
    </div>
  );
}
