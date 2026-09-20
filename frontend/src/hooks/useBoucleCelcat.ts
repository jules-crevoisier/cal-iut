/**
 * La boucle « corriger, puis VÉRIFIER » — côté écran.
 *
 * Retour utilisateur du 16/09/2026 : « j'ai l'impression de devoir cliquer
 * plusieurs fois à des heures différentes sur "Corriger les écarts de cette
 * semaine" pour que ça les corrige vraiment. »
 *
 * Ce n'était pas une impression. Le clic met des jobs en file ; le worker
 * les pousse dans un autre conteneur ; et RIEN ne relisait Celcat ensuite.
 * L'écran relisait bien la comparaison, mais contre le MÊME relevé — si bien
 * qu'il se terminait toujours sur les écarts d'avant, y compris quand tout
 * avait réussi. Le relevé suivant n'arrivait que deux heures plus tard.
 *
 * Ce hook enchaîne ce que l'utilisateur faisait à la main, sur plusieurs
 * heures, et le fait en quelques minutes sous ses yeux :
 *
 *   1. mettre les corrections en file ;
 *   2. attendre que le worker soit REPASSÉ (sa trace a changé, ou la file
 *      s'est vidée) ;
 *   3. demander un nouveau relevé de Celcat, et attendre qu'il ARRIVE ;
 *   4. relire la comparaison : c'est seulement là qu'on sait.
 *
 * On compare les horodatages DU SERVEUR à eux-mêmes (« a changé ? ») et
 * jamais à l'horloge du navigateur : les deux conteneurs et le poste de
 * l'utilisateur n'ont aucune raison d'être à la même heure.
 *
 * Chaque attente a une limite, et la dépasser n'est PAS un échec : les
 * corrections restent en file, et l'écran dit précisément où ça s'est
 * arrêté. Un worker en recul après des échecs répétés peut attendre trente
 * minutes entre deux passages — mieux vaut le dire que tourner en rond.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  corrigerEcartsCelcat,
  fetchCelcatFile,
  fetchCelcatInstantane,
  rafraichirCelcatInstantane,
  type CelcatCorrection,
} from "../api/client";

export type EtapeBoucle =
  | "repos"
  | "envoi"
  | "attente_worker"
  | "attente_releve"
  | "verifie"
  | "interrompu"
  | "erreur";

export interface EtatBoucle {
  etape: EtapeBoucle;
  /** Ce que le serveur a répondu à la correction, s'il y en a eu une. */
  correction: CelcatCorrection | null;
  /** Une phrase qui dit où l'on en est — ou pourquoi on s'est arrêté. */
  message: string;
  /** La chaîne worker → relevé a-t-elle été engagée ? Faux quand rien n'est
   * parti : afficher alors trois étapes « fait » affirmerait une
   * vérification qui n'a pas eu lieu — exactement le défaut qu'on répare. */
  verification: boolean;
}

export interface OptionsBoucle {
  /** Relire comparaison, état et file une fois le nouveau relevé arrivé. */
  onVerifie: () => Promise<void> | void;
  intervalleMs?: number;
  limiteWorkerMs?: number;
  limiteReleveMs?: number;
}

const REPOS: EtatBoucle = { etape: "repos", correction: null, message: "", verification: false };

