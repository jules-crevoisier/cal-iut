/**
 * Placement d'une séance non encore au planning, à un créneau CHOISI (donc
 * potentiellement hors de tout créneau pré-vérifié) — extrait de
 * `views/APlacerView.tsx` pour être réutilisé par `views/PromoView.tsx`
 * (retour utilisateur 28/08/2026 : « il faudrait la vue promo où le
 * planning s'affiche et qu'on puisse les placer directement dessus »).
 *
 * Même logique que le glisser-déposer (`moveSession.ts::performMove`) :
 * essai normal, et seulement si ça bute sur un conflit RESSOURCE /
 * forçable (ordre pédagogique, indispo enseignant), popup de confirmation
 * puis nouvel essai avec `force`. Les verrous institutionnels (PAC, SAE
 * pour WR*, férié…) restent NON contournables — le serveur les met dans
 * `blocking_conflicts` ; dans ce cas la popup Forcer ne s'affiche pas.
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

export type DetailConflit = {
  hard_conflicts: string[];
  soft_warnings: string[];
  blocking_conflicts: string[];
};

/** Le serveur renvoie le détail structuré d'un conflit (`hard_conflicts`/
 * `soft_warnings`) comme `detail` JSON d'un 409 — `request()` le rejette en
 * `Error(JSON.stringify(detail))` (cf. api/client.ts) faute de type d'erreur
 * dédié. On le re-parse ici plutôt que d'ajouter un mécanisme d'erreur
 * générique. `null` = pas un conflit structuré (panne réseau, autre message
 * serveur) — dans ce cas pas de proposition de forçage. */
export function detailConflit(e: unknown): DetailConflit | null {
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

/** Liste lisible de toutes les contraintes (blocking + forçable + soft). */
export function texteContraintes(detail: DetailConflit): string {
  const blocs: string[] = [];
  if (detail.blocking_conflicts.length) {
    blocs.push(`Impossible (non forçable) :\n${detail.blocking_conflicts.join("\n")}`);
  }
  if (detail.hard_conflicts.length) {
    blocs.push(`Forçable :\n${detail.hard_conflicts.join("\n")}`);
  }
  if (detail.soft_warnings.length) {
    blocs.push(`Avertissement :\n${detail.soft_warnings.join("\n")}`);
  }
  return blocs.join("\n\n");
}

async function gererConflitPuisForcer(
  detail: DetailConflit,
  titres: { impossible: string; confirmLabel: string },
  forcer: () => Promise<void>,
): Promise<{ ok: true } | { ok: false; message: string }> {
  const texte = texteContraintes(detail);
  if (detail.blocking_conflicts.length > 0) {
    await alerterAsync(texte, { title: titres.impossible });
    return { ok: false, message: detail.blocking_conflicts.join(" · ") };
  }
  const accepte = await confirmAsync(texte, { confirmLabel: titres.confirmLabel });
  if (!accepte) return { ok: false, message: "Action annulée." };
  try {
    await forcer();
    return { ok: true };
  } catch (e2) {
    const detail2 = detailConflit(e2);
    const message = detail2
      ? texteContraintes(detail2).replace(/\n+/g, " · ")
      : e2 instanceof Error
        ? e2.message
        : "Erreur (forcé)";
    return { ok: false, message };
  }
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
    return gererConflitPuisForcer(
      detail,
      { impossible: "Placement impossible", confirmLabel: "Forcer le placement" },
      async () => {
        await placerSeance(sessionId, { ...cible, force: true });
      },
    );
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
    let placement: Placement | null = null;
    const resultat = await gererConflitPuisForcer(
      detail,
      { impossible: "Création impossible", confirmLabel: "Créer quand même" },
      async () => {
        placement = await creerSeancePersonnalisee({ ...corps, force: true });
      },
    );
    if (!resultat.ok || !placement) return { ok: false, message: resultat.ok ? "Création impossible" : resultat.message };
    return { ok: true, placement };
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
    let placement: Placement | null = null;
    const resultat = await gererConflitPuisForcer(
      detail,
      { impossible: "Modification impossible", confirmLabel: "Enregistrer quand même" },
      async () => {
        placement = await modifierSeanceMaquette(sessionId, { ...corps, force: true });
      },
    );
    if (!resultat.ok || !placement) {
      return { ok: false, message: resultat.ok ? "Modification impossible" : resultat.message };
    }
    return { ok: true, placement };
  }
}
