import { useState } from "react";
import type { FormEvent } from "react";

import { signup } from "../api/client";
import { CadreCompte, ChampCompte, ChampMotDePasse } from "./CadreCompte";

interface SignupPageProps {
  onRetourConnexion: () => void;
}

const LONGUEUR_MIN = 10;

/** Inscription (31/08/2026) — ouverte à n'importe quel email. Le compte
 * créé reste `pending_email` jusqu'à confirmation par le lien envoyé par
 * mail, puis `pending_admin_activation` (sauf les deux adresses admin,
 * cf. `api/accounts.py::ADMIN_EMAILS`, actives immédiatement) tant qu'un
 * admin ne lui donne pas de rôle. Les deux étapes sont annoncées ici, pour
 * qu'on ne s'étonne pas d'attendre après avoir cliqué le lien. */
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
      <CadreCompte
        titre="Vérifiez vos mails"
        intro={
          <>
            <p>
              Un lien de confirmation a été envoyé à <strong>{email}</strong>.
            </p>
            <p>Cliquez dessus pour confirmer votre adresse ; un administrateur vous donnera ensuite accès au planning.</p>
          </>
        }
      >
        <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
          Retour à la connexion
        </button>
      </CadreCompte>
    );
  }

  const manque = Math.max(0, LONGUEUR_MIN - motDePasse.length);

  return (
    <CadreCompte
      titre="Créer un compte"
      intro={<p>Un administrateur activera ensuite votre accès au planning.</p>}
      onSubmit={(e) => void soumettre(e)}
      pied={
        <button type="button" className="loginpanel-lien" onClick={onRetourConnexion} disabled={enCours}>
          J'ai déjà un compte
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
      <ChampMotDePasse
        autoComplete="new-password"
        minLength={LONGUEUR_MIN}
        value={motDePasse}
        onChange={(e) => setMotDePasse(e.target.value)}
        disabled={enCours}
        aide={
          manque === 0
            ? `${LONGUEUR_MIN} caractères minimum — c'est bon.`
            : `${LONGUEUR_MIN} caractères minimum${motDePasse ? ` (encore ${manque})` : ""}.`
        }
      />
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <button type="submit" className="btn btn--primary" disabled={enCours || !email || motDePasse.length < LONGUEUR_MIN}>
        {enCours ? "Inscription…" : "S'inscrire"}
      </button>
    </CadreCompte>
  );
}
