/**
 * Nouveau semestre → « Dates du semestre » (17/11/2026).
 *
 * Le premier et le dernier jour de cours étaient écrits dans le code (1er
 * février pour le semestre pair). Ils se règlent ici, pour cette année et
 * les suivantes. L'écran rappelle ce qui aide à choisir : la fin de
 * l'autre semestre et les vacances qui tombent dans la période.
 */
import { useEffect, useState } from "react";

import {
  fixerPeriodeDesCours,
  lirePeriodeDesCours,
  retablirPeriodeDesCours,
  type PeriodeDesCours as Periode,
} from "../api/client";

const JOUR = new Intl.DateTimeFormat("fr-FR", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});
const COURT = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function versDate(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

export function PeriodeDesCours({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<Periode | null>(null);
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const recevoir = (p: Periode) => {
    setDonnees(p);
    setDebut(p.debut);
    setFin(p.fin);
  };

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    lirePeriodeDesCours(groupe)
      .then((p) => {
        if (!perime && p?.debut && p?.fin && p?.autre) recevoir(p);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees) return null;

  const verrouille = donnees.verrouille !== null;
  const change = debut !== donnees.debut || fin !== donnees.fin;

  const agir = async (action: () => Promise<Periode>) => {
    setOccupe(true);
    setErreur(null);
    try {
      recevoir(await action());
      onModifie();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setOccupe(false);
    }
  };

  return (
    <section className="dates-sae periode-cours" aria-labelledby="periode-cours-titre">
      <div className="periode-cours-tete">
        <h3 id="periode-cours-titre">Dates du semestre</h3>
        <span className="muted">
          Du {JOUR.format(versDate(donnees.debut))} au{" "}
          {JOUR.format(versDate(donnees.fin))}, {donnees.semaines} semaines de
          cours
        </span>
        {!donnees.personnalise && <span className="pill">Dates proposées</span>}
      </div>
      <p className="muted">
        {donnees.autre.libelle} : cours du{" "}
        {COURT.format(versDate(donnees.autre.debut))} au{" "}
        {COURT.format(versDate(donnees.autre.fin))} (les alternants peuvent
        finir plus tard).
        {donnees.vacances.length > 0 && (
          <>
            {" "}
            Vacances pendant ce semestre :{" "}
            {donnees.vacances
              .map(
                (v) =>
                  `du ${COURT.format(versDate(v.debut))} au ${COURT.format(versDate(v.fin))}`,
              )
              .join(", ")}
            .
          </>
        )}
      </p>
      {donnees.autre.chevauche && (
        <p className="periode-cours-alerte">
          <span className="pill warn">À vérifier</span> Ces dates chevauchent
          le {donnees.autre.libelle.toLowerCase()} : les salles et les
          enseignants déjà pris par ce semestre ne sont pas connus du calcul.
        </p>
      )}
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      {!verrouille && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!debut || !fin || !change) return;
            void agir(() => fixerPeriodeDesCours(groupe, debut, fin));
          }}
        >
          <label>
            Premier jour de cours
            <input
              type="date"
              value={debut}
              onChange={(e) => setDebut(e.target.value)}
            />
          </label>
          <label>
            Dernier jour de cours
            <input
              type="date"
              value={fin}
              min={debut || undefined}
              onChange={(e) => setFin(e.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !debut || !fin || !change}
          >
            Enregistrer ces dates
          </button>
          {donnees.personnalise && (
            <button
              type="button"
              className="btn btn--sm"
              disabled={occupe}
              onClick={() => void agir(() => retablirPeriodeDesCours(groupe))}
            >
              Revenir aux dates proposées
            </button>
          )}
        </form>
      )}
    </section>
  );
}
