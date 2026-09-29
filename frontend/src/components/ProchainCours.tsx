/**
 * « Prochain cours : mar. 13 oct. · 14h–15h30 · Écriture multimédia · H.205 »
 *
 * La question que se pose celui qui ouvre son lien, souvent sur téléphone
 * entre deux salles : où et quand est mon prochain cours ? La réponse
 * tient en une ligne, au-dessus de la grille, sans avoir à chercher la bonne
 * semaine ni la bonne case. « Voir » amène la grille sur ce jour-là.
 */

import { useEffect, useState } from "react";

import type { AppPayload } from "../types/app";
import type { IcsSession } from "../utils/ics";
import { horaireSeance, jourRelatif, prochaineSeance } from "../utils/planning";
import { groupLabelWithParcours } from "../utils/years";

interface ProchainCoursProps {
  payload: AppPayload;
  items: IcsSession[];
  /** Ajoute la promotion aux groupes (vue Enseignant). */
  showPromo?: boolean;
  /** Masque les groupes (vue TD/TP : c'est le sien). */
  sansGroupes?: boolean;
  onVoir?: (item: IcsSession) => void;
  /** Pour les tests : l'heure « actuelle ». */
  maintenant?: Date;
}

/** Heure courante, relue chaque minute : une page laissée ouverte doit
 *  passer d'elle-même à la séance suivante. */
function useMaintenant(fixe?: Date): Date {
  const [now, setNow] = useState(() => fixe ?? new Date());
  useEffect(() => {
    if (fixe) return;
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, [fixe]);
  return fixe ?? now;
}

export function ProchainCours({ payload, items, showPromo = false, sansGroupes = false, onVoir, maintenant }: ProchainCoursProps) {
  const now = useMaintenant(maintenant);
  if (!items.length) return null;
  const p = prochaineSeance(items, now);
  if (!p) {
    return (
      <p className="prochain prochain--vide" role="status">
        Plus aucun cours prévu d'ici la fin de la période.
      </p>
    );
  }
  const { item } = p;
  const groupes = sansGroupes
    ? ""
    : showPromo
      ? groupLabelWithParcours(item.g, payload.groupLabels, payload.groupParcours)
      : item.g.map((g) => payload.groupLabels[g] ?? g).join(", ");
  return (
    <div className={`prochain${p.enCours ? " prochain--encours" : ""}`} role="status">
      <span className="prochain-etiquette">{p.enCours ? "En cours" : "Prochain cours"}</span>
      <span className="prochain-quand">
        {jourRelatif(p.debut, now)} · {horaireSeance(item).libelle}
      </span>
      <span className="prochain-quoi">
        {item.n || item.c}
        <span className="prochain-code"> {item.c}</span>
        {item.t ? ` · ${item.t}` : ""}
        {groupes ? ` · ${groupes}` : ""}
      </span>
      <span className={`prochain-salle${item.r ? "" : " prochain-salle--absente"}`}>{item.r || "salle à définir"}</span>
      {onVoir && (
        <button type="button" className="btn btn--ghost btn--sm prochain-voir" onClick={() => onVoir(item)}>
          Voir dans la grille
        </button>
      )}
    </div>
  );
}
