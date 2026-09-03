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
  /** Modale semaine : une ligne, sans recouvrir la grille. */
  compact?: boolean;
}

export function ParkedCard({
  parked,
  selected,
  onSelect,
  onAnnuler,
  groupLabels = {},
  compact = false,
}: ParkedCardProps) {
  const { origin } = parked;
  const titre = `${origin.course_code} — ${origin.course_name}`;
  // Retour utilisateur (03/09/2026) : le groupe concerné (TD AB, TP C…)
  // n'apparaissait nulle part sur cette carte — on ne pouvait pas savoir à
  // quel groupe la séance parquée appartenait sans rouvrir la grille.
  const groupe = shortGroupLabel(origin.group_ids, groupLabels);
  const meta = [origin.session_type, groupe, origin.room_label].filter(Boolean).join(" · ");
  const classes = [
    "aplacer-carte",
    "aplacer-carte--park",
    selected ? "aplacer-carte--park-selected" : "",
    compact ? "aplacer-carte--park-compact" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <article className={classes} aria-label={titre} onClick={onSelect}>
      <div className="aplacer-entete">
        <span className="aplacer-titre">
          <strong>{titre}</strong>
          <span className="sub">
            {compact ? meta : `${meta} — cliquez puis une case de la grille`}
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
