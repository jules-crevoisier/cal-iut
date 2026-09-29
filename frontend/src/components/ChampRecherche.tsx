/**
 * Champ de recherche / filtre partagé (annuaires, À traiter, Tâches,
 * Référence, Comptes, Contraintes) : loupe à gauche, raccourci clavier
 * éventuel dans un `<kbd>` à droite (comme « Ctrl K » de la navigation) —
 * jamais écrit dans le texte d'exemple. Échap vide le champ.
 *
 * `className` va sur l'enveloppe : c'est elle, l'élément de la barre
 * d'outils (largeur, `flex`), le champ en prend toute la largeur.
 */

import { Search } from "lucide-react";
import { forwardRef } from "react";

import "./ChampRecherche.css";

interface ChampRechercheProps {
  valeur: string;
  onChange: (v: string) => void;
  /** Nom accessible du champ. */
  libelle: string;
  placeholder: string;
  /** Touche qui place le curseur dans le champ (gérée par l'écran). */
  raccourci?: string;
  className?: string;
}

export const ChampRecherche = forwardRef<HTMLInputElement, ChampRechercheProps>(function ChampRecherche(
  { valeur, onChange, libelle, placeholder, raccourci, className },
  ref,
) {
  return (
    <span className={`champ-recherche${raccourci ? " avec-raccourci" : ""}${className ? ` ${className}` : ""}`}>
      <Search size={16} aria-hidden="true" className="champ-recherche-loupe" />
      <input
        ref={ref}
        type="search"
        value={valeur}
        onChange={(e) => onChange(e.target.value)}
        aria-label={libelle}
        aria-keyshortcuts={raccourci}
        placeholder={placeholder}
        // Échap vide le champ : on revient à la liste complète sans souris.
        onKeyDown={(e) => {
          if (e.key === "Escape" && valeur) {
            e.preventDefault();
            onChange("");
          }
        }}
      />
      {raccourci && (
        <kbd className="champ-recherche-kbd" aria-hidden="true">
          {raccourci}
        </kbd>
      )}
    </span>
  );
});
