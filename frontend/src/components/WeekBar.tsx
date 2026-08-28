/**
 * Navigateur de semaine — portage FIDÈLE de `renderWeekBar` depuis
 * `export/templates/timetable.html` : un histogramme (barre dont la hauteur
 * est proportionnelle au nombre de créneaux occupés cette semaine-là, pas de
 * simples points uniformes), + un bandeau de légende sous la barre montrant
 * la première semaine, la semaine sélectionnée et la dernière (retour
 * utilisateur 11/08/2026 : "remet les semaines comme cela", capture de
 * l'export HTML à l'appui — la version précédente ("un point par semaine")
 * ne montrait ni la charge relative ni les dates, cf. docs/DATA.md).
 */

import type { WeekRow } from "../types/app";

interface WeekBarProps {
  weekRows: WeekRow[];
  countByWeekIndex: Map<number, number>;
  selected: number; // index d'AFFICHAGE (dans weekRows)
  onSelect: (displayIndex: number) => void;
  /** Unité affichée dans l'info-bulle de chaque barre — "creneaux" (défaut,
   * vues admin) ou "heures" (retour utilisateur 28/08/2026, relayé depuis
   * Discord, idée de Jordan : « le nombre d'heure total de la semaine ça
   * serait cool si il pouvait être montré » — version légère qui réutilise
   * l'histogramme existant plutôt qu'un nouveau composant, `countByWeekIndex`
   * portant alors des heures au lieu d'un compte de séances). */
  unit?: "creneaux" | "heures";
}

export function WeekBar({ weekRows, countByWeekIndex, selected, onSelect, unit = "creneaux" }: WeekBarProps) {
  const counts = weekRows.map((wr) => (wr.weekIndex !== null ? countByWeekIndex.get(wr.weekIndex) ?? 0 : 0));
  const max = Math.max(1, ...counts);

  return (
    <div>
      <div className="weekbar">
        {weekRows.map((wr, i) => {
          const count = counts[i];
          const valeur = unit === "heures" ? `${count.toLocaleString("fr-FR")} h` : `${count} créneau(x) occupé(s)`;
          const title = wr.blocked ? `${wr.label} — bloquée (vacances/fermeture)` : `${wr.label} — ${valeur}`;
          // Retour utilisateur (11/08/2026) : "le % violet dois coressponde
          // au nombre de séance dans la semaine" — le plancher de 6 % hérité
          // du HTML (qui gardait un minimum visible même à 0 créneau) rendait
          // une semaine VRAIMENT vide difficile à distinguer d'une semaine
          // peu chargée. Une semaine à 0 créneau (non bloquée) est
          // maintenant à 0 % — seul le remplissage réel compte.
          const barHeight = wr.blocked ? 100 : count === 0 ? 0 : (count / max) * 100;
          return (
            <button
              key={wr.monday}
              type="button"
              title={title}
              className={"weekbar-bar" + (i === selected ? " active" : "") + (wr.blocked ? " blocked" : "")}
              onClick={() => onSelect(i)}
            >
              <span className="bar" style={{ height: `${barHeight}%` }} />
            </button>
          );
        })}
      </div>
      {weekRows.length > 0 && (
        <div className="weekbar-caption">
          <span>{weekRows[0].label}</span>
          <span>{weekRows[selected]?.label ?? ""}</span>
          <span>{weekRows[weekRows.length - 1].label}</span>
        </div>
      )}
    </div>
  );
}
