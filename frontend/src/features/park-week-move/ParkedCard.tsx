/**
 * Carte d'une séance parquée dans À placer — pick + Annuler, pas de créneaux.
 */
import type { ParkedSession } from "./parkWeekMove";
import { shortGroupLabel } from "../../utils/years";

interface ParkedCardProps {
  parked: ParkedSession;
  selected: boolean;
  onSelect: () => void;
  onAnnuler: () => void;
  groupLabels?: Record<string, string>;
}

export function ParkedCard({ parked, selected, onSelect, onAnnuler, groupLabels = {} }: ParkedCardProps) {
  const { origin } = parked;
  const titre = `${origin.course_code} — ${origin.course_name}`;
  // Retour utilisateur (03/09/2026) : le groupe concerné (TD AB, TP C…)
  // n'apparaissait nulle part sur cette carte — on ne pouvait pas savoir à
  // quel groupe la séance parquée appartenait sans rouvrir la grille.
  const groupe = shortGroupLabel(origin.group_ids, groupLabels);
  return (
    <article
      className={"aplacer-carte aplacer-carte--park" + (selected ? " aplacer-carte--park-selected" : "")}
      aria-label={titre}
      onClick={onSelect}
    >
      <div className="aplacer-entete">
        <span className="aplacer-titre">
          <strong>{titre}</strong>
          <span className="sub">
            {origin.session_type}
            {groupe ? ` · ${groupe}` : ""}
            {origin.room_label ? ` · ${origin.room_label}` : ""} — cliquez puis une case de la grille
          </span>
        </span>
      </div>
      <div className="aplacer-corps">
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={(e) => {
            e.stopPropagation();
            onAnnuler();
          }}
        >
          Annuler
        </button>
      </div>
    </article>
  );
}
