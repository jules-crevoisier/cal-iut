import { useState } from "react";
import type { FormEvent } from "react";

import { login } from "../api/client";

interface LoginGateProps {
  onSuccess: () => void;
}

/** Écran de mot de passe partagé — bloque TOUT le reste de l'app tant que
 * la session n'est pas validée côté serveur (cf. api/auth.py). Les liens
 * personnels enseignants ne passent jamais par ici (App.tsx ne monte ce
 * composant que hors `readOnlyTarget`) — retour utilisateur 28/08/2026. */
export function LoginGate({ onSuccess }: LoginGateProps) {
  const [password, setPassword] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const soumettre = async (e: FormEvent) => {
    e.preventDefault();
    setEnCours(true);
    setErreur(null);
    try {
      await login(password);
      onSuccess();
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur de connexion");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div className="loginwrap">
      <form className="panel loginpanel" onSubmit={(e) => void soumettre(e)}>
        <span className="brand-mark">CI</span>
        <h1>cal-iut</h1>
        <p className="muted">Mot de passe requis pour accéder au planning.</p>
        <label>
          Mot de passe
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={enCours}
          />
        </label>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        <button type="submit" className="btn btn--primary" disabled={enCours || !password}>
          {enCours ? "Connexion…" : "Entrer"}
        </button>
      </form>
    </div>
  );
}
