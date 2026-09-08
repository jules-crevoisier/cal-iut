/**
 * Ce qui attend d'être poussé vers Celcat, et ce que le worker a fait en
 * dernier.
 *
 * Retour utilisateur 08/09/2026, juste après le premier envoi réel : « là on
 * n'a pas vraiment de vue où l'on voit ce qu'il se passe si on appuie sur
 * corriger ». Puis, capture à l'appui le même jour : « fix moi cette
 * interface, on ne comprend rien du tout là ».
 *
 * IL AVAIT RAISON DEUX FOIS. La première version ne montrait rien ; la
 * seconde montrait TOUT, d'un bloc — le résumé brut du worker, vingt lignes
 * de motifs d'échec au milieu desquelles les trois chiffres qui décident
 * (combien attendent, combien ont réussi, quand) étaient introuvables.
 *
 * L'écran est donc hiérarchisé :
 *
 *   1. CE QUI ATTEND, en gros — le nombre et sa répartition ;
 *   2. CE QUE LE WORKER A FAIT en dernier, et QUAND — c'est le croisement des
 *      deux qui alerte : une file qui ne bouge pas MALGRÉ des passages
 *      réguliers est le signe d'une panne, et c'est exactement ce que trois
 *      jours de « file d'attente drainée » n'ont pas permis de voir ;
 *   3. LE DÉTAIL DES MOTIFS, replié. Il ne se lit pas tous les jours, mais
 *      quand on en a besoin il n'existe nulle part ailleurs que dans
 *      `docker compose logs`.
 *
 * Les jobs EN ATTENTE D'UNE SEMAINE POSÉE sont dits à part et en clair :
 * une file qui ne descend pas parce qu'elle attend l'équipe et une file qui
 * ne descend pas parce qu'elle échoue se ressemblent à l'écran et appellent
 * des gestes opposés.
 *
 * Se rafraîchit tout seul tant qu'il reste des jobs : après avoir cliqué, on
 * veut voir la file descendre sans recharger la page.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchCelcatFile, type CelcatFile } from "../api/client";
import { ageLisible, segmentsResume } from "./segmentsResume";

const LIBELLE_ACTION: Record<string, string> = {
  create: "création",
  update: "modification",
  delete: "suppression",
};

function pluriel(n: number, mot: string): string {
  return `${n} ${mot}${n > 1 ? "s" : ""}`;
}

export function EtatFileCelcat() {
  const [file, setFile] = useState<CelcatFile | null>(null);
  const timer = useRef<number>(0);

  const charger = useCallback(async () => {
    try {
      setFile(await fetchCelcatFile());
    } catch {
      setFile(null);
    }
  }, []);

  useEffect(() => {
    void charger();
    return () => window.clearTimeout(timer.current);
  }, [charger]);

  // Tant qu'il reste des jobs, on re-regarde : c'est le moment où l'on veut
  // voir la file descendre. Une fois vide, on arrête — un écran qui
  // interroge le serveur sans raison est un écran qu'on finit par fermer.
  useEffect(() => {
    if (!file || file.en_attente === 0) return;
    timer.current = window.setTimeout(() => void charger(), 10_000);
    return () => window.clearTimeout(timer.current);
  }, [file, charger]);

  // `typeof` et `?? {}` : une réponse inattendue ne doit pas faire tomber
  // tout l'écran autour. C'est la troisième fois de la journée que cet
  // oubli casse un panneau — les données d'API se protègent à l'entrée du
  // composant, pas au cas par cas.
  if (!file || typeof file.en_attente !== "number") return null;

  const detail = Object.entries(file.par_action ?? {})
    .map(([action, n]) => pluriel(n, LIBELLE_ACTION[action] ?? action))
    .join(", ");
  const differes = typeof file.differes === "number" ? file.differes : 0;
  const motifs = segmentsResume(file.resume);

  return (
    <div className="celcat-file" data-testid="etat-file-celcat">
      <p className={file.en_attente > 0 ? "bad" : "muted"}>
        {file.en_attente === 0
          ? "File d’attente vide — tout est poussé."
          : `${file.en_attente} correction(s) en attente${detail ? ` : ${detail}` : ""}.`}
      </p>

      <p className="muted">
        {file.passe_le ? (
          <>
            Dernier passage du worker {ageLisible(file.age_secondes)} :{" "}
            <strong>{file.reussis} réussi(s)</strong>, {file.echecs} en échec.
          </>
        ) : (
          "Le worker n’est pas encore passé."
        )}
      </p>

      {differes > 0 ? (
        <p className="muted" data-testid="file-differes">
          Dont <strong>{differes}</strong> en attente d’une semaine encore non posée dans
          Celcat — normal, rien à faire tant que l’équipe ne l’a pas saisie.
        </p>
      ) : null}

      {motifs.length > 0 ? (
        <details data-testid="file-motifs">
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
