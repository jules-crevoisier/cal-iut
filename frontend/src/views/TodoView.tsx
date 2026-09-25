import { useCallback, useEffect, useMemo, useState } from "react";

import type { Doublon, DoublonHebdoRun } from "../api/client";
import { executerControleDoublonsHebdo, fetchControleDoublonsHebdo, fetchDoublons } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { estNouveau, libelleControleHebdo } from "../utils/controleDoublonsHebdo";
import { coursEnConflit, grouperDoublonsParSemaine, libelleCreneauDoublon, routeVersDoublon } from "../utils/doublons";
import { buildTodoList } from "../utils/todo";
import "./TodoView.css";

interface TodoViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

export function TodoView({ payload, setRoute }: TodoViewProps) {
  const items = useMemo(() => buildTodoList(payload), [payload]);

  // Doublons salle/enseignant (retour Kyllian Bresson 25/09/2026, cf.
  // `api/doublons.py`) : contrôle À POSTERIORI, distinct de `buildTodoList`
  // ci-dessus (dérivé de `payload`, calculé une fois côté serveur au chargement
  // de l'app) — appelé séparément car il balaie `state.timetable` en direct,
  // pour attraper les doublons introduits par une retouche manuelle depuis.
  const [doublons, setDoublons] = useState<Doublon[] | null>(null);
  const [erreurDoublons, setErreurDoublons] = useState<string | null>(null);

  const chargerDoublons = useCallback(async () => {
    try {
      const liste = await fetchDoublons();
      setDoublons(liste);
      setErreurDoublons(null);
    } catch (e) {
      setErreurDoublons(e instanceof Error ? e.message : "Erreur de chargement des doublons.");
    }
  }, []);

  useEffect(() => {
    void chargerDoublons();
  }, [chargerDoublons]);

  const groupesDoublons = useMemo(
    () => (doublons ? grouperDoublonsParSemaine(payload, doublons) : []),
    [payload, doublons],
  );

  // Contrôle HEBDOMADAIRE automatique (Jules Crevoisier, 25/09/2026, dicté :
  // « on veut faire quelque chose qui vérifie chaque semaine [...] »). Le
  // filet tourne côté serveur SANS écran (`api/controle_doublons_hebdo.py`,
  // hooké dans `_apres_ecriture_planning`/`startup()`) — cette section
  // n'affiche que son DERNIER résultat, distinct de la liste ci-dessus (qui
  // recalcule les doublons EN DIRECT à chaque ouverture de l'écran).
  // `undefined` = pas encore chargé, `null` = jamais exécuté (aucun run en
  // historique).
  const [controleHebdo, setControleHebdo] = useState<DoublonHebdoRun | null | undefined>(undefined);
  const [executionHebdoEnCours, setExecutionHebdoEnCours] = useState(false);

  useEffect(() => {
    let annule = false;
    fetchControleDoublonsHebdo()
      .then((dernier) => {
        if (!annule) setControleHebdo(dernier);
      })
      // Ne bloque jamais l'écran : ce résumé est un complément à la liste
      // ci-dessus, pas une donnée dont dépend le reste de « À traiter »
      // (même esprit que `verifier_si_necessaire` côté serveur, qui ne
      // lève jamais).
      .catch(() => {
        if (!annule) setControleHebdo(null);
      });
    return () => {
      annule = true;
    };
  }, []);

  const verifierMaintenant = useCallback(async () => {
    setExecutionHebdoEnCours(true);
    try {
      const resultat = await executerControleDoublonsHebdo();
      setControleHebdo(resultat);
    } catch {
      // Le dernier résultat connu reste affiché — jamais d'écran cassé pour
      // un contrôle manuel raté.
    } finally {
      setExecutionHebdoEnCours(false);
    }
  }, []);

  return (
    <section className="view">
      <div className="panel">
        <h3>Ce qui demande une décision</h3>
        <p className="muted">
          Agrégé depuis la sortie brute du solveur : contraintes enseignantes violées, journées trouées. Chaque
          ligne ouvre le créneau concerné.
        </p>
        {items.length === 0 ? (
          <p className="muted">Rien à signaler : aucune contrainte violée, aucune journée trouée.</p>
        ) : (
          <div className="todolist">
            {items.map((it, i) => (
              <button key={i} type="button" className={`todo-item ${it.sev}`} onClick={() => setRoute(it.route)}>
                <span className="sev">{it.sev === "bad" ? "à corriger" : "à revoir"}</span>
                <span>
                  <strong>{it.title}</strong>
                  <div className="sub">{it.sub}</div>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        {controleHebdo !== undefined && (
          <div className="todo-hebdo">
            {controleHebdo === null ? (
              <p className="muted">Le contrôle hebdomadaire des doublons n'a jamais encore tourné.</p>
            ) : (
              <p className="todo-hebdo-resume">{libelleControleHebdo(controleHebdo)}</p>
            )}
            <button type="button" className="btn" onClick={() => void verifierMaintenant()} disabled={executionHebdoEnCours}>
              {executionHebdoEnCours ? "Vérification…" : "Vérifier maintenant"}
            </button>
          </div>
        )}

        <div className="todo-doublons-header">
          <h3>Doublons salle / enseignant</h3>
          {doublons !== null && doublons.length > 0 && (
            <span className="pill bad" aria-label={`${doublons.length} doublon${doublons.length > 1 ? "s" : ""}`}>
              {doublons.length}
            </span>
          )}
        </div>
        <p className="muted">
          Une salle ou un enseignant mobilisé deux fois sur le même créneau, souvent après une retouche à la main —
          H.201/H.203 et H.007/H.008 comptent comme une seule salle. Chaque ligne ouvre la Vue Promo sur le
          créneau concerné.
        </p>

        {doublons === null && !erreurDoublons && (
          <p className="muted" role="status">
            Chargement…
          </p>
        )}

        {erreurDoublons && (
          <div className="todo-doublons-actions">
            <p className="alerte" role="alert">
              {erreurDoublons}
            </p>
            <button type="button" className="btn" onClick={() => void chargerDoublons()}>
              Réessayer
            </button>
          </div>
        )}

        {doublons !== null && !erreurDoublons && doublons.length === 0 && (
          <p className="muted" role="status">
            Aucun doublon détecté.
          </p>
        )}

        {groupesDoublons.map((groupe) => (
          <div key={groupe.semaine} className="todo-doublons-semaine">
            <h4>{groupe.libelle}</h4>
            <div className="todolist">
              {groupe.doublons.map((d, i) => (
                <button
                  key={i}
                  type="button"
                  className={`todo-item ${d.type === "salle" ? "bad" : "warn"}`}
                  onClick={() => setRoute(routeVersDoublon(d))}
                >
                  <span className="sev">{d.type === "salle" ? "salle" : "enseignant"}</span>
                  <span>
                    <strong>{d.ressource}</strong>
                    {estNouveau(controleHebdo ?? null, d) && <span className="pill new">nouveau</span>}
                    <div className="sub">
                      {libelleCreneauDoublon(payload, d.semaine, d.jour, d.creneau)} — {coursEnConflit(d)}
                    </div>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
