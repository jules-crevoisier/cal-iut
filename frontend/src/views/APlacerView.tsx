/**
 * « À placer » — l'écran qui rattrape ce que le solveur n'a pas su placer.
 *
 * Pourquoi il existe (26/08/2026). Le solveur place ~96,5 % des séances. Les
 * quelques dizaines restantes butent sur des combinaisons PROUVÉES infaisables
 * — pas sur un manque de temps de calcul. Jusqu'ici elles disparaissaient sans
 * bruit : le planning avait l'air complet alors qu'il manquait des heures.
 *
 * Le parti pris de l'écran : on ne demande jamais à la personne de deviner un
 * créneau. Le serveur propose uniquement des créneaux où AUCUNE règle n'est
 * violée (indisponibilités enseignantes, jeudi PAC, jours SAE, événements du
 * planning officiel, ordre pédagogique, conflits de groupe et de salle), et le
 * placement repasse par les mêmes contrôles côté serveur. Un clic suffit.
 */

import { useCallback, useEffect, useState } from "react";

import {
  completerPlacements,
  fetchCreneauxLibres,
  fetchSeancesManquantes,
  placerSeance,
  type Completion,
  type CreneauLibre,
  type SeanceAPlacer,
  type SeancesAPlacer,
} from "../api/client";

const JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"];
const HORAIRES = ["08h00", "09h30", "11h00", "14h00", "15h30", "17h00"];

