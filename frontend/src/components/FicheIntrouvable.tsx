/**
 * Fiche admin : l'id demandé n'existe pas dans le payload (typo, lien périmé).
 * Le bouton rouvre la recherche globale — seul moyen de retomber sur une entité réelle.
 */

interface FicheIntrouvableProps {
  libelle: string;
  id: string;
  onOpenSearch?: () => void;
}

export function FicheIntrouvable({ libelle, id, onOpenSearch }: FicheIntrouvableProps) {
  return (
    <section className="view">
      <div className="panel">
        <p>
          {libelle} « {id} » introuvable.
        </p>
        <button type="button" className="btn" onClick={() => onOpenSearch?.()}>
          Ouvrir la recherche
        </button>
      </div>
    </section>
  );
}
