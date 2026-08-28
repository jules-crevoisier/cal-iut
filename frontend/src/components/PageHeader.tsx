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
  const [cls, label] = STATUS_MAP[payload.status ?? ""] ?? ["bad", payload.status ?? "—"];

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
      <span className={`pill lg dot ${cls}`}>{label}</span>
    </header>
  );
}
