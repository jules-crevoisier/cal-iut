/**
 * Référence → Réglages → semaines des alternants à l'IUT (17/11/2026).
 * En dehors de ces périodes, les alternants sont en entreprise : le calcul
 * ne place aucun de leurs cours.
 */
import { useState } from "react";

import {
  ajouterPresenceAlternants,
  retirerPresenceAlternants,
  type ReglagesReponse,
} from "../api/client";

const ANNEES = ["BUT2", "BUT3"];

function jourLisible(iso: string): string {
  const [a, m, j] = iso.split("-").map(Number);
  return new Date(a, m - 1, j).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

function aujourdhui(): string {
  const d = new Date();
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${deux(d.getMonth() + 1)}-${deux(d.getDate())}`;
}

export function PresencesAlternants({
  donnees,
  onChange,
}: {
  donnees: ReglagesReponse;
  onChange: (r: ReglagesReponse, message: string) => void;
}) {
  const periodes = donnees.presences_alternants;
  const [annee, setAnnee] = useState("BUT2");
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [passees, setPassees] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  if (!periodes) return null;

  const jour = aujourdhui();
  const pret = debut !== "" && fin !== "" && debut <= fin;
  const agir = async (action: () => Promise<ReglagesReponse>, message: string) => {
    setEnvoi(true);
    setErreur(null);
    try {
      onChange(await action(), message);
      return true;
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
      return false;
    } finally {
      setEnvoi(false);
    }
  };
  const nbPassees = periodes.filter((p) => p.fin < jour).length;

  return (
    <section className="panel reglages-famille" aria-labelledby="reglages-presences">
      <header>
        <h2 id="reglages-presences">Semaines des alternants à l’IUT</h2>
        <p className="muted">
          Les périodes où les alternants de 2e et de 3e année sont à l’IUT. En dehors, ils sont en entreprise et
          aucun de leurs cours n’est placé. À ressaisir chaque année à partir du calendrier d’alternance.
        </p>
      </header>
      {ANNEES.map((a) => {
        const liste = periodes.filter((p) => p.annee === a && (passees || p.fin >= jour));
        return (
          <details key={a} className="reglages-parcours" open={a === annee}>
            <summary>
              Alternants de {a} : {liste.length} période{liste.length > 1 ? "s" : ""} à venir
            </summary>
            {liste.length === 0 ? (
              <p className="muted">Aucune période à venir.</p>
            ) : (
              <ul className="reglages-regles-salles">
                {liste.map((p) => (
                  <li key={`${p.origine}-${p.cle}`} className={p.fin < jour ? "reglages-passee" : undefined}>
                    <span>
                      Du {jourLisible(p.debut)} au {jourLisible(p.fin)}
                      <span className="muted">
                        {" "}
                        · {p.jours} jour{p.jours > 1 ? "s" : ""}
                        {p.origine === "ajoutee" ? " · saisie ici" : ""}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={envoi}
                      aria-label={`Retirer la période ${a} du ${jourLisible(p.debut)}`}
                      onClick={() => {
                        if (!window.confirm(`Retirer la période du ${jourLisible(p.debut)} au ${jourLisible(p.fin)} ?`))
                          return;
                        void agir(() => retirerPresenceAlternants(p), "Période retirée.");
                      }}
                    >
                      Retirer
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </details>
        );
      })}
      {nbPassees > 0 && (
        <label className="reglages-passees">
          <input type="checkbox" checked={passees} onChange={(e) => setPassees(e.target.checked)} /> Afficher aussi les{" "}
          {nbPassees} déjà passée{nbPassees > 1 ? "s" : ""}
        </label>
      )}
      <form
        className="reglages-ajout"
        onSubmit={(e) => {
          e.preventDefault();
          if (!pret) return;
          void agir(
            () => ajouterPresenceAlternants({ annee, debut, fin }),
            "Période enregistrée. Le planning en service en tient compte dès maintenant.",
          ).then((ok) => {
            if (ok) {
              setDebut("");
              setFin("");
            }
          });
        }}
      >
        <h3>Ajouter une période à l’IUT</h3>
        <div className="reglages-champs">
          <label>
            Alternants de
            <select value={annee} onChange={(e) => setAnnee(e.target.value)}>
              {ANNEES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label>
            Premier jour à l’IUT
            <input type="date" value={debut} onChange={(e) => setDebut(e.target.value)} />
          </label>
          <label>
            Dernier jour à l’IUT
            <input type="date" value={fin} min={debut || undefined} onChange={(e) => setFin(e.target.value)} />
          </label>
        </div>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        <div className="reglages-actions">
          <button type="submit" className="primary" disabled={envoi || !pret}>
            Ajouter la période
          </button>
        </div>
      </form>
    </section>
  );
}
