/**
 * Cadre commun des pages de compte (connexion, inscription, mot de passe
 * oublié / réinitialisé, email confirmé, compte en attente).
 *
 * Refonte du 29/09/2026 : six pages recopiaient le même gabarit centré
 * (logo, titre, texte gris centré, champs à 10 px d'arrondi). Elles
 * partagent maintenant ce cadre : la marque en tête, un titre, un texte
 * aligné à gauche — plus facile à lire qu'un paragraphe centré — puis le
 * contenu et, en pied, les liens secondaires.
 */
import { useId, useState, type ReactNode } from "react";

import "./CadreCompte.css";

export function CadreCompte({
  titre,
  intro,
  children,
  pied,
  onSubmit,
}: {
  titre: string;
  intro?: ReactNode;
  children?: ReactNode;
  /** Liens secondaires (« Mot de passe oublié ? », « Créer un compte »…). */
  pied?: ReactNode;
  /** Présent : le cadre est un formulaire. */
  onSubmit?: (e: React.FormEvent<HTMLFormElement>) => void;
}) {
  const contenu = (
    <>
      <div className="compte-marque">
        <span className="brand-mark" aria-hidden="true">
          CI
        </span>
        <span>
          <strong>cal-iut</strong>
          <span className="compte-marque-sous">Emplois du temps — IUT MMI Troyes</span>
        </span>
      </div>
      <h1 className="compte-titre">{titre}</h1>
      {intro ? <div className="compte-intro">{intro}</div> : null}
      {children ? <div className="compte-corps">{children}</div> : null}
      {pied ? <div className="compte-pied">{pied}</div> : null}
    </>
  );
  return (
    <main className="loginwrap">
      {onSubmit ? (
        <form className="loginpanel" onSubmit={onSubmit} noValidate={false}>
          {contenu}
        </form>
      ) : (
        <div className="loginpanel">{contenu}</div>
      )}
    </main>
  );
}

/** Champ texte/email avec son libellé au-dessus. */
export function ChampCompte({
  libelle,
  aide,
  ...props
}: { libelle: string; aide?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="compte-champ">
      <label htmlFor={id}>{libelle}</label>
      <input id={id} aria-describedby={aide ? `${id}-aide` : undefined} {...props} />
      {aide ? (
        <p id={`${id}-aide`} className="compte-aide">
          {aide}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Mot de passe avec « Afficher » et l'alerte Verr. Maj : les deux causes
 * les plus fréquentes d'un « mot de passe incorrect » qu'on ne comprend pas.
 */
export function ChampMotDePasse({
  libelle = "Mot de passe",
  aide,
  ...props
}: { libelle?: string; aide?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const [majuscules, setMajuscules] = useState(false);
  const verifierMaj = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (typeof e.getModifierState === "function") setMajuscules(e.getModifierState("CapsLock"));
  };
  const decrits = [aide ? `${id}-aide` : "", majuscules ? `${id}-maj` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="compte-champ">
      <label htmlFor={id}>{libelle}</label>
      <div className="compte-mdp">
        <input
          id={id}
          type={visible ? "text" : "password"}
          aria-describedby={decrits}
          onKeyUp={verifierMaj}
          onKeyDown={verifierMaj}
          {...props}
        />
        <button
          type="button"
          className="btn btn--ghost btn--sm compte-mdp-voir"
          aria-pressed={visible}
          aria-controls={id}
          onClick={() => setVisible((v) => !v)}
        >
          {visible ? "Masquer" : "Afficher"}
        </button>
      </div>
      {majuscules ? (
        <p id={`${id}-maj`} className="compte-aide compte-aide--attention" role="status">
          Verrouillage des majuscules activé.
        </p>
      ) : null}
      {aide ? (
        <p id={`${id}-aide`} className="compte-aide">
          {aide}
        </p>
      ) : null}
    </div>
  );
}
