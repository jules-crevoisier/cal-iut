/**
 * Ce qu'on règle rarement : l'écriture, le robot d'envoi, l'envoi par
 * semaine, les cours présents seulement dans Celcat, et la reconstruction de
 * la file. Replié sous ce qu'on vient vérifier chaque jour.
 *
 * Corrections de la critique design du 16/09/2026, reprises à la refonte du
 * 29/09/2026 :
 *
 *   - LES DEUX INTERRUPTEURS NE SE RESSEMBLENT PAS. L'un met en pause sans
 *     rien perdre, l'autre, coupé, VIDE LA FILE côté serveur. Chacun a sa
 *     carte et sa conséquence écrite ; couper l'écriture demande
 *     confirmation, avec le nombre de corrections qui seront abandonnées ;
 *   - UN SEUL MOT POUR L'ÉCRITURE (« Écriture », « Live armé » et « saisie »
 *     désignaient la même chose) ; « worker » devient « robot d'envoi » ;
 *   - LES SEMAINES PORTENT LEUR DATE, et une légende dit ce que veut dire
 *     chaque état. La pastille n désigne l'indice n-1 ; on affiche le
 *     libellé de la grille.
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

/** Repli quand le calendrier n'a pas pu être lu : trente pastilles numérotées. */
const SEMAINES_PAR_DEFAUT = Array.from({ length: 30 }, (_, i) => i + 1);

type EtatPastille = "passée" | "lancée" | "enregistrée" | "retirée" | "cochée" | "planning complet" | null;

/** Ce que veut dire chaque mot, en légende au-dessus des semaines : six
 * états, c'était six couleurs à deviner. */
const LEGENDE: Array<{ mot: Exclude<EtatPastille, null>; sens: string; ton: string }> = [
  { mot: "enregistrée", sens: "balayée chaque nuit", ton: "good" },
  { mot: "cochée", sens: "le sera une fois enregistrée", ton: "" },
  { mot: "retirée", sens: "sortira du balayage une fois enregistrée", ton: "warn" },
  { mot: "lancée", sens: "déjà envoyée", ton: "" },
  { mot: "passée", sens: "verrouillée", ton: "" },
  { mot: "planning complet", sens: "toutes les séances sont placées", ton: "" },
];
const TON_PASTILLE: Record<string, string> = Object.fromEntries(LEGENDE.map((l) => [l.mot, l.ton]));

function etatPastille(n: number, brouillon: number[], etat: CelcatEtat): EtatPastille {
  const passees = etat.semaines_passees ?? [];
  const lancees = etat.semaines_lancees ?? [];
  const validees = etat.semaines_validees ?? [];
  const completes = etat.semaines_completes ?? [];
  const cochee = brouillon.includes(n);
  if (passees.includes(n)) return "passée";
  if (lancees.includes(n)) return "lancée";
  if (validees.includes(n) && cochee) return "enregistrée";
  // Enregistrée côté serveur, décochée ici : elle SORTIRA du balayage au
  // prochain enregistrement. Le dire en toutes lettres.
  if (validees.includes(n) && !cochee) return "retirée";
  if (cochee) return "cochée";
  if (completes.includes(n)) return "planning complet";
  return null;
}

/** « Semaine 6 (28 sept.–2 oct. 2026) » → « S6 » et « 28 sept.–2 oct. » :
 * trente libellés complets faisaient une grille illisible. */
