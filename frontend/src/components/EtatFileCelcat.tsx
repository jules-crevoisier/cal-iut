/**
 * Ce qui attend d'être poussé vers Celcat, et ce que le robot d'envoi (le
 * « worker » du sidecar) a fait en dernier.
 *
 * Retour utilisateur 08/09/2026, juste après le premier envoi réel : « là on
 * n'a pas vraiment de vue où l'on voit ce qu'il se passe si on appuie sur
 * corriger ». Puis, capture à l'appui le même jour : « fix moi cette
 * interface, on ne comprend rien du tout là ».
 *
 * L'écran est hiérarchisé :
 *
 *   1. CE QUI ATTEND, en gros — le nombre et sa répartition ;
 *   2. CE QUE LE WORKER A FAIT en dernier, et QUAND — c'est le croisement des
 *      deux qui alerte : une file qui ne bouge pas MALGRÉ des passages
 *      réguliers est le signe d'une panne ;
 *   3. LE DÉTAIL DES MOTIFS, replié.
 *
 * Les jobs EN ATTENTE D'UNE SEMAINE POSÉE sont dits à part et en clair : une
 * file qui ne descend pas parce qu'elle attend l'équipe et une file qui ne
 * descend pas parce qu'elle échoue appellent des gestes opposés.
 *
 * DEPUIS LE 16/09/2026, ce composant n'interroge plus le serveur lui-même.
 * Il était monté deux fois (onglets Activité et Contenu Celcat), chaque
 * instance sondant de son côté, et il DISPARAISSAIT sans un mot quand son
 * appel échouait — précisément au moment où l'on se demande si ça marche.
 * La vue fait l'appel une seule fois ; ici, on affiche, y compris l'échec.
 */
import type { CelcatFile } from "../api/client";
import { ageLisible, pluriel } from "../utils/celcatStatut";
import { segmentsResume } from "./segmentsResume";

const LIBELLE_ACTION: Record<string, [string, string]> = {
  create: ["création", "créations"],
  update: ["modification", "modifications"],
  delete: ["suppression", "suppressions"],
};

export function EtatFileCelcat({
  file,
  erreur,
  semaineCelcat,
  creationAutorisee,
  creationParSelection,
  onAutoriserCreation,
}: {
  file: CelcatFile | null;
  erreur?: string | null;
  /** Indice du masque Celcat de la semaine affichée (`comparaison.semaine_celcat`). */
  semaineCelcat?: number | null;
  creationAutorisee?: boolean;
  /** La semaine affichée est cochée dans « Envoi par semaine » : cela vaut
   * autorisation (07/10/2026), et c'est là-bas qu'on la retire. */
  creationParSelection?: boolean;
  onAutoriserCreation?: (autorisee: boolean) => void;
}) {
  if (erreur) {
    return (
      <p className="celcat-texte-panne" data-testid="etat-file-celcat">
        État de la file indisponible : {erreur}
      </p>
    );
  }
  // `typeof` : une réponse inattendue ne doit pas faire tomber l'écran autour.
  if (!file || typeof file.en_attente !== "number") {
    return (
      <p className="celcat-sous-texte" data-testid="etat-file-celcat">
        Lecture de la file…
      </p>
    );
  }

  const detail = Object.entries(file.par_action ?? {})
    .map(([action, n]) => {
      const mots = LIBELLE_ACTION[action];
      return mots ? pluriel(n, mots[0], mots[1]) : `${n} ${action}`;
    })
    .join(", ");
  const differes = typeof file.differes === "number" ? file.differes : 0;
  const motifs = segmentsResume(file.resume);

  return (
    <div className="celcat-file" data-testid="etat-file-celcat">
      <p className={file.en_attente > 0 ? "celcat-file-compte" : "celcat-file-compte celcat-texte-ok"}>
        {file.en_attente === 0
          ? "File d’attente vide — tout est poussé."
          : `${pluriel(file.en_attente, "correction", "corrections")} en attente${detail ? ` : ${detail}` : ""}.`}
      </p>

      <p className="celcat-file-passage">
        {file.passe_le ? (
          <>
            Dernier passage du robot d’envoi {ageLisible(file.age_secondes)} :{" "}
            <strong>{pluriel(file.reussis, "réussie", "réussies")}</strong>
            {file.echecs > 0 ? (
              <>
                , <strong className="celcat-texte-panne">{pluriel(file.echecs, "échec")}</strong>
              </>
            ) : (
              ", aucun échec"
            )}
            .
          </>
        ) : (
          "Le robot d’envoi n’est pas encore passé."
        )}
      </p>

      {differes > 0 ? (
        <div className="celcat-file-differes" data-testid="file-differes">
          {/* Le texte disait « normal, rien à faire tant que l’équipe ne l’a
              pas saisie » : c’est ce qui a laissé 492 corrections attendre
              indéfiniment une saisie manuelle que personne n’allait faire
              (signalement du 28/09/2026). On dit ce que ça bloque, ET comment
              le lever. */}
          <p>
            Dont <strong>{differes}</strong> en attente d’une semaine que Celcat n’a pas encore ouverte. Le robot
            d’envoi n’y crée rien tant que l’équipe ne l’a pas saisie — ou tant que vous ne l’autorisez pas ici.
          </p>
          {creationParSelection ? (
            <p className="celcat-file-autorisation">
              <strong>Création autorisée</strong> : la semaine affichée est cochée dans « Envoi par semaine ».
            </p>
          ) : semaineCelcat !== null && semaineCelcat !== undefined && onAutoriserCreation ? (
            creationAutorisee ? (
              <p className="celcat-file-autorisation">
                <strong>Création autorisée</strong> sur la semaine affichée.{" "}
                <button type="button" className="btn btn--sm" onClick={() => onAutoriserCreation(false)}>
                  Retirer l’autorisation
                </button>
              </p>
            ) : (
              <button type="button" className="btn btn--sm" onClick={() => onAutoriserCreation(true)}>
                Autoriser la création sur la semaine affichée
              </button>
            )
          ) : null}
        </div>
      ) : null}

      {motifs.length > 0 ? (
        <details data-testid="file-motifs" className="celcat-repli">
          <summary>Détail des motifs ({motifs.length})</summary>
          <ul>
            {motifs.map((motif) => (
              <li key={motif}>{motif}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
