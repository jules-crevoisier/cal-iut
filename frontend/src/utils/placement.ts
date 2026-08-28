/**
 * Placement d'une séance non encore au planning, à un créneau CHOISI (donc
 * potentiellement hors de tout créneau pré-vérifié) — extrait de
 * `views/APlacerView.tsx` pour être réutilisé par `views/PromoView.tsx`
 * (retour utilisateur 28/08/2026 : « il faudrait la vue promo où le
 * planning s'affiche et qu'on puisse les placer directement dessus »).
 *
 * Même logique que le glisser-déposer (`moveSession.ts::performMove`) :
 * essai normal, et seulement si ça bute sur un conflit RESSOURCE
 * (contournable), popup de confirmation puis nouvel essai avec `force`. Les
 * règles institutionnelles (PAC, SAE, ordre pédagogique...) restent NON
 * contournables — le serveur les rejette même avec `force`, cf.
 * `placer_seance` (src/cal_iut/api/main.py) ; dans ce cas la popup ne
 * s'affiche pas, le message d'échec du serveur est montré tel quel.
 */

import { placerSeance } from "../api/client";

/** Le serveur renvoie le détail structuré d'un conflit (`hard_conflicts`/
 * `soft_warnings`) comme `detail` JSON d'un 409 — `request()` le rejette en
 * `Error(JSON.stringify(detail))` (cf. api/client.ts) faute de type d'erreur
 * dédié. On le re-parse ici plutôt que d'ajouter un mécanisme d'erreur
 * générique. `null` = pas un conflit structuré (panne réseau, autre message
 * serveur) — dans ce cas pas de proposition de forçage. */
export function detailConflit(e: unknown): { hard_conflicts: string[]; soft_warnings: string[] } | null {
  if (!(e instanceof Error)) return null;
  try {
    const d = JSON.parse(e.message) as { hard_conflicts?: unknown; soft_warnings?: unknown };
    if (Array.isArray(d.hard_conflicts)) {
      return {
        hard_conflicts: d.hard_conflicts as string[],
        soft_warnings: Array.isArray(d.soft_warnings) ? (d.soft_warnings as string[]) : [],
      };
    }
  } catch {
    /* pas un détail structuré */
  }
  return null;
}

export async function placerAvecConfirmation(
  sessionId: string,
  cible: { week: number; day: number; slot: number },
): Promise<{ ok: true } | { ok: false; message: string }> {
  try {
    await placerSeance(sessionId, cible);
    return { ok: true };
  } catch (e) {
    const detail = detailConflit(e);
    if (!detail) {
      return { ok: false, message: e instanceof Error ? e.message : "Erreur de placement" };
    }
    const forcer = window.confirm(
      `Conflit détecté :\n${[...detail.hard_conflicts, ...detail.soft_warnings].join("\n")}\n\nForcer le placement quand même ?`,
    );
    if (!forcer) return { ok: false, message: "Placement annulé." };
    try {
      await placerSeance(sessionId, { ...cible, force: true });
      return { ok: true };
    } catch (e2) {
      // Un second échec malgré `force` = règle institutionnelle non
      // contournable (ex. ordre pédagogique) — le message reste structuré
      // de la même façon, on le reparse pour ne pas afficher le JSON brut.
      const detail2 = detailConflit(e2);
      const message = detail2
        ? [...detail2.hard_conflicts, ...detail2.soft_warnings].join(" · ")
        : e2 instanceof Error
          ? e2.message
          : "Erreur de placement (forcé)";
      return { ok: false, message };
    }
  }
}
