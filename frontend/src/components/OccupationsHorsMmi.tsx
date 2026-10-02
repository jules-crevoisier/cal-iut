/**
 * Écran Celcat → « Occupations hors MMI » : une seule ligne.
 *
 * Combien d'occupations à venir, de quand date le relevé, et un bouton pour
 * relire Celcat tout de suite. Le détail n'a plus d'écran à lui (retour de
 * Jules, 02/10/2026 soir) : les occupations apparaissent en grisé sur les
 * Vues Enseignant et Salle, et l'appli prévient quand on pose une séance
 * dessus.
 */
import { useCallback, useEffect, useState } from "react";

import {
  fetchOccupationsHorsMmi,
  rafraichirOccupationsHorsMmi,
  type OccupationsHorsMmi as Donnees,
} from "../api/client";
import { dateLisible } from "../utils/celcatStatut";

export function OccupationsHorsMmi() {
  const [donnees, setDonnees] = useState<Donnees | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const charger = useCallback(async () => {
    try {
      setDonnees(await fetchOccupationsHorsMmi());
      setErreur(null);
    } catch (e: unknown) {
      setErreur(e instanceof Error ? e.message : "Relevé illisible.");
    }
  }, []);

  useEffect(() => {
    let actif = true;
    fetchOccupationsHorsMmi()
      .then((d) => {
        if (actif) setDonnees(d);
      })
      .catch((e: unknown) => {
        if (actif) setErreur(e instanceof Error ? e.message : "Relevé illisible.");
      });
    return () => {
      actif = false;
    };
  }, []);

  const relire = async () => {
    setEnvoi(true);
    setMessage(null);
    try {
      const r = await rafraichirOccupationsHorsMmi();
      setMessage(r.message);
      await charger();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : "Demande impossible.");
    } finally {
      setEnvoi(false);
    }
  };

  const resume = erreur
    ? `illisible : ${erreur}`
    : !donnees
      ? "chargement…"
      : donnees.absent
        ? "aucun relevé"
        : `${donnees.evenements.length} à venir · relevé ${dateLisible(donnees.releveLe)}`;

  return (
    <section className="panel celcat-occupations-resume" data-testid="occupations-hors-mmi" aria-labelledby="celcat-occ-titre">
      <h2 id="celcat-occ-titre">Occupations hors MMI</h2>
      <span className="celcat-sous-texte">{resume}</span>
      <button
        type="button"
        className="btn"
        onClick={() => void relire()}
        disabled={envoi || !donnees || donnees.demandeEnCours || donnees.lectureActive === false}
      >
        {envoi || donnees?.demandeEnCours ? "Relecture demandée…" : "Relire maintenant"}
      </button>
      {message && (
        <p className="celcat-occupations-message" role="status">
          {message}
        </p>
      )}
      <p className="celcat-sous-texte celcat-occupations-aide">
        Salles et enseignants pris hors MMI. Ils apparaissent en grisé dans les Vues Enseignant et Salle, et l'appli prévient quand on
        pose une séance dessus.
      </p>
    </section>
  );
}
