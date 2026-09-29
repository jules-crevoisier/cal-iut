/**
 * Question posée une seule fois : couleurs par matière, ou par type ?
 *
 * Retour utilisateur 30/08/2026 : « pour les liens des groupes je vois cela
 * comme un popup qui s'affiche et qui demande les préférences, et on stocke
 * cela et on garde en mémoire pour ne pas que l'on redemande à chaque fois ».
 *
 * Elle ne réapparaît PAS quand la réponse est « non » : c'est `repondu` qui
 * ferme la question, pas la valeur choisie.
 *
 * Refonte du 29/09/2026 : chaque choix EST son aperçu. Deux aperçus puis
 * deux boutons à rapprocher d'eux faisaient lire trois blocs pour un clic ;
 * on clique désormais directement sur l'aperçu qu'on préfère. L'aperçu est
 * dessiné ici (`.prefs-puce`), indépendamment des styles de la grille.
 */

import { couleursMatiere } from "../utils/couleursMatiere";
import "./PreferencesModal.css";

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
        aria-describedby="prefsmodal-texte"
      >
        <h3 id="prefsmodal-titre">Comment préférez-vous voir vos cours ?</h3>
        <p id="prefsmodal-texte" className="prefs-texte">
          Choisissez l’affichage qui vous parle le plus. Ce choix est gardé sur cet appareil et reste modifiable à
          tout moment.
        </p>

        <div className="prefs-choix">
          <button type="button" className="prefs-option" autoFocus onClick={() => onChoix(true)}>
            <span className="prefs-option-titre">Une couleur par matière</span>
            <span className="prefs-option-sens">Repérer un cours d’un coup d’œil.</span>
            <span className="prefs-apercu" aria-hidden="true">
              {APERCU.map((c) => (
                <span key={c.code} className="prefs-puce prefs-puce--matiere" style={couleursMatiere(c.code) as React.CSSProperties}>
                  <span className="prefs-puce-code">{c.code}</span>
                  <span className="prefs-puce-nom">{c.nom}</span>
                  <span className="prefs-puce-type">{c.type}</span>
                </span>
              ))}
            </span>
          </button>
          <button type="button" className="prefs-option" onClick={() => onChoix(false)}>
            <span className="prefs-option-titre">Une couleur par type de séance</span>
            <span className="prefs-option-sens">CM, TD, TP — l’affichage habituel.</span>
            <span className="prefs-apercu" aria-hidden="true">
              {APERCU.map((c) => (
                <span key={c.code} className={`prefs-puce prefs-puce--${c.type.toLowerCase()}`}>
                  <span className="prefs-puce-code">{c.code}</span>
                  <span className="prefs-puce-nom">{c.nom}</span>
                  <span className="prefs-puce-type">{c.type}</span>
                </span>
              ))}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
