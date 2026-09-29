/**
 * Détail de la séance cliquée dans la Vue Semaine (refonte du 29/09/2026).
 *
 * Affiché EN TÊTE de la colonne de droite (il était sous la liste des
 * écarts, souvent hors écran), avec des libellés lisibles : la semaine de
 * la grille et sa date (plus « Semaine 7 » = index interne), les noms des
 * groupes et des enseignants (plus leurs identifiants techniques).
 *
 * La Vue Semaine est en lecture seule depuis le 28/08/2026 (retour
 * utilisateur : le glisser-déposer vit dans la Vue Promo) : d'où le lien
 * « Modifier dans la Vue Promo », qui ouvre la bonne semaine au bon jour.
 */
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
}: SessionPanelProps) {
  if (!placement) {
    return (
      <div className="session-panel session-panel--vide">
        <p>Cliquez une séance de la grille pour voir son détail ici.</p>
      </div>
    );
  }

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
          <span aria-hidden="true">×</span>
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
