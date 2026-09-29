/**
 * Qui peut compléter quoi, et comment prévenir l'appli qu'on vient de le
 * faire (29/09/2026, « il faut pouvoir ajouter l'info et l'enregistrer »).
 *
 * Posé une fois par `App.tsx` ; lu par les écrans qui signalent un manque
 * (annuaire des enseignants, fiches, « À traiter », Référence) pour décider
 * s'ils montrent un champ « Ajouter » ou seulement le manque. Sans
 * fournisseur — lien public, test d'un composant isolé —, c'est la lecture
 * seule : le manque reste affiché, sans bouton.
 *
 * `apresEnregistrement` : la révision serveur vient d'avancer ; `App.tsx`
 * la relit tout de suite (`useRevision().verifierMaintenant`), ce qui
 * recharge le planning et, par `revision`, la liste des manques.
 */

import { createContext, useContext, useEffect, useState } from "react";

import { fetchManques, type ListeManques, type Manque } from "../api/client";

export type RoleCompte = "read_only" | "edit" | "admin";

export interface Droits {
  role: RoleCompte | null;
  /** Dernière révision connue de l'état serveur (`null` avant le premier sondage). */
  revision: number | null;
  apresEnregistrement: () => void;
}

const LECTURE_SEULE: Droits = { role: null, revision: null, apresEnregistrement: () => undefined };

export const ContexteDroits = createContext<Droits>(LECTURE_SEULE);

export interface DroitsCalcules extends Droits {
  /** Mail, nom, intitulé, capacité et type (rôle `edit` ou `admin`). */
  peutCompleter: boolean;
  /** Correspondances Celcat (rôle `admin`). */
  estAdmin: boolean;
}

export function useDroits(): DroitsCalcules {
  const d = useContext(ContexteDroits);
  return { ...d, peutCompleter: d.role === "edit" || d.role === "admin", estAdmin: d.role === "admin" };
}

/** Ce compte peut-il compléter ce manque depuis l'appli ? */
export function peutCompleterManque(role: RoleCompte | null, m: Pick<Manque, "role_requis">): boolean {
  if (!role || !m.role_requis) return false;
  if (m.role_requis === "admin") return role === "admin";
  return role === "edit" || role === "admin";
}

/**
 * La liste des manques (`GET /reference/manques`), relue à chaque avance de
 * la révision. `null` tant qu'elle n'est pas arrivée, et pour un lien public
 * (pas de compte : la route répondrait 401). Une réponse inattendue ou une
 * panne rendent une liste vide : un complément, jamais un blocage d'écran.
 */
export function useManques(): Manque[] | null {
  const { role, revision } = useContext(ContexteDroits);
  const [liste, setListe] = useState<Manque[] | null>(null);
  useEffect(() => {
    if (!role) {
      setListe(null);
      return;
    }
    let annule = false;
    fetchManques()
      .then((r: ListeManques) => {
        if (!annule) setListe(Array.isArray(r?.manques) ? r.manques : []);
      })
      .catch(() => {
        if (!annule) setListe((l) => l ?? []);
      });
    return () => {
      annule = true;
    };
  }, [role, revision]);
  return liste;
}
