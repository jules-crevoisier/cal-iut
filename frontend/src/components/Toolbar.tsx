/**
 * Barre d'outils de la Vue Semaine (refonte du 29/09/2026, gabarit v2).
 *
 * Une ligne à plat : « Afficher par » (groupe / enseignant / salle), la cible
 * correspondante (année, parcours et groupe ; enseignant ; salle), et le
 * réglage des couleurs à droite. Dessous, le ruban fin des semaines
 * (`WeekBar`). La semaine elle-même se choisit dans la barre supérieure,
 * partagée par toutes les vues ; les raccourcis Maj + ← / → et T agissent
 * sur cette semaine partagée.
 *
 * Le sélecteur « Semestre » a disparu : il ne filtrait rien (seule l'année
 * compte pour la liste des parcours, et elle a déjà son sélecteur).
 */
import { useEffect, useRef } from "react";

import type { ViewMode, YearMeta } from "../types";
import type { GroupMeta, RoomMeta } from "../types";
import type { WeekRow } from "../types/app";
import { nomComplet } from "../utils/nomEnseignant";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { DEFAULT_YEARS } from "../utils/years";
import { WeekBar } from "./WeekBar";
import "./Toolbar.css";

interface ToolbarProps {
  year: number;
  parcours: string;
  years: YearMeta[];
  parcoursList: string[];
  displayWeek: number;
  /** Plus utilisé : la barre supérieure porte la semaine (et son repli). */
  maxWeeks?: number;
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

/** Ce que montre la grille, en clair (« BUT1 · TD AB », « Joan Lefevre »,
 *  « H.101 ») — pour le résumé de la semaine dans la colonne de droite. */
export function libelleCible(o: {
  viewMode: ViewMode;
  parcours: string;
  groupId: string;
  groups: GroupMeta[];
  teacherCode: string;
  teacherLabels?: Record<string, string>;
  roomId: string;
  rooms: RoomMeta[];
}): string {
  if (o.viewMode === "teacher") {
    if (!o.teacherCode) return "Tous les enseignants";
    const nom = o.teacherLabels?.[o.teacherCode];
    return nom ? nomComplet(nom) : o.teacherCode;
  }
  if (o.viewMode === "room") {
    if (!o.roomId) return "Toutes les salles";
    return o.rooms.find((r) => r.id === o.roomId)?.label ?? o.roomId;
  }
  if (!o.groupId) return `${o.parcours} · tous les groupes`;
  return `${o.parcours} · ${o.groups.find((g) => g.id === o.groupId)?.label ?? o.groupId}`;
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
    <>
      {/* Barre d'outils À PLAT (gabarit v2) : QUOI à gauche (afficher par,
          cible), le réglage des couleurs à droite. Plus de carte autour, plus
          de navigation de semaine : la barre supérieure la porte. */}
      <div className="page-outils semaine-outils">
        <div className="semaine-modes-bloc">
          <span className="semaine-modes-titre" aria-hidden="true">
            Afficher par
          </span>
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
        </div>

        <div className="semaine-cible" role="group" aria-label="Planning affiché">
          {parGroupe && (
            <>
              <select
                aria-label="Année"
                title="Année"
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
              <select
                aria-label="Parcours"
                title="Parcours"
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
              <select
                aria-label="Groupe"
                title="Groupe"
                className="semaine-cible-principale"
                value={props.groupId}
                onChange={(e) => props.onGroupChange(e.target.value)}
              >
                <option value="">Tous les groupes</option>
                {filteredGroups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {groupOptionLabel(g, props.groups)}
                  </option>
                ))}
              </select>
            </>
          )}

          {props.viewMode === "teacher" && (
            <select
              aria-label="Enseignant"
              title="Enseignant"
              className="semaine-cible-principale"
              value={props.teacherCode}
              onChange={(e) => props.onTeacherChange(e.target.value)}
            >
              {/* « Tous » empilait 180 séances illisibles : sans choix, la
                  grille laisse place à l'annuaire des enseignants. */}
              <option value="">Choisir un enseignant…</option>
              {teachersTries.map((t) => (
                <option key={t} value={t}>
                  {nomProf(t)}
                </option>
              ))}
            </select>
          )}

          {props.viewMode === "room" && (
            <select
              aria-label="Salle"
              title="Salle"
              className="semaine-cible-principale"
              value={props.roomId}
              onChange={(e) => props.onRoomChange(e.target.value)}
            >
              <option value="">Choisir une salle…</option>
              {props.rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="page-outils-actions">
          <select
            aria-label="Couleurs"
            className="semaine-couleurs"
            value={props.couleursParMatiere ? "matiere" : "type"}
            onChange={(e) => props.onCouleursChange(e.target.value === "matiere")}
          >
            {/* Mêmes libellés que le réglage des liens publics (`App.tsx`,
                `ReglageCouleurs`) : un seul vocabulaire pour un seul réglage. */}
            <option value="type">Couleurs par type</option>
            <option value="matiere">Couleurs par matière</option>
          </select>
        </div>
      </div>

      {/* Ruban des semaines (retour utilisateur 11/08/2026 : « il faut mettre
          les semaines dans la vue semaine aussi ») : fin, sans légende — la
          barre supérieure dit déjà quelle semaine est affichée. */}
      {props.weekRows.length > 0 && (
        <div className="semaine-ruban">
          <span className="semaine-ruban-titre" aria-hidden="true">
            Semaines
          </span>
          <WeekBar
            weekRows={props.weekRows}
            countByWeekIndex={props.weekCounts}
            selected={props.displayWeek}
            onSelect={props.onWeekChange}
            fine
          />
        </div>
      )}
      {/* « Charger données » / « Générer » / « Recalculer tout » retirés
          (retour utilisateur 27/08/2026 : génération toujours faite en CLI). */}
    </>
  );
}
