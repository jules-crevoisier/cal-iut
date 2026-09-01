/**
 * Carte d'une séance parquée dans À placer — pick + Annuler, pas de créneaux.
 */
import type { ParkedSession } from "./parkWeekMove";

interface ParkedCardProps {
  parked: ParkedSession;
  selected: boolean;
  onSelect: () => void;
  onAnnuler: () => void;
}

export function ParkedCard({ parked, selected, onSelect, onAnnuler }: ParkedCardProps) {
  const { origin } = parked;
  const titre = `${origin.course_code} — ${origin.course_name}`;
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
