/**
 * Sauvegardes JSON datées — item B du contrat verrouillé (22/09/2026).
 *
 * Todo : « Avoir un fichier JSON backup des semaines et séances placées à
 * une date précise ». Réservée aux admins : le backend refuse déjà tout le
 * reste (`Depends(require_role("admin"))`, cf. `api/main.py`), cette vue
 * n'est simplement jamais proposée dans la nav à un autre rôle (App.tsx/
 * SideNav) — même patron que `AdminUsersView`.
 *
 * Une sauvegarde est prise automatiquement au premier écrit du jour (jamais
 * visible ici comme une action) ; le bouton « Faire une sauvegarde
 * maintenant » est le geste EXPLICITE, distinct, qui écrase celle du jour.
 * Aucune restauration : hors périmètre du contrat verrouillé.
 */

import { useCallback, useEffect, useState } from "react";

import { creerSauvegardeMaintenant, listSauvegardes, sauvegardeUrl, type SauvegardeMeta } from "../api/client";
import "./SauvegardesView.css";

const DATE_FMT = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

function formatDate(jour: string): string {
  const d = new Date(`${jour}T00:00:00`);
  if (Number.isNaN(d.getTime())) return jour;
  return DATE_FMT.format(d);
}

function formatTaille(octets: number): string {
  if (octets < 1024) return `${octets} o`;
  const ko = octets / 1024;
  if (ko < 1024) return `${ko.toFixed(1)} Ko`;
  return `${(ko / 1024).toFixed(1)} Mo`;
}

export function SauvegardesView() {
  const [sauvegardes, setSauvegardes] = useState<SauvegardeMeta[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
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
    try {
      await creerSauvegardeMaintenant();
      await recharger();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Échec de la sauvegarde");
    } finally {
      setEnCours(false);
    }
  };

  if (erreur && !sauvegardes) {
    return (
      <section className="view sauvegardes-view">
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
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
        <div className="panel">
          <p className="muted">Chargement…</p>
        </div>
      </section>
    );
  }

  return (
    <section className="view sauvegardes-view">
      <div className="panel sauvegardes-actions">
        <div>
          <h3>Sauvegardes</h3>
          <p className="muted">
            Un fichier JSON par jour — semaines, séances placées, séances ajoutées et retouches. Conservées 90 jours.
          </p>
        </div>
        <button type="button" className="btn btn--primary" disabled={enCours} onClick={() => void sauvegarderMaintenant()}>
          {enCours ? "Sauvegarde en cours…" : "Faire une sauvegarde maintenant"}
        </button>
      </div>

      {erreur && (
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      )}

      <div className="panel">
        {sauvegardes.length === 0 ? (
          <p className="muted">Aucune sauvegarde pour l'instant — la première sera prise à la prochaine modification du planning.</p>
        ) : (
          <ul className="sauvegardes-list">
            {sauvegardes.map((s) => (
              <li key={s.date} className="sauvegardes-row">
                <div className="sauvegardes-identite">
                  <strong>{formatDate(s.date)}</strong>
                  <span className="muted">
                    {s.nb_placements} séance{s.nb_placements > 1 ? "s" : ""} placée{s.nb_placements > 1 ? "s" : ""} ·{" "}
                    {formatTaille(s.taille_octets)}
                  </span>
                </div>
                <a
                  className="btn btn--ghost btn--sm"
                  href={sauvegardeUrl(s.date)}
                  download={`cal-iut-${s.date}.json`}
                >
                  Télécharger
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
