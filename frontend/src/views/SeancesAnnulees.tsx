/**
 * Nouveau semestre → « Séances annulées » (lot 6, 16/11/2026).
 *
 * Une séance qui n'aura pas lieu (reliquat inexploitable, intervenant qui
 * ne l'assure plus) doit être retirée AVANT le calcul, sinon elle est
 * placée comme les autres. Jusque-là, il fallait un fichier et un
 * développeur. Ici, l'administrateur choisit le module, la séance, et
 * donne le motif.
 */
import { useEffect, useState } from "react";

import {
  annulerSeance,
  lireAnnulations,
  lireSeancesDuModule,
  retablirSeance,
  type AnnulationsReponse,
  type SeanceDuModule,
} from "../api/client";

export function SeancesAnnulees({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<AnnulationsReponse | null>(null);
  const [code, setCode] = useState("");
  const [seances, setSeances] = useState<SeanceDuModule[]>([]);
  const [seance, setSeance] = useState("");
  const [motif, setMotif] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    setCode("");
    lireAnnulations(groupe)
      .then((r) => {
        if (!perime && Array.isArray(r?.annulees) && Array.isArray(r?.modules))
          setDonnees(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  useEffect(() => {
    let perime = false;
    setSeances([]);
    setSeance("");
    if (!code) return undefined;
    lireSeancesDuModule(groupe, code)
      .then((liste) => {
        if (!perime) setSeances(liste);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe, code, donnees]);

  if (!donnees || donnees.modules.length === 0) return null;

  const verrouille = donnees.verrouille !== null;
  const n = donnees.annulees.length;

  const agir = async (action: () => Promise<AnnulationsReponse>) => {
    setOccupe(true);
    setErreur(null);
    try {
      setDonnees(await action());
      setSeance("");
      setMotif("");
      onModifie();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setOccupe(false);
    }
  };

  return (
    <details className="dates-sae seances-annulees">
      <summary>
        <h3>Séances annulées</h3>
        <span className="muted">
          {n === 0
            ? "Aucune"
            : `${n} séance${n > 1 ? "s" : ""} ne ser${n > 1 ? "ont" : "a"} pas placée${n > 1 ? "s" : ""}`}
        </span>
      </summary>
      <p className="muted">
        Une séance annulée n’est pas placée par le calcul et n’apparaît plus
        dans les séances à placer. Cela vaut pour la prochaine génération.
      </p>
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      {n > 0 && (
        <ul>
          {donnees.annulees.map((a) => (
            <li key={a.session_id} className="dates-sae-ligne">
              <div className="dates-sae-quoi">
                <div className="dates-sae-titre">
                  <strong>{a.code}</strong> <span>{a.nom}</span>
                  {a.existe && <span className="muted"> · {a.libelle}</span>}
                  {!a.existe && (
                    <>
                      {" "}
                      <span
                        className="pill"
                        title={`${a.session_id} : la maquette a changé, cette séance n’existe plus`}
                      >
                        N’existe plus
                      </span>
                    </>
                  )}
                </div>
                <div className="muted">
                  {a.motif}
                  {a.demande_par ? ` (${a.demande_par})` : ""}
                </div>
              </div>
              {!verrouille && (
                <button
                  type="button"
                  className="btn btn--sm"
                  disabled={occupe}
                  aria-label={`Rétablir ${a.code} ${a.libelle}`}
                  onClick={() =>
                    void agir(() => retablirSeance(groupe, a.session_id))
                  }
                >
                  Rétablir
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!verrouille && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!seance || !motif.trim()) return;
            void agir(() => annulerSeance(groupe, seance, motif.trim()));
          }}
        >
          <label>
            Module
            <select value={code} onChange={(e) => setCode(e.target.value)}>
              <option value="">Choisir…</option>
              {donnees.modules.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.semestre} · {m.code} {m.nom}
                </option>
              ))}
            </select>
          </label>
          <label>
            Séance
            <select
              value={seance}
              disabled={!code || seances.length === 0}
              onChange={(e) => setSeance(e.target.value)}
            >
              <option value="">Choisir…</option>
              {seances.map((s) => (
                <option key={s.id} value={s.id} disabled={s.annulee}>
                  {s.libelle}
                  {s.annulee ? " (annulée)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="seances-annulees-motif">
            Motif
            <input
              type="text"
              value={motif}
              maxLength={300}
              placeholder="Pourquoi cette séance n’aura pas lieu"
              onChange={(e) => setMotif(e.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !seance || !motif.trim()}
          >
            Annuler cette séance
          </button>
        </form>
      )}
    </details>
  );
}
