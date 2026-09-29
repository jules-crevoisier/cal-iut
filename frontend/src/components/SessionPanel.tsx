/**
 * Détail de la séance cliquée dans la Vue Semaine (refonte du 29/09/2026).
 *
 * Affiché EN TÊTE de la colonne de droite (il était sous la liste des
 * écarts, souvent hors écran), avec des libellés lisibles : la semaine de
 * la grille et sa date (plus « Semaine 7 » = index interne), les noms des
 * groupes et des enseignants (plus leurs identifiants techniques).
 *
 * Sans séance choisie (gabarit v2) : la semaine affichée en bref (séances,
 * heures, répartition par type, séances sans salle) plutôt qu'une boîte vide.
 *
 * La Vue Semaine est en lecture seule depuis le 28/08/2026 (retour
 * utilisateur : le glisser-déposer vit dans la Vue Promo) : d'où le lien
 * « Modifier dans la Vue Promo », qui ouvre la bonne semaine au bon jour.
 */
import { X } from "lucide-react";

import type { Placement } from "../types";
import type { WeekRow } from "../types/app";
import { movePlacement } from "../api/client";
import { confirmAsync } from "../utils/confirmDialog";
import { nomComplet } from "../utils/nomEnseignant";
import { dayName, slotLabel } from "../utils/slots";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";
import "./SessionPanel.css";

interface SessionPanelProps {
  placement: Placement | null;
  onClose: () => void;
  onUpdated: (p: Placement) => void;
  onError: (msg: string) => void;
  weekRows?: WeekRow[];
  weekDates?: string[];
  groupLabels?: Record<string, string>;
  teacherLabels?: Record<string, string>;
  /** Ouvre la Vue Promo sur la semaine et le jour de la séance. */
  onOuvrirPromo?: (p: Placement) => void;
  /** Séances de la semaine affichée, pour le résumé sans séance choisie. */
  seancesSemaine?: Placement[];
  /** Ce que montre la grille (« TD AB », « Joan Lefevre »…). */
  portee?: string;
}

const TYPES_RESUME = ["CM", "TD", "TP"] as const;

function formatHeures(n: number): string {
  return `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} h`;
}

/** La semaine affichée en bref : ce qui tient la colonne quand aucune
 *  séance n'est choisie. */
function ResumeSemaine({ seances, portee }: { seances: Placement[]; portee?: string }) {
  const heures = seances.reduce((t, p) => t + Math.max(1, p.duration_slots || 1) * 1.5, 0);
  const parType = TYPES_RESUME.map((t) => ({ t, n: seances.filter((p) => p.session_type === t).length }));
  const autres = seances.length - parType.reduce((t, x) => t + x.n, 0);
  const sansSalle = seances.filter((p) => !p.room_label).length;
  const evaluations = seances.filter((p) => p.is_eval).length;
  return (
    <section className="session-panel session-panel--vide" aria-labelledby="session-resume-titre">
      <h3 id="session-resume-titre">La semaine en bref</h3>
      {portee && <p className="session-resume-portee">{portee}</p>}
      <div className="session-resume-tuiles">
        <div className="session-resume-tuile">
          <span>Séances</span>
          <strong>{seances.length}</strong>
        </div>
        <div className="session-resume-tuile">
          <span>Heures</span>
          <strong>{formatHeures(heures)}</strong>
        </div>
      </div>
      {seances.length > 0 && (
        <ul className="session-resume-types" aria-label="Par type de séance">
          {parType
            .filter((x) => x.n > 0)
            .map((x) => (
              <li key={x.t} className={`type-${x.t.toLowerCase()}`}>
                <span>{x.t}</span>
                <strong>{x.n}</strong>
              </li>
            ))}
          {autres > 0 && (
            <li>
              <span>Autres</span>
              <strong>{autres}</strong>
            </li>
          )}
        </ul>
      )}
      {(sansSalle > 0 || evaluations > 0) && (
        <ul className="session-resume-faits">
          {sansSalle > 0 && (
            <li className="manque">
              {sansSalle} séance{sansSalle > 1 ? "s" : ""} sans salle
            </li>
          )}
          {evaluations > 0 && (
            <li>
              {evaluations} évaluation{evaluations > 1 ? "s" : ""}
            </li>
          )}
        </ul>
      )}
      <p className="session-resume-aide">Cliquez une séance de la grille pour voir son détail ici.</p>
    </section>
  );
}

export function SessionPanel({
  placement,
  onClose,
  onUpdated,
  onError,
  weekRows = [],
  weekDates = [],
  groupLabels = {},
  teacherLabels = {},
  onOuvrirPromo,
  seancesSemaine = [],
  portee,
}: SessionPanelProps) {
  if (!placement) return <ResumeSemaine seances={seancesSemaine} portee={portee} />;

  // Le verrou ne se retire pas depuis l'interface (l'API refuse de déplacer
  // une séance verrouillée) : on demande confirmation.
  const handleLock = async () => {
    const ok = await confirmAsync(
      `Verrouiller ${placement.course_code} à ce créneau ? Elle ne pourra plus être déplacée depuis l'interface.`,
      { title: "Verrouiller la séance", confirmLabel: "Verrouiller" },
    );
    if (!ok) return;
    try {
      const updated = await movePlacement(placement.session_id, {
        week: placement.week,
        day: placement.day,
        slot: placement.slot,
        room_id: placement.room_id,
        lock: true,
      });
      onUpdated(updated);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Verrouillage impossible");
    }
  };

  const semaine = weekRows.find((w) => w.weekIndex === placement.week)?.label ?? `Semaine ${placement.week + 1}`;
  const date = formatShortDate(dateForWeekDay({ weekDates }, placement.week, placement.day));
  const groupes = placement.group_ids.map((id) => groupLabels[id] ?? id).join(", ");
  const enseignants = placement.teacher_codes.map((c) => (teacherLabels[c] ? nomComplet(teacherLabels[c]!) : c));

  return (
    <section className="session-panel" aria-labelledby="session-panel-titre">
      <div className="session-panel-tete">
        <p className="session-panel-code">
          <span className="mono">{placement.course_code}</span> · {placement.session_type}
          {placement.is_eval && <span className="session-panel-etat eval">Évaluation</span>}
          {placement.locked && <span className="session-panel-etat">Verrouillée</span>}
        </p>
        <button type="button" className="btn btn--ghost btn--icon btn--sm" onClick={onClose} aria-label="Fermer le détail">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <h3 id="session-panel-titre">{placement.course_name || placement.course_code}</h3>

      <dl className="session-details">
        <dt>Quand</dt>
        <dd>
          {dayName(placement.day)}
          {date ? ` ${date}` : ""}, {placement.hor ?? slotLabel(placement.slot)}
          <span className="session-details-sub">{semaine}</span>
        </dd>
        <dt>Groupe{placement.group_ids.length > 1 ? "s" : ""}</dt>
        <dd>{groupes || "—"}</dd>
        <dt>Enseignant{enseignants.length > 1 ? "s" : ""}</dt>
        <dd>{enseignants.join(", ") || "—"}</dd>
        <dt>Salle</dt>
        <dd className={placement.room_label ? undefined : "session-details-manque"}>
          {placement.room_label ?? "à définir"}
        </dd>
      </dl>

      <div className="session-panel-actions">
        {onOuvrirPromo && (
          <button type="button" className="btn btn--sm" onClick={() => onOuvrirPromo(placement)}>
            Modifier dans la Vue Promo
          </button>
        )}
        {!placement.locked && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => void handleLock()}>
            Verrouiller ce créneau
          </button>
        )}
      </div>
    </section>
  );
}
