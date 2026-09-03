/**
 * Confirmation « forcer malgré le conflit » — remplace `window.confirm(...)`
 * (retour utilisateur 28/08/2026 : « j'ai désactivé les popups et du coup
 * ça casse le fonctionnement, il faudrait donc internaliser les popups »).
 * `window.confirm` dépend d'un réglage navigateur qui peut être désactivé
 * (bloqueur de popup, mode kiosque...) — dans ce cas il renvoie silencieusement
 * `false`, ce qui annulait TOUJOURS le forçage sans que rien ne s'affiche.
 *
 * Petit event-bus + Promise : `confirmAsync` peut être appelé depuis du code
 * non-composant (utils/moveSession.ts, utils/placement.ts) exactement comme
 * `window.confirm`, mais déclenche une VRAIE modale React
 * (`components/ConfirmModal.tsx`, montée une fois dans App.tsx) au lieu
 * d'une boîte de dialogue du navigateur.
 */

export interface ConfirmRequest {
  title: string;
  message: string;
  /** `null` = rien a confirmer : la modale n'affiche qu'un bouton de
   *  fermeture. Sert aux obstacles que « Forcer » ne leve pas (cf.
   *  `alerterAsync`) — proposer un bouton qui echouera est pire que ne rien
   *  proposer. */
  confirmLabel: string | null;
  cancelLabel: string;
}

type Listener = (request: ConfirmRequest | null) => void;

let listener: Listener | null = null;
let pendingResolve: ((value: boolean) => void) | null = null;

export function registerConfirmListener(fn: Listener): () => void {
  listener = fn;
  return () => {
    if (listener === fn) listener = null;
  };
}

export function confirmAsync(
  message: string,
  options?: { title?: string; confirmLabel?: string; cancelLabel?: string },
): Promise<boolean> {
  return new Promise((resolve) => {
    // Une seule confirmation à la fois : une précédente encore ouverte est
    // annulée plutôt que de laisser sa Promise ne jamais se résoudre.
    if (pendingResolve) pendingResolve(false);
    pendingResolve = resolve;
    listener?.({
      // "Conflit détecté" par défaut : couvre tous les appels existants
      // (glisser-déposer, placement manuel) sans les modifier. Un appel
      // pour un cas non conflictuel (ex. confirmer un envoi de mail,
      // retour utilisateur 28/08/2026 : « je veux des vrais popup de
      // confirmation ») passe son propre `title`.
      title: options?.title ?? "Conflit détecté",
      message,
      confirmLabel: options?.confirmLabel ?? "Forcer quand même",
      cancelLabel: options?.cancelLabel ?? "Annuler",
    });
  });
}

/**
 * Message SANS choix — l'action est impossible, pas discutable.
 *
 * Réservé aux verrous institutionnels (PAC, SAE pour WR*, férié…).
 * L'indisponibilité enseignant et l'ordre pédagogique sont forçables
 * (28/08 et 03/09/2026) : pour ceux-là, utiliser `confirmAsync`.
 */
export function alerterAsync(message: string, options?: { title?: string; cancelLabel?: string }): Promise<void> {
  return new Promise((resolve) => {
    if (pendingResolve) pendingResolve(false);
    pendingResolve = () => resolve();
    listener?.({
      title: options?.title ?? "Impossible",
      message,
      confirmLabel: null,
      cancelLabel: options?.cancelLabel ?? "J'ai compris",
    });
  });
}

export function resolveConfirm(value: boolean): void {
  pendingResolve?.(value);
  pendingResolve = null;
  listener?.(null);
}
