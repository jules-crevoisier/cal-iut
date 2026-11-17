/**
 * Nouveau semestre → « Plafonds hebdomadaires » (17/11/2026).
 *
 * Le nombre maximal de créneaux de 1 h 30 par semaine pour un groupe
 * d'étudiants, un groupe d'alternants et un enseignant était écrit dans le
 * code du calcul. Il se règle ici, par semestre : le calcul et les contrôles
 * du planning lisent la même valeur.
 */
import { useEffect, useState } from "react";

import {
  lirePlafonds,
  reglerPlafonds,
  retablirPlafonds,
  type Plafonds,
  type PlafondsReponse,
} from "../api/client";

const CHAMPS: { cle: keyof Plafonds; libelle: string }[] = [
  { cle: "promo", libelle: "Étudiants" },
  { cle: "alternants", libelle: "Alternants" },
  { cle: "enseignant", libelle: "Enseignant" },
];

/** 23 créneaux → « 34 h 30 ». */
export function heures(creneaux: number): string {
  const minutes = creneaux * 90;
  const reste = minutes % 60;
  return `${Math.floor(minutes / 60)} h${reste ? ` ${reste}` : ""}`;
}

export function PlafondsHebdo({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<PlafondsReponse | null>(null);
  const [saisie, setSaisie] = useState<Plafonds | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const recevoir = (r: PlafondsReponse) => {
    setDonnees(r);
    setSaisie({ ...r.plafonds });
  };

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setSaisie(null);
    setErreur(null);
    lirePlafonds(groupe)
      .then((r) => {
        if (!perime && r?.plafonds && r?.origine) recevoir(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees || !saisie) return null;

  const verrouille = donnees.verrouille !== null;
  const change = CHAMPS.some((c) => saisie[c.cle] !== donnees.plafonds[c.cle]);
  const valide = CHAMPS.every(
    (c) =>
      Number.isInteger(saisie[c.cle]) &&
      saisie[c.cle] >= donnees.mini &&
      saisie[c.cle] <= donnees.maxi,
  );
  const p = donnees.plafonds;

  const agir = async (action: () => Promise<PlafondsReponse>) => {
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
    <details className="dates-sae regles-modules">
      <summary>
        <h3>Plafonds hebdomadaires</h3>
        <span className="muted">
          Étudiants {heures(p.promo)}, alternants {heures(p.alternants)}, enseignant{" "}
          {heures(p.enseignant)}
          {donnees.personnalise ? "" : " (valeurs d’origine)"}
        </span>
      </summary>
      <p className="muted">
        Le nombre maximal de créneaux de 1 h 30 par semaine. Le calcul ne le dépasse jamais, et le
        planning de ce semestre est contrôlé avec la même valeur. Un plafond plus bas allège les
        semaines mais peut empêcher de tout placer ; un plafond plus haut donne de la marge au calcul.
      </p>
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
            if (!change || !valide) return;
            void agir(() => reglerPlafonds(groupe, saisie));
          }}
        >
          {CHAMPS.map((c) => (
            <label key={c.cle}>
              {c.libelle} (créneaux par semaine)
              <span className="plafonds-champ">
                <input
                  type="number"
                  min={donnees.mini}
                  max={donnees.maxi}
                  value={Number.isFinite(saisie[c.cle]) ? saisie[c.cle] : ""}
                  aria-label={`Plafond ${c.libelle.toLowerCase()}`}
                  onChange={(e) => setSaisie({ ...saisie, [c.cle]: e.target.valueAsNumber })}
                />
                <span className="muted">
                  {Number.isFinite(saisie[c.cle]) ? heures(saisie[c.cle]) : ""}
                  {saisie[c.cle] !== donnees.origine[c.cle] && ` (origine : ${donnees.origine[c.cle]})`}
                </span>
              </span>
            </label>
          ))}
          <button type="submit" className="btn btn--sm" disabled={occupe || !change || !valide}>
            Enregistrer ces plafonds
          </button>
          {donnees.personnalise && (
            <button
              type="button"
              className="btn btn--sm"
              disabled={occupe}
              onClick={() => void agir(() => retablirPlafonds(groupe))}
            >
              Revenir aux plafonds d’origine
            </button>
          )}
        </form>
      )}
    </details>
  );
}
