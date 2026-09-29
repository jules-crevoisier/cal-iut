import { useState } from "react";
import type { FormEvent } from "react";

import { resetPassword } from "../api/client";
import { CadreCompte, ChampMotDePasse } from "./CadreCompte";

interface ResetPasswordPageProps {
  token: string;
  onRetourConnexion: () => void;
}

const LONGUEUR_MIN = 10;

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
      <CadreCompte
        titre="Lien invalide"
        intro={<p>Ce lien de réinitialisation est incomplet. Demandez-en un nouveau depuis « Mot de passe oublié ? ».</p>}
      >
        <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
          Retour à la connexion
        </button>
      </CadreCompte>
    );
  }

  if (reussi) {
    return (
      <CadreCompte
        titre="Mot de passe changé"
        intro={<p>Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.</p>}
      >
        <button type="button" className="btn btn--primary" onClick={onRetourConnexion}>
          Se connecter
        </button>
      </CadreCompte>
    );
  }

  const manque = Math.max(0, LONGUEUR_MIN - motDePasse.length);

  return (
    <CadreCompte titre="Nouveau mot de passe" onSubmit={(e) => void soumettre(e)}>
      <ChampMotDePasse
        libelle="Nouveau mot de passe"
        autoFocus
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
      <button type="submit" className="btn btn--primary" disabled={enCours || motDePasse.length < LONGUEUR_MIN}>
        {enCours ? "Enregistrement…" : "Changer le mot de passe"}
      </button>
    </CadreCompte>
  );
}
