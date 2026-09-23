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
  creerEvenement,
  creerSeancePersonnalisee,
  modifierSeanceMaquette,
  modifierSeancePersonnalisee,
  placerSeance,
  type CreerEvenementBody,
  type CreerSeanceBody,
  type ModifierSeanceBody,
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
  // `blocking_conflicts` est par contrat un SOUS-ENSEMBLE de
  // `hard_conflicts` (cf. schemas.ValidationResponse) : afficher
  // `hard_conflicts` en entier répétait donc chaque motif bloquant sous
  // « Forçable », en laissant croire qu'on pouvait forcer ce qui est
  // justement non forçable (signalé le 08/09/2026, capture à l'appui).
  const forcables = detail.hard_conflicts.filter((m) => !detail.blocking_conflicts.includes(m));
  if (forcables.length) {
    blocs.push(`Forçable :\n${forcables.join("\n")}`);
  }
  if (detail.soft_warnings.length) {
    blocs.push(`Avertissement :\n${detail.soft_warnings.join("\n")}`);
  }
  return blocs.join("\n\n");
}

// ── Date passée (item A, 22/09/2026) ──
// « ne pas pouvoir déplacer ou créer de séances sur des dates passées ou
// alors vraiment une popup pour le forcer » — décision de Jules : tout reste
// forçable, mais la popup de confirmation doit être FORTE quand le conflit
// touche une date déjà écoulée. Le serveur préfixe ces motifs-là par
// « Date passée : » EXACTEMENT (cf. `api/main.py::_dates_passees_motifs`) —
// c'est le seul signal dont le front dispose pour les reconnaître.
const PREFIXE_DATE_PASSEE = "Date passée : ";
const PHRASE_CELCAT_DATE_PASSEE =
  "Cette séance a peut-être déjà eu lieu : la modification sera aussi envoyée vers Celcat.";

export function estDatePassee(conflits: string[]): boolean {
  return conflits.some((m) => m.startsWith(PREFIXE_DATE_PASSEE));
}

export interface OptionsForcage {
  title?: string;
  confirmLabel: string;
  variant?: "default" | "danger";
}

/**
 * Texte affiché + options de `confirmAsync` pour la popup de forçage —
 * variante FORTE si un des conflits FORÇABLES (jamais un `blocking`, cf.
 * appelants) touche une date déjà écoulée : titre dédié, le(s) message(s) de
 * date en PREMIER, la phrase Celcat explicite, bouton de confirmation en
 * danger (`ConfirmModal` applique `.btn--danger`). Le bouton Annuler garde
 * le focus par défaut (`autoFocus`, `ConfirmModal.tsx`) — déjà le cas pour
 * TOUTE confirmation, rien de plus à faire ici pour ça.
 */
export function texteEtOptionsForcage(
  hard: string[],
  blocking: string[],
  soft: string[],
  confirmLabelDefaut: string,
): { texte: string; options: OptionsForcage } {
  const forcables = hard.filter((m) => !blocking.includes(m));
  if (!estDatePassee(forcables)) {
    const blocs: string[] = [];
    if (forcables.length) blocs.push(`Forçable :\n${forcables.join("\n")}`);
    if (soft.length) blocs.push(`Avertissement :\n${soft.join("\n")}`);
    return { texte: blocs.join("\n\n"), options: { confirmLabel: confirmLabelDefaut } };
  }
  const dates = forcables.filter((m) => m.startsWith(PREFIXE_DATE_PASSEE));
  const autres = forcables.filter((m) => !m.startsWith(PREFIXE_DATE_PASSEE));
  const blocs = [dates.join("\n"), PHRASE_CELCAT_DATE_PASSEE];
  if (autres.length) blocs.push(`Forçable :\n${autres.join("\n")}`);
  if (soft.length) blocs.push(`Avertissement :\n${soft.join("\n")}`);
  return {
    texte: blocs.join("\n\n"),
    options: { title: "Modifier une date passée", confirmLabel: "Oui, modifier le passé", variant: "danger" },
  };
}

async function gererConflitPuisForcer(
  detail: DetailConflit,
  titres: { impossible: string; confirmLabel: string },
  forcer: () => Promise<void>,
): Promise<{ ok: true } | { ok: false; message: string }> {
  if (detail.blocking_conflicts.length > 0) {
    await alerterAsync(texteContraintes(detail), { title: titres.impossible });
    return { ok: false, message: detail.blocking_conflicts.join(" · ") };
  }
  const { texte, options } = texteEtOptionsForcage(
    detail.hard_conflicts,
    detail.blocking_conflicts,
    detail.soft_warnings,
    titres.confirmLabel,
  );
  const accepte = await confirmAsync(texte, options);
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

/** Même logique confirmer-puis-forcer, pour la création d'un évènement hors
 * maquette (retour Jules 23/09/2026) — `POST /placements/evenements` porte
 * les mêmes trois catégories de réponse que `POST /placements/personnalisees`. */
export async function creerEvenementAvecConfirmation(
  corps: CreerEvenementBody,
): Promise<{ ok: true; placement: Placement } | { ok: false; message: string }> {
  try {
    return { ok: true, placement: await creerEvenement(corps) };
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
        placement = await creerEvenement({ ...corps, force: true });
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

/**
 * Même confirmer-puis-forcer pour une séance CRÉÉE (✎ de la Vue Promo).
 *
 * Signalement du 22/09/2026 : « je ne peux pas encore modifier la séance une
 * fois créée ». L'enregistrement appelait l'API en direct : devant un conflit
 * forçable (semaine en cours, enseignant indisponible sur le papier…), il
 * affichait l'erreur et s'arrêtait, sans jamais proposer de forcer.
 */
export async function modifierSeancePersonnaliseeAvecConfirmation(
  sessionId: string,
  corps: ModifierSeanceBody,
): Promise<{ ok: true; placement: Placement } | { ok: false; message: string }> {
  try {
    return { ok: true, placement: await modifierSeancePersonnalisee(sessionId, corps) };
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
        placement = await modifierSeancePersonnalisee(sessionId, { ...corps, force: true });
      },
    );
    if (!resultat.ok || !placement) {
      return { ok: false, message: resultat.ok ? "Modification impossible" : resultat.message };
    }
    return { ok: true, placement };
  }
}
