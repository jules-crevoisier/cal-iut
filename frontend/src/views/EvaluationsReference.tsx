/**
 * Référence → Évaluations (19/10/2026, Jules) : les CM marqués « Éval » et le
 * dernier CM de chaque module, calculés en direct (`GET /api/v1/evaluations`).
 * Tout le monde n'a pas coché « Éval » dans Previsio : le dernier CM d'un
 * module non marqué est listé « À confirmer » — à demander à l'enseignant.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchEvaluations, validerEvaluation, type EvaluationLigne, type EvaluationsReponse } from "../api/client";
import { ChampRecherche } from "../components/ChampRecherche";
import { TriColonne, useTri } from "../components/TriColonne";
import { useDroits } from "../contexts/Droits";
import { csvDepuis, telechargerCsv } from "../utils/csv";

type CleEval = "date" | "module" | "enseignant" | "statut";

const LIBELLE_STATUT: Record<EvaluationLigne["statut"], string> = {
  eval: "Éval",
  confirmee: "Éval confirmée",
  a_confirmer: "À confirmer",
  non_placee: "Non placée",
  ecartee: "Pas une Éval",
};

const ORDRE_STATUT: Record<EvaluationLigne["statut"], number> = {
  eval: 0,
  confirmee: 1,
  a_confirmer: 2,
  non_placee: 3,
  ecartee: 4,
};

const VALEURS: Record<CleEval, (e: EvaluationLigne) => string | number> = {
  date: (e) => (e.date ? `${e.date} ${e.debut}` : "9999"),
  module: (e) => e.cours_code,
  enseignant: (e) => e.enseignants_noms.join(", "),
  statut: (e) => ORDRE_STATUT[e.statut],
};

function normaliser(t: string): string {
  return t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function dateCourte(iso: string | null): string {
  if (!iso) return "—";
  const [a, m, j] = iso.split("-");
  return `${j}/${m}/${a}`;
}

function horaire(e: EvaluationLigne): string {
  return e.debut ? `${e.debut}–${e.fin}` : "—";
}

export function EvaluationsReference() {
  const { revision, peutCompleter, apresEnregistrement } = useDroits();
  const [donnees, setDonnees] = useState<EvaluationsReponse | null>(null);
  const [erreur, setErreur] = useState(false);
  const [texte, setTexte] = useState("");
  const [statut, setStatut] = useState("");
  const [enCours, setEnCours] = useState<string | null>(null);
  const [echec, setEchec] = useState<string | null>(null);

  const recharger = useCallback(() => {
    return fetchEvaluations()
      .then((r) => {
        setErreur(false);
        setDonnees(r);
      })
      .catch(() => setErreur(true));
  }, []);

  useEffect(() => {
    void recharger();
  }, [revision, recharger]);

  const decider = async (e: EvaluationLigne, decision: "eval" | "pas_eval" | null) => {
    setEnCours(e.id);
    setEchec(null);
    try {
      await validerEvaluation(e.id, decision);
      await recharger();
      apresEnregistrement();
    } catch {
      setEchec(`Réponse non enregistrée pour ${e.cours_code}. Réessayer.`);
    } finally {
      setEnCours(null);
    }
  };

  const lignes = useMemo(() => donnees?.evaluations ?? [], [donnees]);
  const filtrees = useMemo(() => {
    const q = normaliser(texte.trim());
    return lignes.filter(
      (e) =>
        (statut ? e.statut === statut : e.statut !== "ecartee") &&
        (!q ||
          normaliser(
            `${e.cours_code} ${e.cours_nom} ${e.parcours} ${e.enseignants_noms.join(" ")} ${e.enseignants.join(" ")} ${e.groupes_libelles.join(" ")}`,
          ).includes(q)),
    );
  }, [lignes, texte, statut]);
  const { triees, tri, trierPar } = useTri<EvaluationLigne, CleEval>(filtrees, VALEURS, { cle: "statut", sens: 1 });

  if (erreur && !donnees) return <p className="ref-vide">Impossible de charger la liste des évaluations.</p>;
  if (!donnees) return <p className="ref-vide">Chargement…</p>;

  const exporter = () => {
    const entetes = ["Statut", "Date", "Jour", "Début", "Fin", "Module", "Intitulé", "Parcours", "Groupes", "Salle", "Enseignant(s)"];
    telechargerCsv(
      "evaluations-et-derniers-cm.csv",
      csvDepuis(
        entetes,
        triees.map((e) => [
          LIBELLE_STATUT[e.statut],
          e.date ?? "",
          e.jour_nom,
          e.debut,
          e.fin,
          e.cours_code,
          e.cours_nom,
          e.parcours,
          e.groupes_libelles.join("; "),
          e.salle_libelle ?? "",
          e.enseignants_noms.join("; "),
        ]),
      ),
    );
  };

  return (
    <>
      <div className="page-outils ref-barre">
        <ChampRecherche
          className="ref-recherche"
          placeholder="Filtrer : module, enseignant…"
          libelle="Filtrer les évaluations"
          valeur={texte}
          onChange={(v) => setTexte(v)}
        />
        <select aria-label="Statut" value={statut} onChange={(e) => setStatut(e.target.value)}>
          <option value="">Tous les statuts</option>
          <option value="eval">Éval</option>
          <option value="confirmee">Éval confirmée</option>
          <option value="a_confirmer">À confirmer</option>
          <option value="non_placee">Non placée</option>
          <option value="ecartee">Pas une Éval</option>
        </select>
        <span className="ref-resume">
          {donnees.nb_eval + (donnees.nb_confirmees ?? 0)} Éval · {donnees.nb_a_confirmer} à confirmer
          {donnees.nb_non_placees > 0 && ` · ${donnees.nb_non_placees} non placée${donnees.nb_non_placees > 1 ? "s" : ""}`}
        </span>
        <button type="button" className="btn" onClick={exporter} disabled={triees.length === 0}>
          Exporter en CSV
        </button>
      </div>
      <p className="ref-note">
        « Éval » : CM marqué Éval dans la maquette. « À confirmer » : dernier CM du module, pas marqué Éval — à demander à
        l'enseignant ; sa réponse s'enregistre ici (sans modifier le planning).
      </p>
      {echec && (
        <p className="ref-vide" role="alert">
          {echec}
        </p>
      )}
      <div className="panel carte-tableau carte-tableau--haute ref-tableau">
        <table className="ref ref-evaluations">
          <thead>
            <tr>
              <TriColonne cle="statut" tri={tri} onTrier={trierPar}>
                Statut
              </TriColonne>
              <TriColonne cle="date" tri={tri} onTrier={trierPar}>
                Date
              </TriColonne>
              <th>Heure</th>
              <TriColonne cle="module" tri={tri} onTrier={trierPar}>
                Module
              </TriColonne>
              <th className="ref-optionnel">Promo / groupes</th>
              <th className="ref-secondaire">Salle</th>
              <TriColonne cle="enseignant" tri={tri} onTrier={trierPar}>
                Enseignant
              </TriColonne>
              {peutCompleter && <th>Réponse</th>}
            </tr>
          </thead>
          <tbody>
            {triees.map((e) => (
              <tr key={e.id}>
                <td>
                  <span className={`ref-statut ref-statut--${e.statut}`}>{LIBELLE_STATUT[e.statut]}</span>
                </td>
                <td>
                  {e.jour_nom && <span className="ref-jour">{e.jour_nom.slice(0, 3)}. </span>}
                  {dateCourte(e.date)}
                </td>
                <td>{horaire(e)}</td>
                <td>
                  <strong>{e.cours_code}</strong> {e.cours_nom}
                  <div className="ref-sous">{e.parcours}</div>
                </td>
                <td className="ref-optionnel">{e.groupes_libelles.join(", ")}</td>
                <td className="ref-secondaire">{e.salle_libelle ?? "—"}</td>
                <td>
                  {e.enseignants.length === 0 ? "—" : e.enseignants.map((c, i) => e.enseignants_noms[i] ?? c).join(", ")}
                </td>
                {peutCompleter && (
                  <td>
                    <div className="ref-actions">
                      {e.statut === "a_confirmer" && (
                        <>
                          <button type="button" className="btn btn--sm" disabled={enCours === e.id} onClick={() => void decider(e, "eval")}>
                            C'est une Éval
                          </button>
                          <button type="button" className="btn btn--ghost btn--sm" disabled={enCours === e.id} onClick={() => void decider(e, "pas_eval")}>
                            Pas une Éval
                          </button>
                        </>
                      )}
                      {(e.statut === "confirmee" || e.statut === "ecartee") && (
                        <button type="button" className="btn btn--ghost btn--sm" disabled={enCours === e.id} onClick={() => void decider(e, null)}>
                          Annuler
                        </button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {triees.length === 0 && <p className="ref-vide">Aucune évaluation ne correspond.</p>}
      </div>
    </>
  );
}
