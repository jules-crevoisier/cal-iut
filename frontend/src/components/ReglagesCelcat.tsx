/**
 * Ce qu'on règle rarement : l'écriture, le worker, l'envoi par semaine,
 * les cours présents seulement dans Celcat, et la reconstruction de la file.
 *
 * Tout cela occupait l'onglet d'ouverture, avant même le verdict. Replié ici,
 * sous ce qu'on vient vérifier chaque jour.
 *
 * Trois corrections de la critique design du 16/09/2026 :
 *
 *   - LES DEUX INTERRUPTEURS NE SE RESSEMBLENT PLUS. Deux cercles rouges
 *     identiques, dont l'un met en pause sans rien perdre et l'autre, coupé,
 *     VIDE LA FILE côté serveur. La seule mise en garde était un commentaire
 *     dans le code. Couper l'écriture demande maintenant confirmation, avec
 *     le nombre de corrections qui seront abandonnées ;
 *   - UN SEUL MOT POUR L'ÉCRITURE. « Écriture », « Live armé » et « saisie »
 *     désignaient la même chose ;
 *   - LES SEMAINES PORTENT LEUR DATE. « Semaine 1…30 » était une seconde
 *     numérotation à côté du sélecteur daté — le piège documenté du projet.
 *     La pastille n désigne l'indice n-1 ; on affiche le libellé de la grille.
 */
import { useState } from "react";

import {
  ajouterExtraCelcat,
  ignorerExtraCelcat,
  lancerNuitCelcat,
  patchCelcatSaisie,
  patchCelcatWorker,
  resynchroniserFileCelcat,
  validerSemainesCelcat,
  type CelcatEtat,
  type CelcatExtra,
  type CelcatFile,
} from "../api/client";
import { confirmAsync } from "../utils/confirmDialog";
import { dateLisible, pluriel } from "../utils/celcatStatut";
import type { SemaineChoisissable } from "./VerdictCelcat";

const SEMAINES = Array.from({ length: 30 }, (_, i) => i + 1);

type EtatPastille = "passée" | "lancée" | "enregistrée" | "retirée" | "cochée" | "planning complet" | null;

function etatPastille(
  n: number,
  brouillon: number[],
  etat: CelcatEtat,
): EtatPastille {
  const passees = etat.semaines_passees ?? [];
  const lancees = etat.semaines_lancees ?? [];
  const validees = etat.semaines_validees ?? [];
  const completes = etat.semaines_completes ?? [];
  const cochee = brouillon.includes(n);
  if (passees.includes(n)) return "passée";
  if (lancees.includes(n)) return "lancée";
  if (validees.includes(n) && cochee) return "enregistrée";
  // Enregistrée côté serveur, décochée ici : elle SORTIRA du lot au prochain
  // enregistrement. Le dire en toutes lettres — un pointillé ambre ne le
  // disait qu'à ceux qui distinguent l'ambre.
  if (validees.includes(n) && !cochee) return "retirée";
  if (cochee) return "cochée";
  if (completes.includes(n)) return "planning complet";
  return null;
}

function libelleExtra(extra: CelcatExtra): string {
  return extra.libelle || extra.course_code || extra.module_nom || extra.id;
}

