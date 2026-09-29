/**
 * Tuile chiffrée — le « sommaire en tête » des écrans qui ont des compteurs
 * (refonte v2 du 29/09/2026, cf. docs/DESIGN.md « Gabarit de page »).
 *
 * Née sur l'Accueil ; partagée depuis pour que À traiter, Contraintes,
 * Celcat et Comptes parlent le même langage : un libellé, un grand nombre,
 * une ligne d'explication et, si la tuile mène quelque part, l'action en
 * lien. L'état (`ton`) ne colore que le chiffre ; le mot, lui, est dans le
 * libellé ou le détail — jamais la couleur seule.
 *
 * Avec `onClick`, la tuile est un bouton (et `actif` en fait un filtre
 * enfoncé, `aria-pressed`) ; sans, c'est un simple bloc de lecture.
 */

import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";

import "./Tuile.css";

export type TonTuile = "good" | "warn" | "bad";

export interface TuileProps {
  libelle: ReactNode;
  valeur: ReactNode;
  detail?: ReactNode;
  ton?: TonTuile;
  onClick?: () => void;
  /** Libellé du lien en pied de tuile (« Voir », « Placer »…). */
  action?: string;
  /** Tuile utilisée comme filtre : enfoncée quand le filtre est appliqué. */
  actif?: boolean;
  title?: string;
  /** Valeur « vide » (0, rien à signaler). Même dessin qu'une autre valeur
   *  (chiffre noir, cf. docs/DESIGN.md) : seul un `ton` colore le chiffre ;
   *  la classe `is-nul` reste pour les tests et les styles d'écran. */
  nul?: boolean;
}

export function Tuile({ libelle, valeur, detail, ton, onClick, action, actif, title, nul }: TuileProps) {
  const classe = ["tuile", ton ? `is-${ton}` : "", nul ? "is-nul" : "", actif ? "is-actif" : "", onClick ? "is-cliquable" : ""]
    .filter(Boolean)
    .join(" ");
  const contenu = (
    <>
      <span className="tuile-libelle">{libelle}</span>
      <span className="tuile-valeur">{valeur}</span>
      {detail !== undefined && detail !== null && <span className="tuile-detail">{detail}</span>}
      {action && (
        <span className="tuile-action">
          {action} <ArrowRight size={14} aria-hidden="true" />
        </span>
      )}
    </>
  );
  if (!onClick) {
    return (
      <div className={classe} title={title}>
        {contenu}
      </div>
    );
  }
  return (
    <button type="button" className={classe} onClick={onClick} title={title} aria-pressed={actif === undefined ? undefined : actif}>
      {contenu}
    </button>
  );
}

/** Rangée de tuiles : autant de colonnes que la largeur en permet. */
export function Tuiles({
  children,
  label,
  className = "",
  testId,
}: {
  children: ReactNode;
  label: string;
  className?: string;
  testId?: string;
}) {
  return (
    <section className={`tuiles ${className}`.trim()} aria-label={label} data-testid={testId}>
      {children}
    </section>
  );
}
