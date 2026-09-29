import { useState } from "react";
import type { FormEvent } from "react";

import { forgotPassword } from "../api/client";
import { CadreCompte, ChampCompte } from "./CadreCompte";

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
      <CadreCompte
        titre="Vérifiez vos mails"
        intro={
          <>
            <p>
              Si un compte existe pour <strong>{email}</strong>, un lien de réinitialisation vient d'être envoyé.
            </p>
            <p>Pensez à regarder dans les indésirables.</p>
          </>
        }
      >
        <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
          Retour à la connexion
        </button>
      </CadreCompte>
    );
  }

  return (
    <CadreCompte
      titre="Mot de passe oublié"
      intro={<p>Indiquez votre email : vous recevrez un lien pour choisir un nouveau mot de passe.</p>}
      onSubmit={(e) => void soumettre(e)}
      pied={
        <button type="button" className="loginpanel-lien" onClick={onRetourConnexion} disabled={enCours}>
          Retour à la connexion
        </button>
      }
    >
      <ChampCompte
        libelle="Email"
        type="email"
        autoFocus
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        disabled={enCours}
      />
      <button type="submit" className="btn btn--primary" disabled={enCours || !email}>
        {enCours ? "Envoi…" : "Envoyer le lien"}
      </button>
    </CadreCompte>
  );
}
