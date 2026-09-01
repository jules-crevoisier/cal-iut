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

import { useRef, useState } from "react";

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
  /** Dépôt d'une séance déjà en cours de glisser : la Vue Promo parque
   *  visuellement (À placer) au lieu de garder le même créneau. */
  onDropWeek?: (displayIndex: number) => void;
  dropEnabled?: boolean;
}

export function WeekBar({
  weekRows,
  countByWeekIndex,
  selected,
  onSelect,
  unit = "creneaux",
  onDropWeek,
  dropEnabled = false,
}: WeekBarProps) {
  const counts = weekRows.map((wr) => (wr.weekIndex !== null ? countByWeekIndex.get(wr.weekIndex) ?? 0 : 0));
  const max = Math.max(1, ...counts);
  // Infobulle INTERNE (retour utilisateur 28/08/2026 : « internalise moi les
  // hover, là on est sur les hover du navigateur ») — l'attribut `title`
  // natif est lent à apparaître, non stylable, et invisible au toucher.
  // Positionnée en `position: fixed` d'après le rectangle de la barre
  // survolée : la `.weekbar` défile horizontalement (`overflow-x: auto`),
  // un positionnement relatif au conteneur se décalerait au défilement.
  const [survol, setSurvol] = useState<{ texte: string; x: number; y: number } | null>(null);
  const [dropCible, setDropCible] = useState<number | null>(null);
  const ignorerClic = useRef<number | null>(null);

  // Première / sélectionnée / dernière — mais jamais le même libellé deux
  // fois : quand la semaine choisie EST la première ou la dernière (cas le
  // plus courant à l'ouverture), afficher "Semaine 2 ... Semaine 2 ..."
  // côte à côte lisait comme un bug d'affichage plutôt qu'une information
  // (retour utilisateur 31/08/2026 : « revois un peu les espacements »).
  const premiere = weekRows[0];
  const derniere = weekRows[weekRows.length - 1];
  const courante = weekRows[selected];
  const captions: { key: string; label: string }[] = [];
  if (premiere) captions.push({ key: "premiere", label: premiere.label });
  if (courante && courante !== premiere) captions.push({ key: "courante", label: courante.label });
  if (derniere && derniere !== premiere && derniere !== courante) {
    captions.push({ key: "derniere", label: derniere.label });
  }

  const montrer = (e: { currentTarget: HTMLElement }, texte: string) => {
    const r = e.currentTarget.getBoundingClientRect();
    setSurvol({ texte, x: r.left + r.width / 2, y: r.top });
  };

  return (
    <div className={"weekbar-wrap" + (dropEnabled ? " weekbar-drop-actif" : "")}>
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
          const accepteDepot = Boolean(onDropWeek) && !wr.blocked && wr.weekIndex !== null;
          return (
            <button
              key={wr.monday}
              type="button"
              aria-label={title}
              className={
                "weekbar-bar"
                + (i === selected ? " active" : "")
                + (wr.blocked ? " blocked" : "")
                + (dropCible === i ? " drop-cible" : "")
              }
              onClick={() => {
                if (ignorerClic.current === i) {
                  ignorerClic.current = null;
                  return;
                }
                ignorerClic.current = null;
                onSelect(i);
              }}
              onMouseEnter={(e) => montrer(e, title)}
              onMouseLeave={() => setSurvol(null)}
              onFocus={(e) => montrer(e, title)}
              onBlur={() => setSurvol(null)}
              onDragOver={(e) => {
                if (!accepteDepot) return;
                e.preventDefault();
                if (dropCible !== i) setDropCible(i);
              }}
              onDragLeave={() => setDropCible((cur) => (cur === i ? null : cur))}
              onDrop={(e) => {
                if (!accepteDepot || !onDropWeek) return;
                e.preventDefault();
                ignorerClic.current = i;
                setDropCible(null);
                onDropWeek(i);
              }}
            >
              <span className="bar" style={{ height: `${barHeight}%` }} />
            </button>
          );
        })}
      </div>
      {survol && (
        <div className="weekbar-tip" role="tooltip" style={{ left: survol.x, top: survol.y }}>
          {survol.texte}
        </div>
      )}
      {captions.length > 0 && (
        <div className="weekbar-caption">
          {captions.map((c) => (
            <span key={c.key}>{c.label}</span>
          ))}
        </div>
      )}
    </div>
  );
}
