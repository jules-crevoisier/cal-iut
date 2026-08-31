import { useState } from "react";
import type { FormEvent } from "react";

import { resetPassword } from "../api/client";

interface ResetPasswordPageProps {
  token: string;
  onRetourConnexion: () => void;
}

/** Réinitialisation (31/08/2026) — atteinte via le lien du mail (jeton dans
 * `#compte=reinitialiser&token=...`, jamais envoyé au serveur autrement que
 * dans le corps de cette requête). Jeton absent : lien mal formé, rien à
 * tenter. */
export function ResetPasswordPage({ token, onRetourConnexion }: ResetPasswordPageProps) {
  const [motDePasse, setMotDePasse] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [reussi, setReussi] = useState(false);

  const soumettre = async (e: FormEvent) => {
    e.preventDefault();
    setEnCours(true);
    setErreur(null);
    try {
      await resetPassword(token, motDePasse);
      setReussi(true);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur de réinitialisation");
    } finally {
      setEnCours(false);
    }
  };

  if (!token) {
    return (
      <div className="loginwrap">
        <div className="panel loginpanel">
          <span className="brand-mark">CI</span>
          <h1>Lien invalide</h1>
          <p className="muted">Ce lien de réinitialisation est incomplet.</p>
          <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
            Retour à la connexion
          </button>
        </div>
      </div>
    );
  }

  if (reussi) {
    return (
      <div className="loginwrap">
        <div className="panel loginpanel">
          <span className="brand-mark">CI</span>
          <h1>Mot de passe changé</h1>
          <p className="muted">Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.</p>
          <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
            Se connecter
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="loginwrap">
      <form className="panel loginpanel" onSubmit={(e) => void soumettre(e)}>
        <span className="brand-mark">CI</span>
        <h1>Nouveau mot de passe</h1>
        <label>
          Nouveau mot de passe
          <input
            type="password"
            autoFocus
            autoComplete="new-password"
            minLength={10}
            value={motDePasse}
            onChange={(e) => setMotDePasse(e.target.value)}
            disabled={enCours}
          />
        </label>
        <p className="loginpanel-aide">10 caractères minimum.</p>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        <button type="submit" className="btn btn--primary" disabled={enCours || motDePasse.length < 10}>
          {enCours ? "Enregistrement…" : "Changer le mot de passe"}
        </button>
      </form>
    </div>
  );
}
