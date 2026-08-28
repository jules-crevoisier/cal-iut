/**
 * En-tête de page (titre + statut + 6 statistiques) — portage de la section
 * `<header class="top">` + `<section class="stats">` de
 * `export/templates/timetable.html`, visible sur TOUS les onglets, jamais
 * porté côté React (retour utilisateur 11/08/2026 : "je vois toujours pas la
 * même interface que le html" — la palette/typo avaient été corrigées, mais
 * toute cette section n'existait tout simplement pas encore côté React, cf.
 * docs/DATA.md). Mêmes données que le HTML (`payload.status`/`objective`/
 * `quality`/`rows`/`weekStatus`), rien de recalculé ni deviné ici.
 */

import type { AppPayload } from "../types/app";

const STATUS_MAP: Record<string, [string, string]> = {
  OPTIMAL: ["good", "Optimal"],
  FEASIBLE: ["warn", "Faisable (limite de temps atteinte)"],
  INFEASIBLE: ["bad", "Infaisable"],
};

interface PageHeaderProps {
  payload: AppPayload;
}

export function PageHeader({ payload }: PageHeaderProps) {
  // Seuls les VRAIS verdicts du solveur méritent une pastille. Le serveur
  // renvoie aussi `"CACHED"` quand le planning vient de la base plutôt que
  // d'une résolution fraîche (`api/main.py`) : ce n'est pas un verdict, et
  // il s'affichait tel quel — jargon interne, en rouge « échec » de surcroît
  // puisqu'absent de `STATUS_MAP` (retour utilisateur 28/08/2026 : « enlève
  // moi ça CACHED »). Tout statut non reconnu masque donc la pastille au
  // lieu d'exposer une valeur brute.
  const statut = STATUS_MAP[payload.status ?? ""];

  // La pastille "Prochaine semaine modifiable" et les 6 statistiques
  // (séances/matières/semaines/trous/jours isolés/score) ont été retirées
  // (retour utilisateur 27/08/2026 : « on peut aussi enlever les séance
  // matiere semaine trou etc le cache prochaine semaine modifiable etc »)
  // — pur affichage, aucune donnée ni action perdue ; `payload.quality`,
  // `payload.rows`, `payload.weekStatus` etc. restent utilisés ailleurs
  // (QualityPanel, TodoView...), rien n'a changé côté calcul.
  return (
    <header className="top">
      <div className="titles">
        <h1>Planning généré</h1>
        <p>Sortie du solveur CP-SAT cal-iut.</p>
      </div>
      {statut && <span className={`pill lg dot ${statut[0]}`}>{statut[1]}</span>}
    </header>
  );
}
