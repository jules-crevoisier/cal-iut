import { useState } from "react";
import type { FormEvent } from "react";

import { forgotPassword } from "../api/client";

interface ForgotPasswordPageProps {
  onRetourConnexion: () => void;
}

/** Mot de passe oublié (31/08/2026) — répond TOUJOURS pareil, email connu
 * ou non (anti-énumération, cf. `api/main.py::auth_forgot_password`) :
 * cet écran ne peut donc jamais dire si l'adresse existe. */
export function ForgotPasswordPage({ onRetourConnexion }: ForgotPasswordPageProps) {
  const [email, setEmail] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [envoye, setEnvoye] = useState(false);

  const soumettre = async (e: FormEvent) => {
    e.preventDefault();
    setEnCours(true);
    try {
      await forgotPassword(email);
    } catch {
      // Volontairement ignoré : la réponse ne doit jamais varier selon que
      // l'email existe ou non — même un échec réseau affiche le même message.
    } finally {
      setEnCours(false);
      setEnvoye(true);
    }
  };

  if (envoye) {
    return (
      <div className="loginwrap">
        <div className="panel loginpanel">
          <span className="brand-mark">CI</span>
          <h1>Vérifiez vos mails</h1>
          <p className="muted">
            Si un compte existe pour <strong>{email}</strong>, un lien de réinitialisation vient d'être envoyé.
          </p>
          <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
            Retour à la connexion
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="loginwrap">
      <form className="panel loginpanel" onSubmit={(e) => void soumettre(e)}>
        <span className="brand-mark">CI</span>
        <h1>Mot de passe oublié</h1>
        <p className="muted">Recevez un lien de réinitialisation par email.</p>
        <label>
          Email
          <input
            type="email"
            autoFocus
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={enCours}
          />
        </label>
        <button type="submit" className="btn btn--primary" disabled={enCours || !email}>
          {enCours ? "Envoi…" : "Envoyer le lien"}
        </button>
        <div className="loginpanel-liens">
          <button type="button" className="loginpanel-lien" onClick={onRetourConnexion} disabled={enCours}>
            Retour à la connexion
          </button>
        </div>
      </form>
    </div>
  );
}