export function ReglagesCelcat({
  etat,
  setEtat,
  file,
  extras,
  setExtras,
  semaines,
}: {
  etat: CelcatEtat;
  setEtat: (e: CelcatEtat) => void;
  file: CelcatFile | null;
  extras: CelcatExtra[];
  setExtras: (x: CelcatExtra[]) => void;
  semaines: SemaineChoisissable[];
}) {
  const [brouillon, setBrouillon] = useState<number[]>(etat.semaines_validees ?? []);
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const agir = async (action: () => Promise<void>) => {
    setEnCours(true);
    setErreur(null);
    setMessage(null);
    try {
      await action();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Action impossible");
    } finally {
      setEnCours(false);
    }
  };

  const basculerEcriture = async () => {
    if (etat.saisie_active) {
      const perdues = file?.en_attente ?? 0;
      const ok = await confirmAsync(
        (perdues > 0
          ? `${pluriel(perdues, "correction en attente sera abandonnée", "corrections en attente seront abandonnées")}. `
          : "") +
          "Plus rien ne partira dans Celcat jusqu’à la réactivation.\n\n" +
          "Pour simplement libérer le VPN sans rien perdre, mettez plutôt le worker en pause.",
        { title: "Couper l’écriture dans Celcat", confirmLabel: "Couper l’écriture" },
      );
      if (!ok) return;
    }
    await agir(async () => setEtat(await patchCelcatSaisie(!etat.saisie_active)));
  };

  const libelleDe = (n: number) => semaines.find((s) => s.indice === n - 1)?.libelle ?? `Semaine ${n}`;
  const verrouillee = (n: number) =>
    (etat.semaines_passees ?? []).includes(n) || (etat.semaines_lancees ?? []).includes(n);
  const basculerSemaine = (n: number) => {
    if (verrouillee(n)) return;
    setBrouillon((b) => (b.includes(n) ? b.filter((s) => s !== n) : [...b, n].sort((a, c) => a - c)));
  };

  const workerEnPause = etat.worker_actif === false;

  return (
    <details className="panel celcat-reglages" data-testid="reglages-celcat">
      <summary>
        <h2>Réglages</h2>
        <span className="celcat-sous-texte">écriture, worker, envoi par semaine, cours hors planning, file</span>
      </summary>

      {erreur ? (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      ) : null}
      {message ? (
        <p role="status" className="celcat-sous-texte">
          {message}
        </p>
      ) : null}

      <section className="celcat-reglage" aria-labelledby="reglage-ecriture">
        <h3 id="reglage-ecriture">Écriture et worker</h3>
        <div className="celcat-interrupteur">
          <button
            type="button"
            role="switch"
            className="celcat-switch"
            aria-checked={etat.saisie_active}
            aria-labelledby="interrupteur-ecriture-nom"
            aria-describedby="interrupteur-ecriture-effet"
            disabled={enCours}
            onClick={() => void basculerEcriture()}
          >
            <span className="celcat-switch-knob" />
          </button>
          <div>
            <p id="interrupteur-ecriture-nom" className="celcat-interrupteur-nom">
              Écriture dans Celcat : {etat.saisie_active ? "active" : "coupée"}
            </p>
            <p id="interrupteur-ecriture-effet" className="celcat-sous-texte">
              {etat.saisie_active
                ? "Chaque modification du planning part dans Celcat. La couper vide la file d’attente."
                : "Rien ne part dans Celcat, et la file est vide. Réactiver reprend l’envoi des modifications."}
            </p>
          </div>
        </div>
        <div className="celcat-interrupteur">
          <button
            type="button"
            role="switch"
            className="celcat-switch celcat-switch--pause"
            aria-checked={!workerEnPause}
            aria-labelledby="interrupteur-worker-nom"
            aria-describedby="interrupteur-worker-effet"
            disabled={enCours}
            onClick={() => void agir(async () => setEtat(await patchCelcatWorker(workerEnPause)))}
          >
            <span className="celcat-switch-knob" />
          </button>
          <div>
            <p id="interrupteur-worker-nom" className="celcat-interrupteur-nom">
              Worker : {workerEnPause ? "en pause" : "actif"}
            </p>
            <p id="interrupteur-worker-effet" className="celcat-sous-texte">
              {workerEnPause
                ? "Le VPN est libre pour l’équipe. La file est conservée et repartira à la reprise."
                : "Il prend le VPN partagé à chaque passage. Le mettre en pause ne perd rien."}
            </p>
          </div>
        </div>
        <p className="celcat-sous-texte">
          {etat.derniere_ecriture_celcat
            ? `Dernière écriture réelle dans Celcat : ${dateLisible(etat.derniere_ecriture_celcat)}.`
            : "Aucune écriture encore faite dans Celcat."}
        </p>
      </section>

      <section className="celcat-reglage" aria-labelledby="reglage-semaines">
        <h3 id="reglage-semaines">Envoi par semaine</h3>
        <p className="celcat-aide">
          Les semaines cochées sont balayées chaque nuit : ce qui diverge de Celcat est mis en file. « Envoyer
          maintenant » le fait tout de suite.
        </p>
        <div className="celcat-semaines" role="group" aria-label="Semaines envoyées chaque nuit">
          {SEMAINES.map((n) => {
            const statut = etatPastille(n, brouillon, etat);
            const bloquee = verrouillee(n);
            const cochee = brouillon.includes(n);
            return (
              <button
                key={n}
                type="button"
                className={`celcat-semaine${cochee ? " celcat-semaine--cochee" : ""}${bloquee ? " celcat-semaine--bloquee" : ""}${statut === "retirée" ? " celcat-semaine--retiree" : ""}`}
                aria-pressed={cochee}
                // Nom explicite : les deux `span` accolés se lisaient
                // « Semaine 1passée » au lecteur d'écran.
                aria-label={statut ? `${libelleDe(n)}, ${statut}` : libelleDe(n)}
                // `aria-disabled` plutôt que `disabled` : une semaine passée
                // reste atteignable au clavier, sans quoi on ne peut plus
                // savoir qu'elle l'est.
                aria-disabled={bloquee || enCours}
                onClick={() => !enCours && basculerSemaine(n)}
              >
                <span>{libelleDe(n)}</span>
                {statut ? <span className="pill">{statut}</span> : null}
              </button>
            );
          })}
        </div>
        <div className="celcat-actions">
          <button
            type="button"
            className="btn btn--accent"
            disabled={enCours}
            onClick={() =>
              void agir(async () => {
                setEtat(await validerSemainesCelcat(brouillon));
                setMessage("Sélection enregistrée pour le balayage de nuit.");
              })
            }
          >
            Enregistrer la sélection
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={enCours || !etat.saisie_active}
            aria-describedby={!etat.saisie_active ? "envoyer-impossible" : undefined}
            onClick={() =>
              void agir(async () => {
                // Enregistre d'abord ce qui est coché : l'envoi ne connaît que le
                // lot enregistré côté serveur (bug utilisateur du 05/09/2026).
                await validerSemainesCelcat(brouillon);
                setEtat(await lancerNuitCelcat());
                setMessage("Semaines envoyées : les écarts sont en file.");
              })
            }
          >
            Envoyer maintenant
          </button>
        </div>
        {!etat.saisie_active ? (
          <p id="envoyer-impossible" className="celcat-texte-attention">
            « Envoyer maintenant » attend que l’écriture dans Celcat soit active.
          </p>
        ) : null}
      </section>

      <section className="celcat-reglage" aria-labelledby="reglage-extras">
        <h3 id="reglage-extras">Cours présents seulement dans Celcat</h3>
        <p className="celcat-aide">
          Saisis directement dans Celcat, sans équivalent dans le planning. Les ajouter les importe dans cal-iut ;
          les ignorer les écarte de cette liste.
        </p>
        {extras.length === 0 ? (
          <p className="celcat-sous-texte">Aucun cours à examiner.</p>
        ) : (
          <ul className="celcat-extras">
            {extras.map((x) => {
              const label = libelleExtra(x);
              return (
                <li key={x.id} className="celcat-extra">
                  <strong>{label}</strong>
                  <div className="celcat-extra-actions">
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={enCours}
                      aria-label={`Ajouter ${label}`}
                      onClick={() =>
                        void agir(async () => {
                          await ajouterExtraCelcat(x.id);
                          setExtras(extras.filter((e) => e.id !== x.id));
                        })
                      }
                    >
                      Ajouter
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={enCours}
                      aria-label={`Ignorer ${label}`}
                      onClick={() =>
                        void agir(async () => {
                          await ignorerExtraCelcat(x.id);
                          setExtras(extras.filter((e) => e.id !== x.id));
                        })
                      }
                    >
                      Ignorer
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="celcat-reglage" aria-labelledby="reglage-file">
        <h3 id="reglage-file">Reconstruire la file</h3>
        <p className="celcat-aide">
          Jette ce qui attend sur les semaines enregistrées et ne remet en file que ce qui diverge réellement de
          Celcat. Utile après un gros changement de planning.
        </p>
        <div className="celcat-actions">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={enCours}
            data-testid="resynchroniser-file-sans"
            onClick={() =>
              void agir(async () => setMessage((await resynchroniserFileCelcat(undefined, { supprimer: false })).message))
            }
          >
            Reconstruire sans supprimer
          </button>
          <button
            type="button"
            className="btn btn--danger"
            disabled={enCours}
            data-testid="resynchroniser-file-avec"
            onClick={() =>
              void (async () => {
                const ok = await confirmAsync(
                  "Les évènements que Celcat a en trop sur les semaines enregistrées seront SUPPRIMÉS définitivement.\n\n" +
                    "À n’utiliser que si personne ne travaille dans Celcat en ce moment.",
                  { title: "Reconstruire avec les suppressions", confirmLabel: "Reconstruire et supprimer" },
                );
                if (!ok) return;
                await agir(async () =>
                  setMessage((await resynchroniserFileCelcat(undefined, { supprimer: true })).message),
                );
              })()
            }
          >
            Reconstruire avec suppressions
          </button>
        </div>
      </section>
    </details>
  );
}
