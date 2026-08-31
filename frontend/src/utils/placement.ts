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

import {
  creerSeancePersonnalisee,
  modifierSeanceMaquette,
  placerSeance,
  type CreerSeanceBody,
  type PatchSeanceMaquetteBody,
} from "../api/client";
import type { Placement } from "../types";
import { alerterAsync, confirmAsync } from "./confirmDialog";

/** Le serveur renvoie le détail structuré d'un conflit (`hard_conflicts`/
 * `soft_warnings`) comme `detail` JSON d'un 409 — `request()` le rejette en
 * `Error(JSON.stringify(detail))` (cf. api/client.ts) faute de type d'erreur
 * dédié. On le re-parse ici plutôt que d'ajouter un mécanisme d'erreur
 * générique. `null` = pas un conflit structuré (panne réseau, autre message
 * serveur) — dans ce cas pas de proposition de forçage. */
export function detailConflit(
  e: unknown,
): { hard_conflicts: string[]; soft_warnings: string[]; blocking_conflicts: string[] } | null {
  if (!(e instanceof Error)) return null;
  try {
    const d = JSON.parse(e.message) as {
      hard_conflicts?: unknown;
      soft_warnings?: unknown;
      blocking_conflicts?: unknown;
    };
    if (Array.isArray(d.hard_conflicts)) {
      return {
        hard_conflicts: d.hard_conflicts as string[],
        soft_warnings: Array.isArray(d.soft_warnings) ? (d.soft_warnings as string[]) : [],
        // Ce que « Forcer » ne lèvera pas — absent des serveurs antérieurs
        // au 29/08/2026, d'où le repli sur une liste vide.
        blocking_conflicts: Array.isArray(d.blocking_conflicts) ? (d.blocking_conflicts as string[]) : [],
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
    // Modale interne, pas `window.confirm` — cf. utils/confirmDialog.ts
    // (retour utilisateur 28/08/2026, popups navigateur désactivées).
    // Obstacle non contournable (indisponibilité enseignant, verrou
    // PAC/SAE) : on le dit, au lieu de proposer un forçage qui échouera.
    if (detail.blocking_conflicts.length > 0) {
      await alerterAsync(detail.blocking_conflicts.join(String.fromCharCode(10)), { title: "Placement impossible" });
      return { ok: false, message: detail.blocking_conflicts.join(" · ") };
    }
    const forcer = await confirmAsync([...detail.hard_conflicts, ...detail.soft_warnings].join("\n"), {
      confirmLabel: "Forcer le placement",
    });
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

/** Même logique confirmer-puis-forcer que `placerAvecConfirmation`, pour la
 * création d'une séance personnalisée (retour utilisateur 31/08/2026) —
 * `POST /placements/personnalisees` porte les mêmes trois catégories de
 * réponse (succès, conflit forçable, verrou institutionnel). */
export async function creerSeanceAvecConfirmation(
  corps: CreerSeanceBody,
): Promise<{ ok: true; placement: Placement } | { ok: false; message: string }> {
  try {
    return { ok: true, placement: await creerSeancePersonnalisee(corps) };
  } catch (e) {
    const detail = detailConflit(e);
    if (!detail) {
      return { ok: false, message: e instanceof Error ? e.message : "Création impossible" };
    }
    if (detail.blocking_conflicts.length > 0) {
      await alerterAsync(detail.blocking_conflicts.join(String.fromCharCode(10)), { title: "Création impossible" });
      return { ok: false, message: detail.blocking_conflicts.join(" · ") };
    }
    const forcer = await confirmAsync([...detail.hard_conflicts, ...detail.soft_warnings].join("\n"), {
      confirmLabel: "Créer quand même",
    });
    if (!forcer) return { ok: false, message: "Création annulée." };
    try {
      return { ok: true, placement: await creerSeancePersonnalisee({ ...corps, force: true }) };
    } catch (e2) {
      const detail2 = detailConflit(e2);
      const message = detail2
        ? [...detail2.hard_conflicts, ...detail2.soft_warnings].join(" · ")
        : e2 instanceof Error
          ? e2.message
          : "Erreur de création (forcée)";
      return { ok: false, message };
    }
  }
}

/** Même confirmer-puis-forcer pour l'overlay maquette (enseignant / type / durée). */
export async function modifierSeanceMaquetteAvecConfirmation(
  sessionId: string,
  corps: PatchSeanceMaquetteBody,
): Promise<{ ok: true; placement: Placement } | { ok: false; message: string }> {
  try {
    return { ok: true, placement: await modifierSeanceMaquette(sessionId, corps) };
  } catch (e) {
    const detail = detailConflit(e);
    if (!detail) {
      return { ok: false, message: e instanceof Error ? e.message : "Modification impossible" };
    }
    if (detail.blocking_conflicts.length > 0) {
      await alerterAsync(detail.blocking_conflicts.join(String.fromCharCode(10)), { title: "Modification impossible" });
      return { ok: false, message: detail.blocking_conflicts.join(" · ") };
    }
    const forcer = await confirmAsync([...detail.hard_conflicts, ...detail.soft_warnings].join("\n"), {
      confirmLabel: "Enregistrer quand même",
    });
    if (!forcer) return { ok: false, message: "Modification annulée." };
    try {
      return { ok: true, placement: await modifierSeanceMaquette(sessionId, { ...corps, force: true }) };
    } catch (e2) {
      const detail2 = detailConflit(e2);
      const message = detail2
        ? [...detail2.hard_conflicts, ...detail2.soft_warnings].join(" · ")
        : e2 instanceof Error
          ? e2.message
          : "Erreur de modification (forcée)";
      return { ok: false, message };
    }
  }
}
