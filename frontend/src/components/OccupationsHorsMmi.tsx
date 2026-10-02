/**
 * Écran Celcat → « Occupations hors MMI » : une seule ligne de résumé.
 *
 * Le détail (conflits, salles et enseignants pris ailleurs, état du relevé,
 * relecture à la demande) vit depuis le 02/10/2026 dans la vue « Occupé
 * ailleurs » (`views/OccupeAilleursView.tsx`) : le gros bloc replié de cet
 * écran était jugé illisible. Ici : combien d'occupations, de quand, et le
 * chemin vers la vue.
 */
import { useEffect, useState } from "react";

import { fetchOccupationsHorsMmi, type OccupationsHorsMmi as Donnees } from "../api/client";
import { dateLisible, pluriel } from "../utils/celcatStatut";

function ouvrirOccupeAilleurs() {
  window.location.hash = "#vue=occupations";
}

export function OccupationsHorsMmi() {
  const [donnees, setDonnees] = useState<Donnees | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

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

  const resume = erreur
    ? `illisible : ${erreur}`
    : !donnees
      ? "chargement…"
      : donnees.absent
        ? "aucun relevé"
        : `${pluriel(donnees.evenements.length, "occupation")} · relevé ${dateLisible(donnees.releveLe)}`;

  return (
    <section className="panel celcat-occupations-resume" data-testid="occupations-hors-mmi" aria-labelledby="celcat-occ-titre">
      <h2 id="celcat-occ-titre">Occupations hors MMI</h2>
      <span className="celcat-sous-texte">{resume}</span>
      <button type="button" className="btn" onClick={ouvrirOccupeAilleurs}>
        Ouvrir Occupé ailleurs
      </button>
    </section>
  );
}
