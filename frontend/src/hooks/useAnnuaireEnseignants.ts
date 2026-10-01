/**
 * L'annuaire des enseignants (`GET /reference/enseignants`, 01/10/2026),
 * relu à chaque avance de la révision — pour ce qui n'est PAS dans le
 * payload : le téléphone (rôles edit / admin seulement).
 *
 * Une requête par révision, partagée entre les écrans qui la demandent
 * (fiche enseignant). `null` tant qu'elle n'est pas arrivée, sans compte
 * qui puisse le lire, ou en cas de panne : un complément, jamais un
 * blocage d'écran.
 */

import { useEffect, useState } from "react";

import { fetchAnnuaireEnseignants, type AnnuaireEnseignantsReponse } from "../api/client";
import { useDroits } from "../contexts/Droits";

let memo: { revision: number | null; promesse: Promise<AnnuaireEnseignantsReponse> } | null = null;

function charger(revision: number | null): Promise<AnnuaireEnseignantsReponse> {
  if (!memo || memo.revision !== revision || revision === null) {
    const promesse = fetchAnnuaireEnseignants();
    memo = { revision, promesse };
    promesse.catch(() => {
      if (memo?.promesse === promesse) memo = null;
    });
  }
  return memo.promesse;
}

/** Pour les tests : oublie la réponse gardée. */
export function oublierAnnuaireEnseignants(): void {
  memo = null;
}

export function useAnnuaireEnseignants(actif: boolean): AnnuaireEnseignantsReponse | null {
  const { revision } = useDroits();
  const [donnees, setDonnees] = useState<AnnuaireEnseignantsReponse | null>(null);
  useEffect(() => {
    if (!actif) {
      setDonnees(null);
      return;
    }
    let annule = false;
    charger(revision)
      .then((r) => {
        // Réponse inattendue (serveur plus ancien) : comme une panne.
        if (!annule) setDonnees(Array.isArray(r?.lignes) ? r : null);
      })
      .catch(() => {
        if (!annule) setDonnees(null);
      });
    return () => {
      annule = true;
    };
  }, [actif, revision]);
  return donnees;
}
