/**
 * Question posée une seule fois : couleurs par matière, ou non ?
 *
 * Retour utilisateur 30/08/2026 : « pour les liens des groupes je vois cela
 * comme un popup qui s'affiche et qui demande les préférences, et on stocke
 * cela et on garde en mémoire pour ne pas que l'on redemande à chaque fois ».
 *
 * Elle ne réapparaît PAS quand la réponse est « non » : c'est `repondu` qui
 * ferme la question, pas la valeur choisie. Une question reposée à chaque
 * visite parce qu'on a dit non est le défaut le plus agaçant de ce genre de
 * fenêtre.
 *
 * Un aperçu réel accompagne chaque choix : « couleurs par matière » ne dit
 * pas grand-chose tant qu'on ne l'a pas vu.
 */

import { teinteMatiere, varianteMatiere } from "../utils/couleursMatiere";

interface PreferencesModalProps {
  onChoix: (couleursParMatiere: boolean) => void;
}

const APERCU = [
  { code: "WR104", nom: "Culture numérique", type: "CM" },
  { code: "WR106", nom: "Expression", type: "TD" },
  { code: "WR112", nom: "Intégration web", type: "TP" },
];

export function PreferencesModal({ onChoix }: PreferencesModalProps) {
  return (
    <div className="confirmmodal-overlay" role="presentation">
      <div
        className="panel confirmmodal prefsmodal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="prefsmodal-titre"
      >
        <h3 id="prefsmodal-titre">Comment préférez-vous voir vos cours ?</h3>
        <p className="confirmmodal-message">
          Une couleur différente par matière aide à repérer un cours d'un coup d'œil. Sinon, la couleur
          indique le type de séance (CM, TD, TP), comme aujourd'hui.
        </p>

        <div className="prefs-apercus">
          <div className="prefs-apercu">
            <span className="prefs-apercu-titre">Une couleur par matière</span>
            <div className="prefs-apercu-grille couleurs-matiere">
              {APERCU.map((c) => (
                <span
                  key={c.code}
                  className="promo-chip"
                  style={{
                    ["--teinte-matiere" as string]: String(teinteMatiere(c.code)),
                    ["--variante-matiere" as string]: String(varianteMatiere(c.code)),
                  }}
                >
                  <span className="code">{c.code}</span>
                  <span className="ty">{c.type}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="prefs-apercu">
            <span className="prefs-apercu-titre">Une couleur par type</span>
            <div className="prefs-apercu-grille">
              {APERCU.map((c) => (
                <span key={c.code} className={`promo-chip type-${c.type.toLowerCase()}`}>
                  <span className="code">{c.code}</span>
                  <span className="ty">{c.type}</span>
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={() => onChoix(false)}>
            Par type de séance
          </button>
          <button type="button" className="btn btn--accent" autoFocus onClick={() => onChoix(true)}>
            Par matière
          </button>
        </div>
        <p className="prefs-note">Ce choix est gardé sur cet appareil, et modifiable à tout moment en haut de page.</p>
      </div>
    </div>
  );
}
