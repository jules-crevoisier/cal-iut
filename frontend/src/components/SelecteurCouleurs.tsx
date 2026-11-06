/**
 * Sélecteur « Couleurs par type / par matière », commun à la Vue semaine
 * (`Toolbar`) et à la Vue Promo : un seul composant, un seul vocabulaire
 * (mêmes libellés que `ReglageCouleurs` dans `App.tsx`).
 */
interface SelecteurCouleursProps {
  parMatiere: boolean;
  onChange: (parMatiere: boolean) => void;
}

export function SelecteurCouleurs({ parMatiere, onChange }: SelecteurCouleursProps) {
  return (
    <select
      aria-label="Couleurs"
      className="semaine-couleurs"
      value={parMatiere ? "matiere" : "type"}
      onChange={(e) => onChange(e.target.value === "matiere")}
    >
      <option value="type">Couleurs par type</option>
      <option value="matiere">Couleurs par matière</option>
    </select>
  );
}
