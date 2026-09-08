/**
 * Ce qui attend d'être poussé vers Celcat, et ce que le worker a fait en
 * dernier.
 *
 * Retour utilisateur 08/09/2026, juste après le premier envoi réel : « là on
 * n'a pas vraiment de vue où l'on voit ce qu'il se passe si on appuie sur
 * corriger ». Le bouton annonçait « 38 corrections mises en file », puis
 * plus rien.
 *
 * Les deux informations sont montrées ENSEMBLE parce qu'elles ne disent pas
 * la même chose, et que c'est leur croisement qui alerte : une file qui ne
 * bouge pas MALGRÉ des passages réguliers est le signe d'une panne. C'est
 * exactement ce que trois jours de « file d'attente drainée » n'ont pas
 * permis de voir.
 *
 * Se rafraîchit tout seul tant qu'il reste des jobs : après avoir cliqué, on
 * veut voir la file descendre sans avoir à recharger la page.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchCelcatFile, type CelcatFile } from "../api/client";

function ageLisible(secondes: number | null): string {
  if (secondes === null) return "";
  if (secondes < 60) return `il y a ${Math.max(1, Math.round(secondes))} s`;
  const minutes = Math.floor(secondes / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  return `il y a ${Math.floor(minutes / 60)} h`;
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
    .map(([action, n]) => `${n} ${action}`)
    .join(", ");

  // Une file qui ne descend pas parce qu'elle ATTEND que l'équipe ouvre les
  // semaines dans Celcat, et une file qui ne descend pas parce qu'elle
  // ÉCHOUE, se ressemblent à l'écran et appellent des gestes opposés : dans
  // un cas il n'y a rien à faire, dans l'autre il faut aller voir. On le dit
  // donc explicitement plutôt que de laisser déduire du compteur.
  const differes = typeof file.differes === "number" ? file.differes : 0;

  return (
    <p className={file.en_attente > 0 ? "bad" : "muted"} data-testid="etat-file-celcat">
      {file.en_attente === 0
        ? "File d’attente vide — tout est poussé."
        : `${file.en_attente} correction(s) en attente${detail ? ` (${detail})` : ""}.`}{" "}
      {file.passe_le
        ? `Dernier passage du worker ${ageLisible(file.age_secondes)} : ${file.resume || "—"}.`
        : "Le worker n’est pas encore passé."}
      {differes > 0 ? (
        <>
          {" "}
          <span data-testid="file-differes">
            Dont {differes} en attente d’une semaine encore non posée dans Celcat — normal,
            rien à faire tant que l’équipe ne l’a pas saisie.
          </span>
        </>
      ) : null}
    </p>
  );
}
