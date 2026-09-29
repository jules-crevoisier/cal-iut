/**
 * Chiffres clés en tête de la Vue Promo (maquette « Lumière » validée par
 * l'utilisateur le 29/09/2026) : séances de la semaine, points à corriger,
 * séances non placées, tâches ouvertes. Chaque tuile mène où l'on agit :
 * « Non placées » ouvre la colonne « À placer » de cette même vue.
 *
 * Mêmes calculs que l'Accueil (`AccueilView`) ; jamais sur le lien public.
 */
import { useEffect, useState } from "react";

import { fetchDoublons, fetchTaches, type Tache } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { compterATraiter } from "../utils/todo";

interface PromoTuilesProps {
  payload: AppPayload;
  /** Index solveur de la semaine affichée (`null` : semaine fermée). */
  solverWeek: number | null;
  setRoute?: (patch: Partial<Route>) => void;
  onOuvrirAPlacer: () => void;
}

function ecart(n: number, avant: number): string {
  const d = n - avant;
  // Court : la tuile fait la moitié d'un téléphone de large.
  if (d === 0) return "autant que la précédente";
  return `${d > 0 ? "+" : "−"}${Math.abs(d)} vs semaine préc.`;
}

export function PromoTuiles({ payload, solverWeek, setRoute, onOuvrirAPlacer }: PromoTuilesProps) {
  const [doublons, setDoublons] = useState<number | null>(null);
  const [taches, setTaches] = useState<Tache[] | null>(null);

  useEffect(() => {
    let actif = true;
    fetchDoublons()
      .then((d) => actif && setDoublons(Array.isArray(d) ? d.length : 0))
      .catch(() => actif && setDoublons(0));
    fetchTaches()
      .then((t) => actif && setTaches(Array.isArray(t) ? t : []))
      .catch(() => actif && setTaches([]));
    return () => {
      actif = false;
    };
  }, []);

  const seances = solverWeek === null ? null : payload.rows.filter((r) => r.w === solverWeek).length;
  const precedente =
    solverWeek === null || solverWeek === 0 ? null : payload.rows.filter((r) => r.w === solverWeek - 1).length;
  const compte = compterATraiter(payload, doublons ?? 0);
  const nonPlacees = payload.seancesNonPlacees?.length ?? 0;
  const ouvertes = (taches ?? []).filter((t) => t.colonne !== "fait");
  const urgentes = ouvertes.filter((t) => t.priorite === "urgente").length;

  return (
    <section className="promo-tuiles" aria-label="Chiffres de la semaine">
      <div className="promo-tuile">
        <span className="promo-tuile-libelle">Séances cette semaine</span>
        <strong className="promo-tuile-valeur">{seances ?? "—"}</strong>
        <span className="promo-tuile-detail">
          {seances === null ? "Semaine sans cours" : precedente === null ? "toutes promos" : ecart(seances, precedente)}
        </span>
      </div>
      <button type="button" className="promo-tuile" onClick={() => setRoute?.({ vue: "apf" })}>
        <span className="promo-tuile-libelle">À corriger</span>
        <strong className={`promo-tuile-valeur${compte.aCorriger > 0 ? " is-bad" : ""}`}>
          {doublons === null ? "…" : compte.aCorriger}
        </strong>
        <span className="promo-tuile-detail">
          {doublons ? `dont ${doublons} doublon${doublons > 1 ? "s" : ""}` : "ouvrir « À traiter »"}
        </span>
      </button>
      <button type="button" className="promo-tuile" onClick={onOuvrirAPlacer}>
        <span className="promo-tuile-libelle">Non placées</span>
        <strong className={`promo-tuile-valeur${nonPlacees > 0 ? " is-warn" : ""}`}>{nonPlacees}</strong>
        <span className="promo-tuile-detail">{nonPlacees > 0 ? "à poser sur la grille" : "tout est placé"}</span>
      </button>
      <button type="button" className="promo-tuile" onClick={() => setRoute?.({ vue: "taches" })}>
        <span className="promo-tuile-libelle">Tâches ouvertes</span>
        <strong className="promo-tuile-valeur">{taches === null ? "…" : ouvertes.length}</strong>
        <span className="promo-tuile-detail">
          {urgentes ? `dont ${urgentes} urgente${urgentes > 1 ? "s" : ""}` : "aucune urgente"}
        </span>
      </button>
    </section>
  );
}
