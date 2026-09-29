/**
 * Sondage de la révision de l'état serveur (`GET /api/v1/version`, cf.
 * `api/revision.py`) — demande utilisateur du 29/09/2026 : « limiter les
 * connexions au serveur ».
 *
 * Avant : chaque action rechargeait tout (`/app-state`, ≈ 590 Ko), et un
 * collègue qui modifiait le planning depuis un autre poste restait invisible
 * jusqu'à un F5. Maintenant : un seul petit sondage (quelques octets, et même
 * un 304 vide la plupart du temps), et le rechargement complet n'a lieu QUE
 * quand la révision a bougé — quel que soit l'auteur de la modification.
 *
 * - Pas de sondage quand l'onglet est caché (`document.visibilityState`) :
 *   un onglet oublié ouvert toute la nuit ne coûte plus rien. Au retour de
 *   visibilité, sondage IMMÉDIAT, pour ne pas montrer un état périmé.
 * - `verifierMaintenant()` : après une écriture locale, plutôt que de
 *   recharger chaque ressource à la main (et souvent deux fois, depuis deux
 *   endroits différents), on vérifie la révision — les appels rapprochés
 *   sont regroupés en un seul (`delaiRegroupementMs`).
 * - Le tout premier sondage ne déclenche rien : l'écran vient de tout
 *   charger lui-même, il ne fait qu'apprendre la révision de départ.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchVersion } from "../api/client";
import type { VersionEtat } from "../api/client";

export interface OptionsRevision {
  /** Faux tant qu'aucun compte actif ni lien perso n'est là (401 sinon). */
  actif: boolean;
  /** Période du sondage quand l'onglet est visible. */
  intervalleMs: number;
  /** Appelé quand la révision a changé depuis la dernière connue. */
  onChange: (version: VersionEtat) => void;
  /** Fenêtre de regroupement des `verifierMaintenant()` rapprochés. */
  delaiRegroupementMs?: number;
}

export interface EtatRevision {
  /** Dernière révision connue, `null` avant le premier sondage réussi. */
  revision: number | null;
  /** Vérifie la révision au plus vite (appels rapprochés regroupés). */
  verifierMaintenant: () => void;
}

export function useRevision({
  actif,
  intervalleMs,
  onChange,
  delaiRegroupementMs = 150,
}: OptionsRevision): EtatRevision {
  const [revision, setRevision] = useState<number | null>(null);
  const connue = useRef<number | null>(null);
  // Référence plutôt que dépendance : l'appelant passe en général une
  // fonction recréée à chaque rendu, qui relancerait sinon la minuterie à
  // chaque rendu (et donc un sondage à chaque frappe clavier).
  const rappel = useRef(onChange);
  rappel.current = onChange;
  const regroupement = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Posé par `verifierMaintenant` : la PROCHAINE révision reçue doit être
  // signalée même si aucune n'était encore connue — y compris quand c'est
  // le sondage régulier, parti en même temps (requête partagée, cf.
  // `api/client.ts::request`), qui la traite en premier.
  const forcer = useRef(false);

  const verifier = useCallback(async (signalerSiInconnue: boolean) => {
    if (signalerSiInconnue) forcer.current = true;
    let version: VersionEtat;
    try {
      version = await fetchVersion();
    } catch {
      // Réseau coupé, serveur redémarré, session expirée : on retentera au
      // prochain tour, jamais d'erreur affichée pour un simple sondage.
      return;
    }
    const precedente = connue.current;
    if (precedente === version.revision) return;
    const signaler = precedente !== null || forcer.current;
    forcer.current = false;
    connue.current = version.revision;
    setRevision(version.revision);
    if (signaler) rappel.current(version);
  }, []);

  useEffect(() => {
    if (!actif) return;
    let minuterie: ReturnType<typeof setTimeout> | null = null;
    let enCours = false;
    let arrete = false;

    const visible = () => document.visibilityState === "visible";
    const planifier = () => {
      if (minuterie) clearTimeout(minuterie);
      minuterie = setTimeout(() => void tour(), intervalleMs);
    };
    const tour = async () => {
      minuterie = null;
      // Un tour déjà en vol replanifiera lui-même en se terminant.
      if (enCours || !visible()) return;
      enCours = true;
      try {
        await verifier(false);
      } finally {
        enCours = false;
      }
      if (!arrete && visible()) planifier();
    };
    const surVisibilite = () => {
      if (visible()) {
        void tour();
      } else if (minuterie) {
        clearTimeout(minuterie);
        minuterie = null;
      }
    };

    void tour();
    document.addEventListener("visibilitychange", surVisibilite);
    return () => {
      arrete = true;
      if (minuterie) clearTimeout(minuterie);
      document.removeEventListener("visibilitychange", surVisibilite);
    };
  }, [actif, intervalleMs, verifier]);

  useEffect(
    () => () => {
      if (regroupement.current) clearTimeout(regroupement.current);
    },
    [],
  );

  const verifierMaintenant = useCallback(() => {
    if (regroupement.current) clearTimeout(regroupement.current);
    regroupement.current = setTimeout(() => {
      regroupement.current = null;
      // Juste après une écriture locale : même si le premier sondage n'est
      // pas encore revenu, la révision a forcément bougé — on recharge.
      void verifier(true);
    }, delaiRegroupementMs);
  }, [verifier, delaiRegroupementMs]);

  return { revision, verifierMaintenant };
}
