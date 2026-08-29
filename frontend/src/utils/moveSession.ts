/**
 * Déplacement d'une séance (validation -> confirmation si conflit -> move) —
 * extrait de `TimetableCalendar.tsx` (seul endroit qui le faisait jusqu'ici)
 * pour être réutilisé par `TdWeekGrid.tsx`, qui n'avait ABSOLUMENT AUCUN
 * moyen de déplacer une séance (ni glisser-déposer, ni formulaire) — retour
 * utilisateur 11/08/2026 : "l'interface ne permet pas la modification pour
 * l'instant fix cela". `TdWeekGrid` est pourtant la vue PAR DÉFAUT (groupe
 * TD), donc c'est la première chose qu'un utilisateur rencontre.
 *
 * Aujourd'hui le glisser-déposer vit dans `views/PromoView.tsx` (retour
 * utilisateur 28/08/2026) et dans la modale semaine par parcours.
 */

import { echangerPlacements, movePlacement, validateMove } from "../api/client";
import type { Placement } from "../types";
import { alerterAsync, confirmAsync } from "./confirmDialog";
import { detailConflit } from "./placement";

/** Obstacles que « Forcer » ne lève pas : on prévient au lieu de proposer un
 *  bouton qui échouera (retour utilisateur 29/08/2026 : « on veut bien
 *  afficher les contraintes enseignantes si cela les enfreint »). */
async function annoncerBlocage(motifs: string[], titre: string): Promise<void> {
  await alerterAsync(motifs.join("\n"), { title: titre });
}

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
      // Indisponibilité enseignant déclarée, verrou PAC/SAE, événement
      // institutionnel : le serveur les refuse MÊME avec `force` (cf.
      // api/main.py::move_session). Proposer « Forcer » ici menait à un
      // échec incompréhensible.
      const bloquants = validation.blocking_conflicts ?? [];
      if (bloquants.length > 0) {
        await annoncerBlocage(bloquants, "Déplacement impossible");
        return false;
      }
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

/**
 * Échange de place entre deux séances — retour utilisateur 29/08/2026 : « si
 * l'on fait un glisser-déposer d'un cours sur un autre, cela nous propose un
 * échange de cours tout en vérifiant pareil ».
 *
 * Un seul appel serveur (`POST /placements/echanger`), pas deux déplacements
 * enchaînés : le premier des deux poserait forcément une séance sur une case
 * encore occupée par l'autre, donc il faudrait forcer — et le forçage
 * sauterait justement les vérifications qu'on veut garder.
 */
export async function performSwap(
  sessionA: string,
  sessionB: string,
  libelleA: string,
  libelleB: string,
  onPlacementUpdated: (p: Placement) => void,
  onError: (msg: string) => void,
): Promise<boolean> {
  const accepte = await confirmAsync(`Échanger ${libelleA} et ${libelleB} de place ?`, {
    title: "Échanger deux séances",
    confirmLabel: "Échanger",
  });
  if (!accepte) return false;

  try {
    const { placements } = await echangerPlacements(sessionA, sessionB);
    placements.forEach(onPlacementUpdated);
    return true;
  } catch (err) {
    const detail = detailConflit(err);
    if (!detail) {
      onError(err instanceof Error ? err.message : "Échange impossible");
      return false;
    }
    if (detail.blocking_conflicts.length > 0) {
      await annoncerBlocage(detail.blocking_conflicts, "Échange impossible");
      return false;
    }
    const force = await confirmAsync([...detail.hard_conflicts, ...detail.soft_warnings].join("\n"), {
      confirmLabel: "Échanger quand même",
    });
    if (!force) return false;
    try {
      const { placements } = await echangerPlacements(sessionA, sessionB, true);
      placements.forEach(onPlacementUpdated);
      return true;
    } catch (err2) {
      const detail2 = detailConflit(err2);
      onError(
        detail2
          ? [...detail2.hard_conflicts, ...detail2.soft_warnings].join(" · ")
          : err2 instanceof Error
            ? err2.message
            : "Échange impossible",
      );
      return false;
    }
  }
}