export function useBoucleCelcat(semaine: number | null, options: OptionsBoucle) {
  const { onVerifie } = options;
  const intervalle = options.intervalleMs ?? 4000;
  const limiteWorker = options.limiteWorkerMs ?? 6 * 60_000;
  const limiteReleve = options.limiteReleveMs ?? 4 * 60_000;

  const [etat, setEtat] = useState<EtatBoucle>(REPOS);
  // Jeton d'annulation : chaque lancement en prend un nouveau, et toute
  // attente en cours dont le jeton n'est plus le bon s'arrête d'elle-même.
  const jeton = useRef(0);
  const onVerifieRef = useRef(onVerifie);
  onVerifieRef.current = onVerifie;

  useEffect(() => {
    // Changer de semaine abandonne la boucle : son compte rendu parle d'une
    // autre semaine, et le laisser affiché le ferait lire comme celui-ci.
    jeton.current += 1;
    setEtat(REPOS);
  }, [semaine]);

  useEffect(
    () => () => {
      jeton.current += 1;
    },
    [],
  );

  const attendre = useCallback(
    (ms: number, moi: number) =>
      new Promise<boolean>((resolve) => {
        window.setTimeout(() => resolve(jeton.current === moi), ms);
      }),
    [],
  );

  /** Attend un nouveau relevé. Rend `false` si l'on a été interrompu. */
  const verifierReleve = useCallback(
    async (moi: number, correction: CelcatCorrection | null): Promise<boolean> => {
      const avant = (await fetchCelcatInstantane()).releve_le;
      await rafraichirCelcatInstantane();
      if (jeton.current !== moi) return false;
      setEtat({
        etape: "attente_releve",
        verification: true,
        correction,
        message: "Nouveau relevé de Celcat demandé — il arrive en général en moins d’une minute.",
      });

      const debut = Date.now();
      for (;;) {
        if (!(await attendre(intervalle, moi))) return false;
        const i = await fetchCelcatInstantane();
        if (jeton.current !== moi) return false;
        if (i.releve_le && i.releve_le !== avant) {
          if (i.erreur) {
            setEtat({
              etape: "erreur",
              verification: true,
              correction,
              message: `Le relevé de Celcat a échoué : ${i.erreur}`,
            });
            return false;
          }
          return true;
        }
        if (Date.now() - debut > limiteReleve) {
          setEtat({
            etape: "interrompu",
            verification: true,
            correction,
            message:
              "Le nouveau relevé n’est pas arrivé à temps : le worker est peut-être occupé. " +
              "Rien n’est perdu — relancez la vérification dans quelques minutes.",
          });
          return false;
        }
      }
    },
    [attendre, intervalle, limiteReleve],
  );

  const terminer = useCallback(
    async (moi: number, correction: CelcatCorrection | null) => {
      await onVerifieRef.current();
      if (jeton.current !== moi) return;
      setEtat({ etape: "verifie", correction, message: "Vérifié sur un relevé tout frais.", verification: true });
    },
    [],
  );

  const erreur = useCallback((moi: number, correction: CelcatCorrection | null, e: unknown) => {
    if (jeton.current !== moi) return;
    setEtat((precedent) => ({
      etape: "erreur",
      verification: precedent.verification,
      correction,
      message: e instanceof Error ? e.message : "La vérification a échoué.",
    }));
  }, []);

  /** Corrige la semaine, puis va jusqu'à la vérification. */
  const corriger = useCallback(
    async (supprimer: boolean) => {
      if (semaine === null) return;
      const moi = ++jeton.current;
      let correction: CelcatCorrection | null = null;
      setEtat({ etape: "envoi", correction: null, message: "Mise en file des corrections…", verification: true });
      try {
        const avant = await fetchCelcatFile();
        correction = await corrigerEcartsCelcat(semaine, { supprimer });
        if (jeton.current !== moi) return;

        // Rien à pousser, rien d'attendu : inutile de prendre le VPN pour
        // relire un Celcat où rien n'a pu changer de notre fait.
        if ((correction.total ?? 0) + (correction.deja_en_file ?? 0) === 0) {
          setEtat({ etape: "verifie", correction, message: "", verification: false });
          return;
        }

        setEtat({
          etape: "attente_worker",
          verification: true,
          correction,
          message: "En attente du passage du worker, qui pousse les corrections dans Celcat…",
        });
        const debut = Date.now();
        for (;;) {
          if (!(await attendre(intervalle, moi))) return;
          const f = await fetchCelcatFile();
          if (jeton.current !== moi) return;
          if ((f.passe_le && f.passe_le !== avant.passe_le) || f.en_attente === 0) break;
          if (Date.now() - debut > limiteWorker) {
            setEtat({
              etape: "interrompu",
              verification: true,
              correction,
              message:
                "Le worker n’est pas repassé depuis plusieurs minutes — il espace ses passages " +
                "après des échecs répétés. Les corrections restent en file et partiront à son retour.",
            });
            return;
          }
        }

        if (!(await verifierReleve(moi, correction))) return;
        await terminer(moi, correction);
      } catch (e) {
        erreur(moi, correction, e);
      }
    },
    [semaine, attendre, intervalle, limiteWorker, verifierReleve, terminer, erreur],
  );

  /** Relit Celcat sans rien corriger. */
  const verifier = useCallback(async () => {
    const moi = ++jeton.current;
    setEtat({ etape: "attente_releve", correction: null, message: "Demande d’un nouveau relevé de Celcat…", verification: true });
    try {
      if (!(await verifierReleve(moi, null))) return;
      await terminer(moi, null);
    } catch (e) {
      erreur(moi, null, e);
    }
  }, [verifierReleve, terminer, erreur]);

  /** Cesse d'attendre. N'annule rien côté serveur : les jobs restent en file. */
  const arreter = useCallback(() => {
    jeton.current += 1;
    setEtat((e) => ({
      ...e,
      etape: "interrompu",
      message: "Attente arrêtée. Les corrections déjà en file partiront quand même.",
    }));
  }, []);

  const occupe = etat.etape === "envoi" || etat.etape === "attente_worker" || etat.etape === "attente_releve";

  return { etat, occupe, corriger, verifier, arreter };
}
