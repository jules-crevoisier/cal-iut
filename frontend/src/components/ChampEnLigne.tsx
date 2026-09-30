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
 *
 * Mode « modifier » (29/09/2026, corriger une valeur déjà présente) : au
 * repos, la valeur (`valeurAffichee`) suivie d'un petit crayon — discret,
 * révélé au survol de la ligne, toujours visible au focus clavier —, puis le
 * même champ en ligne, prérempli.
 */

import { Pencil } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

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
  /** « ajouter » (pastille, défaut) ou « modifier » (crayon après la valeur). */
  mode?: "ajouter" | "modifier";
  /** Mode « modifier » : la valeur actuelle, telle que l'écran l'affiche. */
  valeurAffichee?: ReactNode;
  /** Mode « modifier » : ce qui suit le crayon (marque « modifiée »). */
  apres?: ReactNode;
  /** Valeurs proposées sous le champ libre (`<datalist>`) — codes relevés
   *  dans Celcat, par exemple (onglet « Codes Celcat », 30/09/2026). */
  suggestions?: string[];
  /** Texte visible du bouton « Enregistrer ». */
  libelleEnregistrer?: string;
  /** Classe du bouton d'ouverture en mode « ajouter » (défaut : la
   *  pastille « manquant »). */
  classeBouton?: string;
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
  mode = "ajouter",
  valeurAffichee,
  apres,
  suggestions,
  libelleEnregistrer = "Enregistrer",
  classeBouton = "pill dot warn champ-ajouter",
}: ChampEnLigneProps) {
  const [etat, setEtat] = useState<Etat>("repos");
  // Mode « modifier » : l'écran a rechargé la valeur enregistrée — retour
  // au repos (crayon de nouveau disponible), le « Enregistré » restant affiché.
  const [vientDEnregistrer, setVientDEnregistrer] = useState(false);
  const valeurVue = useRef(valeurInitiale);
  const [valeur, setValeur] = useState(valeurInitiale || options?.[0]?.value || "");
  const [erreur, setErreur] = useState<string | null>(null);
  const [enregistree, setEnregistree] = useState("");
  const bouton = useRef<HTMLButtonElement>(null);
  const champ = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const idErreur = useId();
  const idListe = useId();
  const rendreFocus = useRef(false);

  useEffect(() => {
    if (mode === "modifier" && etat === "fait" && valeurInitiale !== valeurVue.current) {
      setVientDEnregistrer(true);
      setEtat("repos");
    }
    valeurVue.current = valeurInitiale;
  }, [mode, etat, valeurInitiale]);

  useEffect(() => {
    if (etat === "edition") champ.current?.focus();
    if (etat === "repos" && rendreFocus.current) {
      rendreFocus.current = false;
      bouton.current?.focus();
    }
  }, [etat]);

  const ouvrir = () => {
    setValeur(valeurInitiale || options?.[0]?.value || "");
    setErreur(null);
    setVientDEnregistrer(false);
    setEtat("edition");
  };

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
      {etat === "repos" && mode === "ajouter" && (
        <button
          ref={bouton}
          type="button"
          className={classeBouton}
          aria-label={`${libelleBouton} — ${libelleChamp}`}
          title={`${libelleChamp} : à compléter`}
          onClick={ouvrir}
        >
          {libelleBouton}
        </button>
      )}
      {etat === "repos" && mode === "modifier" && (
        <span className="valeur-modifiable">
          {valeurAffichee}
          <button
            ref={bouton}
            type="button"
            className="btn-modifier"
            aria-label={`Modifier — ${libelleChamp}`}
            title="Modifier"
            onClick={ouvrir}
          >
            <Pencil size={13} aria-hidden="true" />
          </button>
          {apres}
          {vientDEnregistrer && <span className="pill dot good">Enregistré</span>}
        </span>
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
              list={suggestions && suggestions.length > 0 ? idListe : undefined}
              onChange={(e) => {
                setValeur(e.target.value);
                if (erreur) setErreur(null);
              }}
              aria-invalid={erreur ? true : undefined}
              aria-describedby={erreur ? idErreur : undefined}
            />
          )}
          <button type="submit" className="btn btn--primary btn--sm" disabled={etat === "envoi"}>
            {etat === "envoi" ? "Enregistrement…" : libelleEnregistrer}
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={annuler} disabled={etat === "envoi"}>
            Annuler
          </button>
          {suggestions && suggestions.length > 0 && (
            <datalist id={idListe}>
              {suggestions.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          )}
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
          {/* Mode « modifier » : on peut reprendre tout de suite, et la
              marque reste visible (même valeur ressaisie : rien ne
              rechargerait le composant). */}
          {mode === "modifier" && (
            <button
              ref={bouton}
              type="button"
              className="btn-modifier"
              aria-label={`Modifier — ${libelleChamp}`}
              title="Modifier"
              onClick={ouvrir}
            >
              <Pencil size={13} aria-hidden="true" />
            </button>
          )}
          {mode === "modifier" && apres}
          <span className="pill dot good">Enregistré</span>
        </span>
      )}
      <span className="sr-only" aria-live="polite">
        {annonce}
      </span>
    </span>
  );
}
