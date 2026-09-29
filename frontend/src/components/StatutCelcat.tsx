/**
 * Les trois conditions sans lesquelles rien ne part dans Celcat : écriture,
 * robot d'envoi, lecture de Celcat.
 *
 * Refonte du 29/09/2026 : les trois cartes occupaient tout le haut de
 * l'écran, au-dessus du verdict — la question qu'on vient poser. Elles
 * tiennent maintenant sur UNE ligne, à côté du choix de la semaine. Un
 * signal sain reste discret ; un signal qui demande attention prend sa
 * couleur et garde sa phrase de conséquence.
 *
 * Chaque signal porte un MOT (« active », « en pause », « périmé ») : la
 * couleur ne dit jamais seule ce qui se passe.
 */
import type { CelcatEtat, CelcatFile, CelcatInstantane } from "../api/client";
import { PILULE, signauxSysteme } from "../utils/celcatStatut";

export function StatutCelcat({
  etat,
  instantane,
  file,
  erreurInstantane,
}: {
  etat: CelcatEtat;
  instantane: CelcatInstantane | null;
  file: CelcatFile | null;
  erreurInstantane?: string | null;
}) {
  const signaux = signauxSysteme(etat, instantane, file).map((s) =>
    // « Je n'ai pas pu lire l'état de la lecture » et « Celcat n'a jamais
    // été lu » sont deux choses différentes : les confondre a fait afficher
    // « aucun relevé » alors qu'il en existait un de trente-six minutes.
    s.cle === "releve" && erreurInstantane
      ? { ...s, etat: "indisponible", ton: "panne" as const, detail: erreurInstantane }
      : s,
  );
  return (
    <section className="celcat-statut" aria-label="État de la synchronisation Celcat">
      <dl className="celcat-signaux">
        {signaux.map((s) => (
          <div key={s.cle} className={`celcat-signal celcat-signal--${s.ton}`} data-testid={`signal-${s.cle}`}>
            <dt>{s.libelle}</dt>
            <dd>
              <span className={`pill dot ${PILULE[s.ton]}`}>{s.etat}</span>
              {/* « Chaque modification part dans Celcat » : l'état normal n'a
                  pas besoin de sa phrase à l'écran, les lecteurs d'écran la
                  gardent. */}
              <span className={s.cle === "ecriture" && s.ton === "ok" ? "sr-only" : "celcat-signal-detail"}>
                {s.detail}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
