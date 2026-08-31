import { useState } from "react";
import type { FormEvent } from "react";

import { signup } from "../api/client";

interface SignupPageProps {
  onRetourConnexion: () => void;
}

/** Inscription (31/08/2026) — ouverte à n'importe quel email. Le compte
 * créé reste `pending_email` jusqu'à confirmation par le lien envoyé par
 * mail, puis `pending_admin_activation` (sauf les deux adresses admin,
 * cf. `api/accounts.py::ADMIN_EMAILS`, actives immédiatement) tant qu'un
 * admin ne lui donne pas de rôle — rien de tout ça ne se voit ici, cet
 * écran ne fait que déclencher l'envoi du mail. */
export function SignupPage({ onRetourConnexion }: SignupPageProps) {
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoye, setEnvoye] = useState(false);

  const soumettre = async (e: FormEvent) => {
    e.preventDefault();
    setEnCours(true);
    setErreur(null);
    try {
      await signup(email, motDePasse);
      setEnvoye(true);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur d'inscription");
    } finally {
      setEnCours(false);
    }
  };

  if (envoye) {
    return (
      <div className="loginwrap">
        <div className="panel loginpanel">
          <span className="brand-mark">CI</span>
          <h1>Vérifiez vos mails</h1>
          <p className="muted">
            Un lien de confirmation a été envoyé à <strong>{email}</strong>. Cliquez dessus pour activer votre
            compte, puis un administrateur vous donnera accès au planning.
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
        <h1>Créer un compte</h1>
        <p className="muted">N'importe quel email — un administrateur devra ensuite activer votre accès.</p>
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
        <label>
          Mot de passe
          <input
            type="password"
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
        <button type="submit" className="btn btn--primary" disabled={enCours || !email || motDePasse.length < 10}>
          {enCours ? "Inscription…" : "S'inscrire"}
        </button>
        <div className="loginpanel-liens">
          <button type="button" className="loginpanel-lien" onClick={onRetourConnexion} disabled={enCours}>
            J'ai déjà un compte
          </button>
        </div>
      </form>
    </div>
  );
}
