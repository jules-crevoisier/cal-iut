/**
 * Déplacement d'une séance (validation -> confirmation si conflit -> move) —
 * extrait de `TimetableCalendar.tsx` (seul endroit qui le faisait jusqu'ici)
 * pour être réutilisé par `TdWeekGrid.tsx`, qui n'avait ABSOLUMENT AUCUN
 * moyen de déplacer une séance (ni glisser-déposer, ni formulaire) — retour
 * utilisateur 11/08/2026 : "l'interface ne permet pas la modification pour
 * l'instant fix cela". `TdWeekGrid` est pourtant la vue PAR DÉFAUT (groupe
 * TD), donc c'est la première chose qu'un utilisateur rencontre.
 */

import { movePlacement, validateMove } from "../api/client";
import type { Placement } from "../types";
import { confirmAsync } from "./confirmDialog";

export async function performMove(
  sessionId: string,
  target: { week: number; day: number; slot: number },
  placement: Placement,
  onPlacementUpdated: (p: Placement) => void,
  onError: (msg: string) => void,
): Promise<boolean> {
  try {
    const validation = await validateMove(sessionId, { ...target, room_id: placement.room_id });
    if (!validation.valid) {
      // Modale interne, pas `window.confirm` (retour utilisateur 28/08/2026 :
      // un bloqueur de popup le renvoie à `false` en silence, empêchant tout
      // forçage — cf. utils/confirmDialog.ts).
      const force = await confirmAsync(validation.hard_conflicts.join("\n"), { confirmLabel: "Forcer le déplacement" });
      if (!force) return false;
      const updated = await movePlacement(sessionId, { ...target, room_id: placement.room_id, force: true });
      onPlacementUpdated(updated);
      return true;
    }
    if (validation.soft_warnings.length > 0) {
      onError(`Avertissement : ${validation.soft_warnings.join(", ")}`);
    }
    const updated = await movePlacement(sessionId, { ...target, room_id: placement.room_id });
    onPlacementUpdated(updated);
    return true;
  } catch (err) {
    onError(err instanceof Error ? err.message : "Erreur de déplacement");
    return false;
  }
}