function dateLisible(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

interface APlacerViewProps {
  /** Rechargement du planning après un placement réussi. */
  onPlacement: () => void;
}

export function APlacerView({ onPlacement }: APlacerViewProps) {
  const [inventaire, setInventaire] = useState<SeancesAPlacer | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);
  // Annoncé aux lecteurs d'écran : sans ça, la réussite d'un placement
  // n'existe que visuellement — la carte disparaît de la liste, et rien ne le
  // dit à qui ne voit pas l'écran.
  const [annonce, setAnnonce] = useState("");
  // Incrémenté à chaque placement réussi. Les créneaux proposés sont calculés
  // CONTRE le planning du moment : dès qu'une séance est posée, ceux que les
  // autres cartes ont déjà en mémoire peuvent être devenus faux — vérifié sur
  // le run réel, plusieurs séances se voyaient offrir exactement le même
  // créneau. Sans cette invalidation, le deuxième clic serait refusé pour
  // conflit sans que la personne comprenne pourquoi.
  const [version, setVersion] = useState(0);
  const [completion, setCompletion] = useState<Completion | null>(null);
  const [completionEnCours, setCompletionEnCours] = useState(false);

  const recharger = useCallback(() => {
    setChargement(true);
    fetchSeancesManquantes()
      .then((data) => {
        setInventaire(data);
        setErreur(null);
      })
      .catch((e: Error) => setErreur(e.message))
      .finally(() => setChargement(false));
  }, []);

  useEffect(recharger, [recharger]);

  if (chargement && !inventaire) {
    return (
      <section className="view">
        <div className="panel">
          <p className="muted">Recherche des séances non placées…</p>
        </div>
      </section>
    );
  }

  if (erreur) {
    return (
      <section className="view">
        <div className="panel">
          <h3>À placer</h3>
          <p className="alerte">{erreur}</p>
          <button type="button" className="btn" onClick={recharger}>
            Réessayer
          </button>
        </div>
      </section>
    );
  }

  const manquantes = inventaire?.manquantes ?? [];

  return (
    <section className="view aplacer">
      <p role="status" aria-live="polite" className="sr-only">
        {annonce}
      </p>
      <div className="panel">
        <h3>Séances à placer à la main</h3>
        <p className="muted">{inventaire?.resume}</p>

        {manquantes.length > 0 && (
          <>
            <div className="aplacer-jauge" aria-hidden="true">
              <div
                className="aplacer-jauge-remplie"
                style={{
                  width: `${Math.round(
                    ((inventaire?.total_placees ?? 0) / Math.max(1, inventaire?.total_a_placer ?? 1)) * 100,
                  )}%`,
                }}
              />
            </div>
            <p className="muted small">
              {inventaire?.total_placees} séances placées sur {inventaire?.total_a_placer} —{" "}
              {Math.round(((inventaire?.total_placees ?? 0) / Math.max(1, inventaire?.total_a_placer ?? 1)) * 100)} %
            </p>

            <div className="aplacer-auto">
              <button
                type="button"
                className="btn btn--primary"
                disabled={completionEnCours}
                onClick={() => {
                  setCompletionEnCours(true);
                  setAnnonce("Placement automatique en cours…");
                  completerPlacements()
                    .then((r) => {
                      setCompletion(r);
                      setAnnonce(r.resume);
                      setVersion((v) => v + 1);
                      recharger();
                      onPlacement();
                    })
                    .catch((e: Error) => setErreur(e.message))
                    .finally(() => setCompletionEnCours(false));
                }}
              >
                {completionEnCours ? "Placement en cours…" : "Tout placer automatiquement"}
              </button>
              <p className="muted small">
                L'outil pose lui-même toutes les séances pour lesquelles il trouve un créneau valable, les plus
                difficiles d'abord. Il ne déplace jamais un cours déjà placé, et vous dit ce qu'il n'a pas su faire.
                Cela prend quelques minutes.
              </p>
            </div>
          </>
        )}

        {completion && (
          <div className="aplacer-rapport">
            <p>
              <strong>{completion.placees.length}</strong> séance(s) placée(s) automatiquement.
              {completion.refusees.length > 0 && (
                <> <strong>{completion.refusees.length}</strong> restent à traiter ci-dessous.</>
              )}
            </p>
            {completion.refusees.length > 0 && (
              <details>
                <summary>Pourquoi celles-ci n'ont pas pu être placées</summary>
                <ul>
                  {[...new Set(completion.refusees.map((r) => r.raison))].map((raison) => (
                    <li key={raison}>
                      {raison}{" "}
                      <span className="muted">
                        ({completion.refusees.filter((r) => r.raison === raison).length} séance(s))
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </div>

      {manquantes.length === 0 ? (
        <div className="panel">
          <p className="muted">Rien à faire ici : toutes les séances sont au planning.</p>
        </div>
      ) : (
        <div className="aplacer-liste">
          {manquantes.map((s) => (
            <CarteSeance
              key={s.session_id}
              seance={s}
              version={version}
              onPlace={() => {
                setAnnonce(`${s.course_code} placée. Il reste ${manquantes.length - 1} séance(s) à placer.`);
                setVersion((v) => v + 1);
                recharger();
                onPlacement();
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function CarteSeance({
  seance,
  version,
  onPlace,
}: {
  seance: SeanceAPlacer;
  version: number;
  onPlace: () => void;
}) {
  const [ouverte, setOuverte] = useState(false);
  const [creneaux, setCreneaux] = useState<CreneauLibre[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [chargement, setChargement] = useState(false);
  const [enCours, setEnCours] = useState<string | null>(null);
  const [echec, setEchec] = useState<string | null>(null);

  const charger = useCallback(() => {
    setChargement(true);
    fetchCreneauxLibres(seance.session_id)
      .then((r) => {
        setCreneaux(r.creneaux);
        setNote(r.note);
        setEchec(null);
      })
      .catch((e: Error) => setEchec(e.message))
      .finally(() => setChargement(false));
  }, [seance.session_id]);

  // Le planning a changé pendant que cette carte était ouverte : ses créneaux
  // en mémoire ne valent plus rien, on les redemande.
  useEffect(() => {
    if (ouverte && version > 0) charger();
    // `charger` et `ouverte` volontairement hors dépendances : seul un
    // changement de `version` doit relancer l'appel, pas la simple ouverture
    // (traitée dans `ouvrir`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const ouvrir = () => {
    const suivant = !ouverte;
    setOuverte(suivant);
    if (suivant && creneaux === null && !chargement) charger();
  };

  const placer = (c: CreneauLibre) => {
    setEnCours(`${c.week}-${c.day}-${c.slot}`);
    setEchec(null);
    placerSeance(seance.session_id, { week: c.week, day: c.day, slot: c.slot })
      .then(onPlace)
      .catch((e: Error) => {
        // Un refus vient presque toujours d'un créneau pris entre-temps :
        // on redemande la liste plutôt que de laisser un choix périmé à
        // l'écran.
        setEchec(`${e.message} — la liste des créneaux vient d'être actualisée.`);
        charger();
      })
      .finally(() => setEnCours(null));
  };

  const titre = `${seance.course_code} — ${seance.course_name}`;
  const panneauId = `creneaux-${seance.session_id}`;

  return (
    <article className="aplacer-carte" aria-label={titre}>
      <button type="button" className="aplacer-entete" onClick={ouvrir} aria-expanded={ouverte} aria-controls={panneauId}>
        <span className="aplacer-titre">
          <strong>{titre}</strong>
          <span className="sub">
            {seance.session_type} · {seance.duree_libelle} · {seance.groupes_libelles.join(", ")} ·{" "}
            {seance.enseignants_libelles.join(", ")}
          </span>
        </span>
        <span className="aplacer-chevron" aria-hidden="true">
          {ouverte ? "▾" : "▸"}
        </span>
      </button>

      {ouverte && (
        <div className="aplacer-corps" id={panneauId}>
          <p className="muted small">{seance.raison}</p>

          {chargement && <p className="muted">Recherche des créneaux possibles…</p>}
          {note && <p className="alerte">{note}</p>}
          {echec && <p className="alerte">{echec}</p>}

          {creneaux && creneaux.length > 0 && (
            <>
              <p className="muted small">
                Chacun de ces créneaux a été vérifié : aucune indisponibilité enseignante, aucun conflit de groupe ou
                de salle, aucune règle de l'établissement enfreinte.
              </p>
              <ul className="aplacer-creneaux">
                {creneaux.map((c) => {
                  const cle = `${c.week}-${c.day}-${c.slot}`;
                  return (
                    <li key={cle}>
                      <button
                        type="button"
                        className="aplacer-creneau"
                        onClick={() => placer(c)}
                        disabled={enCours !== null}
                      >
                        <span className="aplacer-quand">
                          <strong>
                            {dateLisible(c.date) || `${JOURS[c.day]} semaine ${c.week + 1}`}
                          </strong>
                          <span className="sub">
                            {HORAIRES[c.slot]} · {c.salle_label ?? "salle à définir"}
                          </span>
                        </span>
                        <span className="aplacer-action">{enCours === cle ? "Placement…" : "Placer ici"}</span>
                      </button>
                      {c.remarques.length > 0 && <p className="muted small">{c.remarques.join(" · ")}</p>}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      )}
    </article>
  );
}
