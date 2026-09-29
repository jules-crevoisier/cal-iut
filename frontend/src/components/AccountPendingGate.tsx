import { logout } from "../api/client";
import { CadreCompte } from "./CadreCompte";

interface AccountPendingGateProps {
  email: string;
  onDeconnecte: () => void;
}

/** Compte connecté mais non actif — en pratique toujours
 * `pending_admin_activation` : `pending_email` et `disabled` ne peuvent
 * jamais obtenir de cookie en premier lieu (`POST /auth/login` les refuse
 * en 403, cf. `api/main.py`), seul un compte confirmé mais pas encore
 * activé par un admin arrive jusqu'ici. */
export function AccountPendingGate({ email, onDeconnecte }: AccountPendingGateProps) {
  const deconnecter = () => {
    void logout().finally(onDeconnecte);
  };

  return (
    <CadreCompte
      titre="En attente d'activation"
      intro={
        <>
          <p>
            Votre compte <strong>{email}</strong> est confirmé. Il reste à un administrateur à vous donner accès au
            planning.
          </p>
          <p>Une fois prévenu, cliquez « Vérifier à nouveau » : aucune autre démarche n'est nécessaire.</p>
        </>
      }
    >
      <button type="button" className="btn" onClick={() => window.location.reload()}>
        Vérifier à nouveau
      </button>
      <button type="button" className="btn btn--ghost" onClick={deconnecter}>
        Se déconnecter
      </button>
    </CadreCompte>
  );
}
