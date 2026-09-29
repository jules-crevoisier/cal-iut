/**
 * Fiche : l'id demandé n'existe pas dans le planning (typo, lien périmé).
 * Le bouton rouvre la recherche globale — seul moyen de retomber sur une
 * entité réelle.
 */

interface FicheIntrouvableProps {
  libelle: string;
  id: string;
  onOpenSearch?: () => void;
}

export function FicheIntrouvable({ libelle, id, onOpenSearch }: FicheIntrouvableProps) {
  return (
    <section className="view">
      <div className="empty-state" role="status">
        <p>
          <strong>
            {libelle} « {id} » introuvable.
          </strong>
        </p>
        <p className="muted">Le lien est peut-être ancien, ou le code mal recopié.</p>
        <p>
          <button type="button" className="btn btn--primary" onClick={() => onOpenSearch?.()}>
            Ouvrir la recherche
          </button>{" "}
          <span className="muted">(Ctrl+K)</span>
        </p>
      </div>
    </section>
  );
}
