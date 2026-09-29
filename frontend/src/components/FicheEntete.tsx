/**
 * Haut de fiche commun aux vues Enseignant, TD / TP, Cours et Salle
 * (refonte v2 du 29/09/2026, cf. docs/DESIGN.md « Gabarit de page ») :
 *
 *   [← Annuaire] [Enseignant ▾ Kyllian Bresson]            [actions de partage]
 *   Kyllian Bresson
 *   KBR · mail · 19,5 h en semaine 6 · 247,5 h au semestre · 6 matières
 *
 * Tout à plat, sans carte : la barre d'outils dit ce qu'on regarde et ce
 * qu'on peut en faire, le bandeau d'identité le nomme une seule fois (la
 * barre supérieure porte déjà le nom de la vue).
 */

import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

interface FicheOutilsProps {
  /** Libellé du sélecteur (« Enseignant », « Salle »…) — aussi son nom
   *  accessible. */
  libelle: string;
  valeur: string;
  options: { value: string; label: string }[];
  onChoisir: (valeur: string) => void;
  onAnnuaire: () => void;
  /** Actions à droite (partage, liens…). */
  actions?: ReactNode;
}

export function FicheOutils({ libelle, valeur, options, onChoisir, onAnnuaire, actions }: FicheOutilsProps) {
  return (
    <div className="page-outils fiche-outils">
      <button type="button" className="btn fiche-retour" onClick={onAnnuaire}>
        <ArrowLeft size={16} aria-hidden="true" />
        Retour à l'annuaire
      </button>
      <label className="fiche-choix">
        <span>{libelle}</span>
        <select value={valeur} onChange={(e) => onChoisir(e.target.value)}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {actions && <div className="page-outils-actions">{actions}</div>}
    </div>
  );
}

interface FicheIdentiteProps {
  titre: ReactNode;
  /** Faits de la fiche, chacun un élément de la ligne. */
  faits: ReactNode[];
}

export function FicheIdentite({ titre, faits }: FicheIdentiteProps) {
  return (
    <div className="page-identite fiche-identite">
      <h2>{titre}</h2>
      <p className="page-identite-faits">
        {faits.filter(Boolean).map((f, i) => (
          <span key={i} className="fiche-fait">
            {f}
          </span>
        ))}
      </p>
    </div>
  );
}
