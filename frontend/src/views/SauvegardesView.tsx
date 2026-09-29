/**
 * Sauvegardes JSON datées — item B du contrat verrouillé (22/09/2026).
 *
 * Todo : « Avoir un fichier JSON backup des semaines et séances placées à
 * une date précise ». Réservée aux admins : le backend refuse déjà tout le
 * reste (`Depends(require_role("admin"))`, cf. `api/main.py`), cette vue
 * n'est simplement jamais proposée dans la nav à un autre rôle — même
 * patron que `AdminUsersView`.
 *
 * Une sauvegarde est prise automatiquement au premier écrit du jour ; le
 * bouton « Faire une sauvegarde maintenant » est le geste EXPLICITE, qui
 * remplace celle du jour. Aucune restauration : hors périmètre du contrat.
 *
 * Refonte du 29/09/2026 : un tableau daté, avec l'écart de séances placées
 * d'une sauvegarde à la précédente — une chute brutale se voit sans ouvrir
 * les fichiers, et c'est précisément ce qu'on vient chercher ici.
 */

import { useCallback, useEffect, useState } from "react";

import { creerSauvegardeMaintenant, listSauvegardes, sauvegardeUrl, type SauvegardeMeta } from "../api/client";
import "./SauvegardesView.css";

const DATE_FMT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "long", year: "numeric" });
const NOMBRE = new Intl.NumberFormat("fr-FR");
const DECIMAL = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDate(jour: string): string {
  const d = new Date(`${jour}T00:00:00`);
  if (Number.isNaN(d.getTime())) return jour;
  return DATE_FMT.format(d);
}

function formatTaille(octets: number): string {
  if (octets < 1024) return `${octets} o`;
  const ko = octets / 1024;
  if (ko < 1024) return `${DECIMAL.format(ko)} Ko`;
  return `${DECIMAL.format(ko / 1024)} Mo`;
}

/** Une baisse de plus de 5 % d'un jour à l'autre mérite un coup d'œil. */
function ecart(actuel: number, precedent: number | undefined): { texte: string; classe: string } | null {
  if (precedent === undefined) return null;
  const d = actuel - precedent;
  if (d === 0) return { texte: "=", classe: "muted" };
  const forte = d < 0 && precedent > 0 && -d / precedent > 0.05;
  return {
    texte: `${d > 0 ? "+" : "−"}${NOMBRE.format(Math.abs(d))}`,
    classe: forte ? "sauvegardes-baisse" : "muted",
  };
}

export function SauvegardesView() {
  const [sauvegardes, setSauvegardes] = useState<SauvegardeMeta[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  const recharger = useCallback(async () => {
    try {
      setSauvegardes(await listSauvegardes());
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur de chargement");
    }
  }, []);

  useEffect(() => {
    void recharger();
  }, [recharger]);

  const sauvegarderMaintenant = async () => {
    setEnCours(true);
    setErreur(null);
    setMessage(null);
    try {
      await creerSauvegardeMaintenant();
      await recharger();
      setMessage("Sauvegarde du jour enregistrée.");
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Échec de la sauvegarde");
    } finally {
      setEnCours(false);
    }
  };

  if (erreur && !sauvegardes) {
    return (
      <section className="view sauvegardes-view">
        <p className="alerte" role="alert">
          {erreur}
        </p>
        <div>
          <button type="button" className="btn" onClick={() => void recharger()}>
            Réessayer
          </button>
        </div>
      </section>
    );
  }

  if (!sauvegardes) {
    return (
      <section className="view sauvegardes-view">
        <p className="muted">Chargement…</p>
      </section>
    );
  }

  const aujourdhui = isoLocal(new Date());
  const tries = [...sauvegardes].sort((a, b) => b.date.localeCompare(a.date));
  const derniere = tries[0];

  return (
    <section className="view sauvegardes-view">
      <div className="panel sauvegardes-actions">
        <div>
          <p className="sauvegardes-derniere">
            {derniere ? (
              <>
                Dernière sauvegarde : <strong>{derniere.date === aujourdhui ? "aujourd’hui" : formatDate(derniere.date)}</strong>
                {" — "}
                {NOMBRE.format(derniere.nb_placements)} séance{derniere.nb_placements > 1 ? "s" : ""} placée
                {derniere.nb_placements > 1 ? "s" : ""}
              </>
            ) : (
              "Aucune sauvegarde pour l’instant."
            )}
          </p>
          <p className="muted">
            Prise automatiquement au premier changement du planning de la journée, conservée 90 jours. Un fichier JSON
            par jour : semaines, séances placées, séances ajoutées et retouches.
          </p>
        </div>
        <button type="button" className="btn btn--primary" disabled={enCours} onClick={() => void sauvegarderMaintenant()}>
          {enCours ? "Sauvegarde en cours…" : "Faire une sauvegarde maintenant"}
        </button>
      </div>

      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <div className="sauvegardes-message" role="status" aria-live="polite">
        {message}
      </div>

      <section className="panel" aria-labelledby="sauvegardes-titre">
        <h2 id="sauvegardes-titre">Historique ({sauvegardes.length})</h2>
        {sauvegardes.length === 0 ? (
          <p className="muted">Aucune sauvegarde pour l'instant — la première sera prise à la prochaine modification du planning.</p>
        ) : (
          <div className="ref-table-wrap">
            <table className="ref sauvegardes-table">
              <thead>
                <tr>
                  <th scope="col">Jour</th>
                  <th scope="col" className="num">
                    Séances placées
                  </th>
                  <th scope="col" className="num">
                    Écart
                  </th>
                  <th scope="col" className="num">
                    Taille
                  </th>
                  <th scope="col">
                    <span className="sr-only">Fichier</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {tries.map((s, i) => {
                  const e = ecart(s.nb_placements, tries[i + 1]?.nb_placements);
                  return (
                    <tr key={s.date}>
                      <th scope="row">
                        <span className="sauvegardes-jour">{formatDate(s.date)}</span>
                        {s.date === aujourdhui ? <span className="pill">aujourd’hui</span> : null}
                      </th>
                      <td className="num">{NOMBRE.format(s.nb_placements)}</td>
                      <td className="num">
                        {e ? (
                          <span className={e.classe} title="Par rapport à la sauvegarde précédente">
                            {e.texte}
                          </span>
                        ) : null}
                      </td>
                      <td className="num">{formatTaille(s.taille_octets)}</td>
                      <td className="sauvegardes-col-fichier">
                        <a
                          className="btn btn--ghost btn--sm"
                          href={sauvegardeUrl(s.date)}
                          download={`cal-iut-${s.date}.json`}
                        >
                          Télécharger
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
