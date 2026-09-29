/**
 * Serveur injoignable (audit du 29/09/2026, P1-13).
 *
 * Avant, une coupure réseau se déguisait : écran de connexion (alors que la
 * session était bonne) ou « aucun planning » (alors qu'il existait). Ce
 * bandeau dit ce qui se passe, sans rien retirer de l'écran : le dernier
 * état reçu reste affiché dessous. `App.tsx` retente tout seul à intervalle
 * régulier ; « Réessayer » n'attend pas le prochain tour.
 *
 * Refonte v2 (29/09/2026) : une icône en tête de chaque bandeau, pour qu'on
 * les distingue d'un message ordinaire sans lire la couleur seule.
 */
import { ServerCrash, WifiOff } from "lucide-react";

import "./BandeauPanne.css";

export function BandeauPanne({ onReessayer }: { onReessayer: () => void }) {
  return (
    <div className="banner banner--warn bandeau-panne no-print" role="alert">
      <WifiOff size={16} className="bandeau-icone" aria-hidden="true" />
      <span className="bandeau-texte">
        <strong>Serveur injoignable — nouvelle tentative…</strong> Ce qui est affiché peut ne pas être à jour.
      </span>
      <button type="button" className="btn btn--sm" onClick={onReessayer}>
        Réessayer
      </button>
    </div>
  );
}

/** Planning enregistré mais non chargé côté serveur (`/health` en 503
 *  `degraded`, audit du 29/09/2026, P1-6). Réservé aux admins : ce sont eux
 *  qui peuvent agir (configuration, redémarrage). */
export function BandeauServeurDegrade({ detail }: { detail?: string }) {
  return (
    <div className="banner banner--error bandeau-panne" role="alert">
      <ServerCrash size={16} className="bandeau-icone" aria-hidden="true" />
      <span className="bandeau-texte">
        <strong>Le serveur n'a pas chargé le planning enregistré.</strong> Les écrans peuvent montrer un planning
        vide ou incomplet : ne modifiez rien avant d'avoir corrigé la cause et redémarré le serveur.
        {detail ? <> Cause signalée : {detail}</> : null}
      </span>
    </div>
  );
}
