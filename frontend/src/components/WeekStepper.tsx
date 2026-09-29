/**
 * Semaine affichée + précédente / suivante / aujourd'hui (refonte du
 * 29/09/2026). Complète la `WeekBar` (histogramme, vue d'ensemble de
 * l'année) : celle-ci sert à sauter loin, ce bloc à avancer d'une semaine
 * sans viser une barre de 16 px, et dit en toutes lettres où l'on est.
 *
 * Partagé par la Vue Promo et la Vue Semaine.
 */
import type { ReactNode } from "react";

import { useSemaineGlobale } from "../contexts/SemaineGlobale";

import type { WeekRow } from "../types/app";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { semaineCalendaireDepuisLundi } from "../utils/weekDisplay";
import "./WeekStepper.css";

interface WeekStepperProps {
  weekRows: WeekRow[];
  /** Index d'AFFICHAGE dans `weekRows`. */
  selected: number;
  onSelect: (displayIndex: number) => void;
  /** Remplace le simple saut à la semaine en cours (ex. Vue Promo : semaine
   *  ET jour d'aujourd'hui). */
  onToday?: () => void;
  /** Déjà sur aujourd'hui : le bouton est grisé. Par défaut : semaine en cours. */
  estAujourdhui?: boolean;
  /** Raccourcis rappelés dans les infobulles, quand la vue les gère. */
  raccourcis?: boolean;
  /** Texte ajouté après le libellé (ex. nombre de séances). */
  complement?: ReactNode;
  /** Affiché même dans l'application connectée (ex. une modale qui a sa
   *  propre semaine) ; sinon la barre supérieure en tient lieu. */
  toujours?: boolean;
}

/** « Semaine 6 (28 sept.–2 oct. 2026) » -> ["Semaine 6", "28 sept.–2 oct. 2026"]. */
function decouper(label: string): [string, string] {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(label);
  return m ? [m[1]!, m[2]!] : [label, ""];
}

function Chevron({ sens }: { sens: "gauche" | "droite" }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d={sens === "gauche" ? "M10 3 5 8l5 5" : "M6 3l5 5-5 5"}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function WeekStepper({
  weekRows,
  selected,
  onSelect,
  onToday,
  estAujourdhui,
  raccourcis = false,
  complement,
  toujours = false,
}: WeekStepperProps) {
  const barreGlobale = useSemaineGlobale() !== null;
  const ligne = weekRows[selected];
  const indexAujourdhui = indexSemaineCourante(weekRows);
  const surAujourdhui = estAujourdhui ?? selected === indexAujourdhui;
  const [nom, dates] = decouper(ligne?.label ?? `Semaine ${selected + 1}`);
  const semaineCal = semaineCalendaireDepuisLundi(ligne?.monday);

  // La barre supérieure porte déjà la semaine partagée : pas de doublon.
  if (barreGlobale && !toujours) return null;

  return (
    <div className="weekstepper" role="group" aria-label="Semaine affichée">
      <button
        type="button"
        className="btn btn--icon"
        aria-label="Semaine précédente"
        title={raccourcis ? "Semaine précédente (Maj + ←)" : "Semaine précédente"}
        disabled={selected <= 0}
        onClick={() => onSelect(selected - 1)}
      >
        <Chevron sens="gauche" />
      </button>
      <button
        type="button"
        className="btn btn--icon"
        aria-label="Semaine suivante"
        title={raccourcis ? "Semaine suivante (Maj + →)" : "Semaine suivante"}
        disabled={selected >= weekRows.length - 1}
        onClick={() => onSelect(selected + 1)}
      >
        <Chevron sens="droite" />
      </button>
      {/* Libellé complet dans un seul titre : c'est lui qu'annonce un lecteur
          d'écran, et lui que cherchent les tests (« Semaine 6 (28 sept.–2
          oct. 2026) · semaine calendaire 40 »). */}
      <h2 className="weekstepper-titre">
        <span className="weekstepper-nom">{nom}</span>
        {dates && (
          <>
            {" "}
            <span className="weekstepper-dates">({dates})</span>
          </>
        )}
        {semaineCal !== null && (
          <>
            {" "}
            <span className="weekstepper-cal">· semaine calendaire {semaineCal}</span>
          </>
        )}
        {ligne?.blocked && (
          <>
            {" "}
            <span className="weekstepper-cal">· vacances</span>
          </>
        )}
        {complement}
      </h2>
      <button
        type="button"
        className="btn btn--sm weekstepper-auj"
        disabled={surAujourdhui}
        title={raccourcis ? "Revenir à aujourd'hui (T)" : "Revenir à la semaine en cours"}
        onClick={() => (onToday ? onToday() : onSelect(indexAujourdhui))}
      >
        Aujourd'hui
      </button>
    </div>
  );
}
