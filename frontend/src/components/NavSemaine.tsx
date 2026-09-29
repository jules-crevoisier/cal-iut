/**
 * Navigation de semaine des écrans de consultation (Vue Enseignant, TD/TP,
 * Cours, Salle, Salles libres et leurs liens publics) :
 *
 *   [‹]  Semaine 6 · 28 sept.–2 oct. 2026  [›]  [Aujourd'hui]   12 h
 *   ▁▂▅█▃ … (barre des semaines, inchangée)
 *
 * La barre des semaines (`WeekBar`, histogramme de charge) reste telle que
 * les utilisateurs la connaissent ; on lui ajoute ce qui manquait pour
 * « passer à la semaine suivante » sans viser une barre de 30 px : deux
 * flèches, le nom de la semaine en clair et un retour à aujourd'hui.
 *
 * Raccourcis clavier (ignorés pendant une saisie ou avec Ctrl/Alt/Cmd) :
 * ← / → semaine précédente / suivante, T semaine en cours.
 */

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

import type { WeekRow } from "../types/app";
import { decouperLibelleSemaine } from "../utils/planning";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { semaineCalendaireDepuisLundi } from "../utils/weekDisplay";
import { WeekBar } from "./WeekBar";

import "./Planning.css";

interface NavSemaineProps {
  weekRows: WeekRow[];
  selected: number;
  onSelect: (displayIndex: number) => void;
  /** Histogramme de la barre des semaines. */
  countByWeekIndex: Map<number, number>;
  unit?: "creneaux" | "heures";
  /** Appelé en plus de `onSelect` par « Aujourd'hui » (et la touche T) :
   *  la lecture jour par jour y remet aussi le jour du jour. */
  onAujourdhui?: () => void;
  /** Court résumé à droite du nom de la semaine (ex. « 12 h »). */
  resume?: ReactNode;
  /** Contenu poussé à droite de la ligne (actions de la vue). */
  children?: ReactNode;
  /** Désactive les raccourcis (écran qui en a déjà d'autres). */
  sansRaccourcis?: boolean;
}

/** Vrai quand la frappe vise un champ : les flèches y déplacent le curseur,
 *  elles ne doivent pas changer de semaine en même temps. */
function saisieEnCours(cible: EventTarget | null): boolean {
  const el = cible as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "select" || tag === "textarea" || el.isContentEditable;
}

export function NavSemaine({
  weekRows,
  selected,
  onSelect,
  countByWeekIndex,
  unit = "heures",
  onAujourdhui,
  resume,
  children,
  sansRaccourcis = false,
}: NavSemaineProps) {
  const courante = indexSemaineCourante(weekRows);
  const semaine = weekRows[selected];
  const { titre, dates } = decouperLibelleSemaine(semaine?.label ?? `Semaine ${selected + 1}`);
  const semaineCal = semaineCalendaireDepuisLundi(semaine?.monday);
  const premier = selected <= 0;
  const dernier = selected >= weekRows.length - 1;

  // Dernières valeurs lues par l'écouteur clavier sans le réabonner à
  // chaque rendu.
  const etat = useRef({ selected, courante, onSelect, onAujourdhui, n: weekRows.length });
  etat.current = { selected, courante, onSelect, onAujourdhui, n: weekRows.length };

  useEffect(() => {
    if (sansRaccourcis) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      if (saisieEnCours(e.target)) return;
      // Une modale ouverte garde ses touches pour elle.
      if (document.querySelector("[aria-modal='true']")) return;
      const s = etat.current;
      if (e.key === "ArrowLeft" && s.selected > 0) {
        e.preventDefault();
        s.onSelect(s.selected - 1);
      } else if (e.key === "ArrowRight" && s.selected < s.n - 1) {
        e.preventDefault();
        s.onSelect(s.selected + 1);
      } else if (e.key === "t" || e.key === "T") {
        e.preventDefault();
        s.onSelect(s.courante);
        s.onAujourdhui?.();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sansRaccourcis]);

  return (
    <div className="navsemaine">
      <div className="navsemaine-ligne">
        <div className="navsemaine-pas" role="group" aria-label="Changer de semaine">
          <button
            type="button"
            className="btn btn--icon"
            onClick={() => onSelect(selected - 1)}
            disabled={premier}
            aria-label="Semaine précédente"
            title="Semaine précédente (←)"
          >
            <Chevron sens="gauche" />
          </button>
          <div className="navsemaine-libelle" aria-live="polite">
            <strong>{titre}</strong>
            {dates && <span className="navsemaine-dates">{dates}</span>}
            {semaine?.blocked ? (
              <span className="navsemaine-etat">sans cours</span>
            ) : selected === courante ? (
              <span className="navsemaine-etat navsemaine-etat--courante">cette semaine</span>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn--icon"
            onClick={() => onSelect(selected + 1)}
            disabled={dernier}
            aria-label="Semaine suivante"
            title="Semaine suivante (→)"
          >
            <Chevron sens="droite" />
          </button>
        </div>
        <button
          type="button"
          className="btn btn--sm navsemaine-auj"
          onClick={() => {
            onSelect(courante);
            onAujourdhui?.();
          }}
          disabled={selected === courante && !onAujourdhui}
          title="Revenir à la semaine en cours (T)"
        >
          Aujourd'hui
        </button>
        {(resume || semaineCal !== null) && (
          <span className="navsemaine-resume">
            {resume}
            {semaineCal !== null && <span className="navsemaine-cal">sem. calendaire {semaineCal}</span>}
          </span>
        )}
        {children && <div className="navsemaine-extra">{children}</div>}
      </div>
      <WeekBar
        weekRows={weekRows}
        countByWeekIndex={countByWeekIndex}
        selected={selected}
        onSelect={onSelect}
        unit={unit}
      />
    </div>
  );
}

export function Chevron({ sens }: { sens: "gauche" | "droite" | "bas" }) {
  const d = sens === "gauche" ? "M10 3.5 5.5 8l4.5 4.5" : sens === "droite" ? "M6 3.5 10.5 8 6 12.5" : "M3.5 6 8 10.5 12.5 6";
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
