import type { Placement } from "../types";
import { dayName, slotLabel } from "../utils/slots";
import { movePlacement } from "../api/client";

interface SessionPanelProps {
  placement: Placement | null;
  onClose: () => void;
  onUpdated: (p: Placement) => void;
  onError: (msg: string) => void;
}

export function SessionPanel({ placement, onClose, onUpdated, onError }: SessionPanelProps) {
  if (!placement) return null;

  const handleLock = async () => {
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
      onError(err instanceof Error ? err.message : "Erreur");
    }
  };

  return (
    <div className="session-panel">
      <button type="button" className="close-btn" onClick={onClose} aria-label="Fermer">
        ×
      </button>
      <h3>{placement.course_name}</h3>
      <p className="session-code">
        {placement.course_code} · {placement.session_type}
        {placement.is_eval && <span className="badge eval">Éval</span>}
        {placement.locked && <span className="badge lock">Verrouillé</span>}
      </p>

      <dl className="session-details">
        <dt>Semaine</dt>
        <dd>{placement.week + 1}</dd>
        <dt>Jour</dt>
        <dd>{dayName(placement.day)}</dd>
        <dt>Créneau</dt>
        <dd>{slotLabel(placement.slot)}</dd>
        <dt>Enseignant(s)</dt>
        <dd>{placement.teacher_codes.join(", ")}</dd>
        <dt>Salle</dt>
        <dd>{placement.room_label ?? "—"}</dd>
        <dt>Groupe</dt>
        <dd>{placement.group_ids.join(", ")} ({placement.session_type})</dd>
      </dl>

      {!placement.locked && (
        <button type="button" className="btn btn--ghost" onClick={handleLock}>
          Verrouiller ce créneau
        </button>
      )}
    </div>
  );
}
