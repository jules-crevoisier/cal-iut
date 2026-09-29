/**
 * Compléter une donnée manquante là où le manque se voit, en un geste
 * (29/09/2026, « il faut pouvoir ajouter l'info et l'enregistrer »).
 *
 *   [• Ajouter]  →  [ prenom.nom@univ-reims.fr ] [Enregistrer] [Annuler]
 *                →  prenom.nom@univ-reims.fr  • Enregistré
 *
 * - au repos, la pastille « manquant » devenue bouton (même dessin : point
 *   orange + mot), dont le nom accessible dit CE qu'on ajoute et À QUI ;
 * - Entrée enregistre, Échap annule (le focus revient sur « Ajouter ») ;
 * - l'erreur du serveur s'affiche sous le champ, qui reste ouvert avec la
 *   saisie — jamais d'alerte bloquante ;
 * - le succès reste visible (« Enregistré », annoncé par `aria-live`) le
 *   temps que l'écran se recharge avec la nouvelle valeur.
 */

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import "./ChampEnLigne.css";

export interface OptionChamp {
  value: string;
  label: string;
}

interface ChampEnLigneProps {
  /** Texte visible du bouton (« Ajouter », « Ajouter le mail »). */
  libelleBouton?: string;
  /** Nom accessible du bouton ET du champ : « Adresse mail de Kyllian Bresson ». */
  libelleChamp: string;
  type?: "email" | "text" | "number";
  /** Liste de choix : un `<select>` au lieu d'un champ libre. */
  options?: OptionChamp[];
  placeholder?: string;
  valeurInitiale?: string;
  /** Contrôle côté navigateur, avant tout appel : message d'erreur ou null. */
  valider?: (valeur: string) => string | null;
  /** Appelle l'API ; une erreur levée est affichée telle quelle. */
  onEnregistrer: (valeur: string) => Promise<unknown>;
  /** Largeur du champ en caractères. */
  taille?: number;
}

type Etat = "repos" | "edition" | "envoi" | "fait";

const RE_EMAIL = /^[^@\s<>(),;:"[\]]+@[^@\s<>(),;:"[\]]+\.[^@\s<>(),;:"[\].]{2,}$/;

/** Même règle que le serveur (`api/reference.py::normaliser_email`), pour un
 *  refus immédiat sans aller-retour ; le serveur reste juge. */
export function validerEmail(valeur: string): string | null {
  const v = valeur.trim().toLowerCase();
  if (!v) return "Saisissez une adresse.";
  if (!RE_EMAIL.test(v) || v.includes("..")) return "Adresse invalide (forme attendue : prenom.nom@univ-reims.fr).";
  return null;
}

export function ChampEnLigne({
  libelleBouton = "Ajouter",
  libelleChamp,
  type = "text",
  options,
  placeholder,
  valeurInitiale = "",
  valider,
  onEnregistrer,
  taille,
}: ChampEnLigneProps) {
  const [etat, setEtat] = useState<Etat>("repos");
  const [valeur, setValeur] = useState(valeurInitiale || options?.[0]?.value || "");
  const [erreur, setErreur] = useState<string | null>(null);
  const [enregistree, setEnregistree] = useState("");
  const bouton = useRef<HTMLButtonElement>(null);
  const champ = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const idErreur = useId();
  const rendreFocus = useRef(false);

  useEffect(() => {
    if (etat === "edition") champ.current?.focus();
    if (etat === "repos" && rendreFocus.current) {
      rendreFocus.current = false;
      bouton.current?.focus();
    }
  }, [etat]);

  const annuler = () => {
    setErreur(null);
    setValeur(valeurInitiale || options?.[0]?.value || "");
    rendreFocus.current = true;
    setEtat("repos");
  };

  const soumettre = async (e: FormEvent) => {
    e.preventDefault();
    const texte = type === "email" ? valeur.trim().toLowerCase() : valeur.trim();
    const refus = valider ? valider(texte) : texte ? null : "Le champ est vide.";
    if (refus) {
      setErreur(refus);
      champ.current?.focus();
      return;
    }
    setEtat("envoi");
    setErreur(null);
    try {
      await onEnregistrer(texte);
      setEnregistree(options?.find((o) => o.value === texte)?.label ?? texte);
      setEtat("fait");
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Enregistrement impossible.");
      setEtat("edition");
    }
  };

  const touche = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      annuler();
    }
  };

  const annonce = etat === "fait" ? `Enregistré. ${libelleChamp} : ${enregistree}` : "";

  return (
    <span className="champ-en-ligne-hote" data-pas-ouvrir="">
      {etat === "repos" && (
        <button
          ref={bouton}
          type="button"
          className="pill dot warn champ-ajouter"
          aria-label={`${libelleBouton} — ${libelleChamp}`}
          title={`${libelleChamp} : à compléter`}
          onClick={() => setEtat("edition")}
        >
          {libelleBouton}
        </button>
      )}
      {(etat === "edition" || etat === "envoi") && (
        <form className="champ-en-ligne" onSubmit={(e) => void soumettre(e)} onKeyDown={touche} noValidate>
          {options ? (
            <select
              ref={champ}
              aria-label={libelleChamp}
              value={valeur}
              disabled={etat === "envoi"}
              onChange={(e) => setValeur(e.target.value)}
              aria-invalid={erreur ? true : undefined}
              aria-describedby={erreur ? idErreur : undefined}
            >
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : (
            <input
              ref={champ}
              type={type}
              inputMode={type === "number" ? "numeric" : type === "email" ? "email" : undefined}
              aria-label={libelleChamp}
              placeholder={placeholder}
              value={valeur}
              size={taille}
              disabled={etat === "envoi"}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => {
                setValeur(e.target.value);
                if (erreur) setErreur(null);
              }}
              aria-invalid={erreur ? true : undefined}
              aria-describedby={erreur ? idErreur : undefined}
            />
          )}
          <button type="submit" className="btn btn--primary btn--sm" disabled={etat === "envoi"}>
            {etat === "envoi" ? "Enregistrement…" : "Enregistrer"}
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={annuler} disabled={etat === "envoi"}>
            Annuler
          </button>
          {erreur && (
            <span id={idErreur} className="champ-en-ligne-erreur" role="alert">
              {erreur}
            </span>
          )}
        </form>
      )}
      {etat === "fait" && (
        <span className="champ-en-ligne-fait">
          <span className="champ-en-ligne-valeur">{enregistree}</span>
          <span className="pill dot good">Enregistré</span>
        </span>
      )}
      <span className="sr-only" aria-live="polite">
        {annonce}
      </span>
    </span>
  );
}
