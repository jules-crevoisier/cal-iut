/**
 * Cadre commun des pages de compte (connexion, inscription, mot de passe
 * oublié / réinitialisé, email confirmé, compte en attente).
 *
 * Refonte du 29/09/2026 : six pages recopiaient le même gabarit centré
 * (logo, titre, texte gris centré, champs à 10 px d'arrondi). Elles
 * partagent maintenant ce cadre : la marque en tête, un titre, un texte
 * aligné à gauche — plus facile à lire qu'un paragraphe centré — puis le
 * contenu et, en pied, les liens secondaires.
 *
 * Refonte v2 (même jour, direction « Lumière / Nuit ») : c'est la première
 * impression de l'outil, elle en prend l'identité. À gauche, la colonne de
 * la navigation (même fond, même marque) dit ce qu'est cal-iut et rappelle
 * aux enseignants et étudiants que leur lien personnel s'ouvre SANS compte
 * (retour utilisateur 28/08/2026) ; à droite, le formulaire à plat, sans
 * carte, bouton principal noir. Sur téléphone, la colonne se réduit à la
 * marque.
 */
import { useId, useState, type ReactNode } from "react";
import { CalendarRange, Link2, UserRound } from "lucide-react";

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
      <h1 className="compte-titre">{titre}</h1>
      {intro ? <div className="compte-intro">{intro}</div> : null}
      {children ? <div className="compte-corps">{children}</div> : null}
      {pied ? <div className="compte-pied">{pied}</div> : null}
    </>
  );
  return (
    <main className="loginwrap">
      <aside className="compte-cote" aria-label="cal-iut">
        <div className="compte-marque">
          <span className="brand-mark" aria-hidden="true">
            ci
          </span>
          <span>
            <strong>cal-iut</strong>
            <span className="compte-marque-sous">MMI Troyes</span>
          </span>
        </div>
        <div className="compte-cote-corps">
          <p className="compte-cote-titre">Les emplois du temps du département MMI.</p>
          <ul className="compte-cote-faits">
            <li>
              <CalendarRange size={16} aria-hidden="true" />
              <span>La semaine de chaque promo, enseignant, groupe et salle.</span>
            </li>
            <li>
              <Link2 size={16} aria-hidden="true" />
              <span>
                Enseignants et étudiants : votre <strong>lien personnel</strong> ouvre votre planning sans compte ni mot
                de passe.
              </span>
            </li>
            <li>
              <UserRound size={16} aria-hidden="true" />
              <span>Un compte sert à ceux qui préparent et corrigent le planning.</span>
            </li>
          </ul>
        </div>
        <p className="compte-cote-pied">IUT de Troyes — Métiers du multimédia et de l'internet</p>
      </aside>
      <div className="compte-principal">
        {onSubmit ? (
          <form className="loginpanel" onSubmit={onSubmit} noValidate={false}>
            {contenu}
          </form>
        ) : (
          <div className="loginpanel">{contenu}</div>
        )}
      </div>
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
