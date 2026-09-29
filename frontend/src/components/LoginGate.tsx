import { useState } from "react";
import type { FormEvent } from "react";

import { login } from "../api/client";
import { CadreCompte, ChampCompte, ChampMotDePasse } from "./CadreCompte";

interface LoginGateProps {
  onSuccess: () => void;
  onOuvrirInscription: () => void;
  onOuvrirMotDePasseOublie: () => void;
}

/** Écran de connexion par compte (email + mot de passe) — remplace le mot
 * de passe unique partagé le 31/08/2026. Bloque TOUT le reste de l'app tant
 * qu'une session valide n'est pas confirmée côté serveur (cf.
 * api/accounts.py). Les liens personnels enseignants/promo ne passent
 * jamais par ici (App.tsx ne monte ce composant que hors `readOnlyTarget`)
 * — retour utilisateur 28/08/2026. */
export function LoginGate({ onSuccess, onOuvrirInscription, onOuvrirMotDePasseOublie }: LoginGateProps) {
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const soumettre = async (e: FormEvent) => {
    e.preventDefault();
    setEnCours(true);
    setErreur(null);
    try {
      await login(email, motDePasse);
      onSuccess();
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur de connexion");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <CadreCompte
      titre="Connexion"
      onSubmit={(e) => void soumettre(e)}
      pied={
        <>
          <button type="button" className="loginpanel-lien" onClick={onOuvrirMotDePasseOublie} disabled={enCours}>
            Mot de passe oublié ?
          </button>
          <button type="button" className="loginpanel-lien" onClick={onOuvrirInscription} disabled={enCours}>
            Créer un compte
          </button>
        </>
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
        autoComplete="current-password"
        value={motDePasse}
        onChange={(e) => setMotDePasse(e.target.value)}
        disabled={enCours}
      />
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <button type="submit" className="btn btn--primary" disabled={enCours || !email || !motDePasse}>
        {enCours ? "Connexion…" : "Se connecter"}
      </button>
    </CadreCompte>
  );
}
