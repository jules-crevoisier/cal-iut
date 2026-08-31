interface EmailConfirmedPageProps {
  statut: "" | "ok" | "erreur";
  onOuvrirInscription: () => void;
  onRetourConnexion: () => void;
}

/** Atterrissage du lien de confirmation d'email (`GET /auth/confirm-email`,
 * redirection serveur vers `#compte=confirme&statut=ok|erreur`). `erreur` =
 * jeton expiré/déjà utilisé/inconnu — un nouveau signup sur la même adresse
 * renvoie automatiquement un jeton frais (anti scan-antivirus, décision
 * verrouillée du 31/08/2026), donc le repli proposé ici est bien de
 * s'inscrire à nouveau, pas de contacter un admin. */
export function EmailConfirmedPage({ statut, onOuvrirInscription, onRetourConnexion }: EmailConfirmedPageProps) {
  if (statut === "ok") {
    return (
      <div className="loginwrap">
        <div className="panel loginpanel">
          <span className="brand-mark">CI</span>
          <h1>Email confirmé</h1>
          <p className="muted">
            Votre compte est confirmé. Un administrateur doit maintenant vous donner accès au planning — vous
            pouvez déjà vous connecter pour voir où ça en est.
          </p>
          <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
            Se connecter
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="loginwrap">
      <div className="panel loginpanel">
        <span className="brand-mark">CI</span>
        <h1>Lien expiré</h1>
        <p className="muted">Ce lien de confirmation n'est plus valide. Inscrivez-vous à nouveau pour en recevoir un autre.</p>
        <button type="button" className="btn btn--primary" onClick={onOuvrirInscription}>
          S'inscrire à nouveau
        </button>
      </div>
    </div>
  );
}
