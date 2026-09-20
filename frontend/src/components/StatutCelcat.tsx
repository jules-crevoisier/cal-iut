/**
 * Les trois conditions sans lesquelles rien ne part dans Celcat, d'un coup d'œil.
 *
 * Elles étaient éparpillées : l'écriture et le worker dans l'onglet
 * « Pilotage », l'âge du relevé dans « Contenu Celcat », loin de la
 * comparaison qu'il conditionne. Pour savoir pourquoi une correction ne
 * partait pas, il fallait recouper trois panneaux.
 *
 * Chaque signal porte un MOT (« active », « en pause », « périmé ») et une
 * phrase de conséquence : la couleur ne dit jamais seule ce qui se passe.
 */
import type { CelcatEtat, CelcatFile, CelcatInstantane } from "../api/client";
import { PILULE, signauxSysteme } from "../utils/celcatStatut";

export function StatutCelcat({
  etat,
  instantane,
  file,
}: {
  etat: CelcatEtat;
  instantane: CelcatInstantane | null;
  file: CelcatFile | null;
}) {
  const signaux = signauxSysteme(etat, instantane, file);
  return (
    <section className="celcat-statut" aria-label="État de la synchronisation Celcat">
      <dl className="celcat-signaux">
        {signaux.map((s) => (
          <div key={s.cle} className={`celcat-signal celcat-signal--${s.ton}`} data-testid={`signal-${s.cle}`}>
            <dt>{s.libelle}</dt>
            <dd>
              <span className={`pill ${PILULE[s.ton]}`}>{s.etat}</span>
              <span className="celcat-signal-detail">{s.detail}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
