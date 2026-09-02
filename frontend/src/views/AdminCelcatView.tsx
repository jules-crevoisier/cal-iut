/**
 * Administration Celcat — interrupteur de saisie, semaines à valider,
 * extras Live-only (Ajouter / Ignorer) et journal des blocages.
 */
import { useCallback, useEffect, useState } from "react";

import {
  ajouterExtraCelcat,
  fetchCelcatEtat,
  fetchCelcatExtras,
  fetchCelcatLogs,
  ignorerExtraCelcat,
  patchCelcatSaisie,
  validerSemainesCelcat,
  type CelcatEtat,
  type CelcatExtra,
  type CelcatLog,
} from "../api/client";

const SEMAINES = Array.from({ length: 30 }, (_, i) => i + 1);

export function AdminCelcatView() {
  const [etat, setEtat] = useState<CelcatEtat | null>(null);
  const [extras, setExtras] = useState<CelcatExtra[]>([]);
  const [logs, setLogs] = useState<CelcatLog[]>([]);
  const [semaines, setSemaines] = useState<number[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [e, x, l] = await Promise.all([
        fetchCelcatEtat(),
        fetchCelcatExtras("ouvert"),
        fetchCelcatLogs(50),
      ]);
      setEtat(e);
      setSemaines(e.semaines_validees);
      setExtras(x.extras);
      setLogs(l.items);
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur de chargement");
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const basculerSaisie = async (active: boolean) => {
    setEnCours(true);
    try {
      setEtat(await patchCelcatSaisie(active));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const valider = async () => {
    setEnCours(true);
    try {
      setEtat(await validerSemainesCelcat(semaines));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const traiterExtra = async (id: string, action: "ajouter" | "ignorer") => {
    setEnCours(true);
    try {
      if (action === "ajouter") {
        await ajouterExtraCelcat(id);
      } else {
        await ignorerExtraCelcat(id);
      }
      setExtras((prev) => prev.filter((x) => x.id !== id));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const basculerSemaine = (n: number) => {
    setSemaines((prev) => (prev.includes(n) ? prev.filter((s) => s !== n) : [...prev, n].sort((a, b) => a - b)));
  };

  if (erreur && !etat) {
    return (
      <section className="view">
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      </section>
    );
  }

  if (!etat) {
    return (
      <section className="view">
        <div className="panel">
          <p className="muted">Chargement…</p>
        </div>
      </section>
    );
  }

  return (
    <section className="view">
      {erreur && (
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      )}

      <div className="panel">
        <h3>Saisie Celcat</h3>
        <label>
          <input
            type="checkbox"
            checked={etat.saisie_active}
            disabled={enCours}
            onChange={(ev) => void basculerSaisie(ev.target.checked)}
          />{" "}
          Saisie active
        </label>
        <p className="muted">
          {etat.worker_ok ? "Worker joignable." : "Worker injoignable."}
          {etat.valide_le ? ` Dernière validation : ${etat.valide_le}.` : ""}
        </p>
      </div>

      <div className="panel">
        <h3>Semaines à envoyer</h3>
        <div>
          {SEMAINES.map((n) => {
            const libelle = n <= 2 ? `Semaine ${n}` : `S. ${n}`;
            return (
              <label key={n}>
                <input
                  type="checkbox"
                  checked={semaines.includes(n)}
                  aria-label={libelle}
                  onChange={() => basculerSemaine(n)}
                />{" "}
                {libelle}
              </label>
            );
          })}
        </div>
        <button type="button" className="btn btn--accent" disabled={enCours} onClick={() => void valider()}>
          Valider
        </button>
      </div>

      <div className="panel">
        <h3>Extras Live</h3>
        {extras.length === 0 ? (
          <p className="muted">Aucun extra ouvert.</p>
        ) : (
          <ul>
            {extras.map((x) => (
              <li key={x.id}>
                {x.course_code || x.libelle || x.module_nom || x.id}{" "}
                <button
                  type="button"
                  className="btn btn--sm"
                  disabled={enCours}
                  aria-label={`Ajouter ${x.course_code || x.libelle || x.id}`}
                  onClick={() => void traiterExtra(x.id, "ajouter")}
                >
                  Ajouter
                </button>{" "}
                <button
                  type="button"
                  className="btn btn--sm btn--ghost"
                  disabled={enCours}
                  aria-label={`Ignorer ${x.course_code || x.libelle || x.id}`}
                  onClick={() => void traiterExtra(x.id, "ignorer")}
                >
                  Ignorer
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel">
        <h3>Journal</h3>
        {logs.length === 0 ? (
          <p className="muted">Aucune entrée.</p>
        ) : (
          <ul>
            {logs.map((item, i) => (
              <li key={`${item.session_id ?? "log"}-${i}`}>
                {item.kind}
                {item.motif ? ` — ${item.motif}` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
