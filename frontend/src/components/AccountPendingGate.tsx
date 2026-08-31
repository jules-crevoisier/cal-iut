import { logout } from "../api/client";

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
    <div className="loginwrap">
      <div className="panel loginpanel">
        <span className="brand-mark">CI</span>
        <h1>En attente d'activation</h1>
        <p className="muted">
          Votre compte <strong>{email}</strong> est confirmé, mais un administrateur ne vous a pas encore donné
          accès au planning.
        </p>
        <button type="button" className="btn btn--primary" onClick={deconnecter}>
          Se déconnecter
        </button>
      </div>
    </div>
  );
}