function decouper(libelle: string): { numero: string; dates: string } {
  const m = /^Semaine\s+(\d+)\s*(?:\((.*)\))?\s*$/.exec(libelle);
  if (!m) return { numero: libelle, dates: "" };
  return { numero: `S${m[1]}`, dates: (m[2] ?? "").replace(/\s+\d{4}$/, "") };
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
  const [brouillon, setBrouillon] = useState<number[]>([...(etat.semaines_validees ?? [])].sort((a, b) => a - b));
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

  const perdues = file?.en_attente ?? 0;

  const basculerEcriture = async () => {
    if (etat.saisie_active) {
      const ok = await confirmAsync(
        (perdues > 0
          ? `${pluriel(perdues, "correction en attente sera abandonnée", "corrections en attente seront abandonnées")}. `
          : "") +
          "Plus rien ne partira dans Celcat jusqu’à la réactivation.\n\n" +
          "Pour simplement libérer le VPN sans rien perdre, mettez plutôt le robot d’envoi en pause.",
        { title: "Couper l’écriture dans Celcat", confirmLabel: "Couper l’écriture", variant: "danger" },
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
  // Les pastilles suivent le calendrier réel : trente pastilles fixes
  // affichaient « Semaine 26…30 » sans date au-delà de la dernière semaine
  // du planning. Une semaine enregistrée hors calendrier reste visible, pour
  // pouvoir la retirer.
  const pastilles = semaines.length
    ? [...new Set([...semaines.map((s) => s.indice + 1), ...(etat.semaines_validees ?? [])])].sort((a, b) => a - b)
    : SEMAINES_PAR_DEFAUT;
  const enregistrees = [...(etat.semaines_validees ?? [])].sort((a, b) => a - b);
  const modifie = enregistrees.join(",") !== brouillon.join(",");

  const workerEnPause = etat.worker_actif === false;

  return (
    <details className="panel celcat-reglages celcat-repliable" data-testid="reglages-celcat">
      <summary>
        <h2>Réglages</h2>
        <span className="celcat-sous-texte">écriture, robot d’envoi, balayage de nuit, cours hors planning, file</span>
      </summary>

      {erreur ? (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      ) : null}
      {message ? (
        <p role="status" className="celcat-message-ok">
          {message}
        </p>
      ) : null}

      <section className="celcat-reglage" aria-labelledby="reglage-ecriture">
        <h3 id="reglage-ecriture">Écriture et robot d’envoi</h3>
        <div className="celcat-interrupteurs">
          <div className="celcat-interrupteur">
            <div className="celcat-interrupteur-tete">
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
              <p id="interrupteur-ecriture-nom" className="celcat-interrupteur-nom">
                Écriture dans Celcat : {etat.saisie_active ? "active" : "coupée"}
              </p>
            </div>
            <p id="interrupteur-ecriture-effet" className="celcat-sous-texte">
              {etat.saisie_active
                ? "Chaque modification du planning part dans Celcat."
                : "Rien ne part dans Celcat, et la file est vide. Réactiver reprend l’envoi des modifications."}
            </p>
            {etat.saisie_active ? (
              <p className="celcat-texte-attention">
                La couper vide la file d’attente
                {perdues > 0 ? ` (${pluriel(perdues, "correction abandonnée", "corrections abandonnées")})` : ""}.
              </p>
            ) : null}
          </div>

          <div className="celcat-interrupteur">
            <div className="celcat-interrupteur-tete">
              <button
                type="button"
                role="switch"
                className="celcat-switch"
                aria-checked={!workerEnPause}
                aria-labelledby="interrupteur-worker-nom"
                aria-describedby="interrupteur-worker-effet"
                disabled={enCours}
                onClick={() => void agir(async () => setEtat(await patchCelcatWorker(workerEnPause)))}
              >
                <span className="celcat-switch-knob" />
              </button>
              <p id="interrupteur-worker-nom" className="celcat-interrupteur-nom">
                Robot d’envoi : {workerEnPause ? "en pause" : "actif"}
              </p>
            </div>
            <p id="interrupteur-worker-effet" className="celcat-sous-texte">
              {workerEnPause
                ? "Le VPN est libre pour l’équipe. La file est conservée et repartira à la reprise."
                : "Il prend le VPN partagé à chaque passage. Le mettre en pause libère le VPN sans rien perdre."}
            </p>
          </div>
        </div>
        <p className="celcat-sous-texte">
          Règles d’envoi (WR100BU, PTUT) : <strong>{etat.regles_envoi_actives ? "actives" : "inactives"}</strong>.{" "}
          {etat.regles_envoi_actives
            ? "Ces séances partent avec la catégorie de leur règle."
            : `Ces séances ne partent pas. Pour les activer : ${etat.variable_regles_envoi ?? "CAL_IUT_REGLES_ENVOI"}=on sur les services backend et celcat-nuit, puis redéployer.`}
        </p>
        <p className="celcat-sous-texte">
          {etat.derniere_ecriture_celcat
            ? `Dernière écriture réelle dans Celcat : ${dateLisible(etat.derniere_ecriture_celcat)}.`
            : "Aucune écriture encore faite dans Celcat."}
        </p>
      </section>

      <section className="celcat-reglage" aria-labelledby="reglage-semaines">
        <h3 id="reglage-semaines">Envoi par semaine — balayage de nuit</h3>
        <p className="celcat-aide">
          Chaque nuit, les semaines enregistrées sont comparées à Celcat et ce qui diverge est mis en file.
          « Envoyer maintenant » fait ce balayage tout de suite.
        </p>
        <dl className="celcat-legende" aria-label="Légende des semaines">
          {LEGENDE.map((l) => (
            <div key={l.mot}>
              <dt>
                <span className={`pill dot ${l.ton}`}>{l.mot}</span>
              </dt>
              <dd>{l.sens}</dd>
            </div>
          ))}
        </dl>
        <div className="celcat-semaines" role="group" aria-label="Semaines envoyées chaque nuit">
          {pastilles.map((n) => {
            const statut = etatPastille(n, brouillon, etat);
            const bloquee = verrouillee(n);
            const cochee = brouillon.includes(n);
            const { numero, dates } = decouper(libelleDe(n));
            return (
              <button
                key={n}
                type="button"
                className={`celcat-semaine${cochee ? " celcat-semaine--cochee" : ""}${bloquee ? " celcat-semaine--bloquee" : ""}${statut === "retirée" ? " celcat-semaine--retiree" : ""}`}
                aria-pressed={cochee}
                // Nom explicite : les `span` accolés se lisaient « Semaine 1passée ».
                aria-label={statut ? `${libelleDe(n)}, ${statut}` : libelleDe(n)}
                // `aria-disabled` plutôt que `disabled` : une semaine passée
                // reste atteignable au clavier, sans quoi on ne peut plus
                // savoir qu'elle l'est.
                aria-disabled={bloquee || enCours}
                onClick={() => !enCours && basculerSemaine(n)}
              >
                <span className="celcat-semaine-case" aria-hidden="true" />
                <span className="celcat-semaine-nom">
                  <strong>{numero}</strong>
                  {dates ? <span>{dates}</span> : null}
                </span>
                {statut ? <span className={`pill dot ${TON_PASTILLE[statut] ?? ""}`}>{statut}</span> : null}
              </button>
            );
          })}
        </div>
        <div className="celcat-actions">
          <button
            type="button"
            className="btn btn--accent"
            disabled={enCours || !modifie}
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
            className="btn"
            disabled={enCours || !etat.saisie_active}
            aria-describedby={!etat.saisie_active ? "envoyer-impossible" : undefined}
            onClick={() =>
              void agir(async () => {
                // Enregistre d'abord ce qui est coché : l'envoi ne connaît que la
                // sélection enregistrée côté serveur (bug utilisateur du 05/09/2026).
                await validerSemainesCelcat(brouillon);
                setEtat(await lancerNuitCelcat());
                setMessage("Semaines envoyées : les écarts sont en file.");
              })
            }
          >
            Envoyer maintenant
          </button>
          {modifie ? <span className="celcat-texte-attention">Sélection modifiée, pas encore enregistrée.</span> : null}
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
          Saisis directement dans Celcat, sans équivalent dans le planning. « Ajouter » les importe dans cal-iut ;
          « Ignorer » les retire de cette liste.
        </p>
        {extras.length === 0 ? (
          <p className="celcat-sous-texte">Aucun cours à examiner.</p>
        ) : (
          <ul className="celcat-extras">
            {extras.map((x) => {
              const label = libelleExtra(x);
              return (
                <li key={x.id} className="celcat-extra">
                  <span>
                    <strong>{label}</strong>
                    {x.event_id ? <span className="celcat-seance-id"> n° {x.event_id}</span> : null}
                  </span>
                  <div className="celcat-extra-actions">
                    <button
                      type="button"
                      className="btn btn--sm"
                      disabled={enCours}
                      aria-label={`Ajouter ${label}`}
                      onClick={() =>
                        void agir(async () => {
                          await ajouterExtraCelcat(x.id);
                          setExtras(extras.filter((e) => e.id !== x.id));
                          setMessage(`« ${label} » ajouté au planning.`);
                        })
                      }
                    >
                      Ajouter
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      disabled={enCours}
                      aria-label={`Ignorer ${label}`}
                      onClick={() =>
                        void agir(async () => {
                          await ignorerExtraCelcat(x.id);
                          setExtras(extras.filter((e) => e.id !== x.id));
                          setMessage(`« ${label} » ignoré.`);
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
            className="btn"
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
                  { title: "Reconstruire avec les suppressions", confirmLabel: "Reconstruire et supprimer", variant: "danger" },
                );
                if (!ok) return;
                await agir(async () =>
                  setMessage((await resynchroniserFileCelcat(undefined, { supprimer: true })).message),
                );
              })()
            }
          >
            Reconstruire avec suppressions…
          </button>
        </div>
      </section>
    </details>
  );
}
