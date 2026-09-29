import { CadreCompte } from "./CadreCompte";

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
      <CadreCompte
        titre="Email confirmé"
        intro={
          <p>
            Un administrateur doit maintenant vous donner accès au planning. Vous pouvez déjà vous connecter pour voir
            où en est votre demande.
          </p>
        }
      >
        <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
          Se connecter
        </button>
      </CadreCompte>
    );
  }

  return (
    <CadreCompte
      titre="Lien expiré"
      intro={<p>Ce lien de confirmation n'est plus valide. Inscrivez-vous à nouveau avec la même adresse pour en recevoir un autre.</p>}
    >
      <button type="button" className="btn btn--primary" onClick={onOuvrirInscription}>
        S'inscrire à nouveau
      </button>
    </CadreCompte>
  );
}
