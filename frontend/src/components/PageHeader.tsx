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
  const firstFutureWeek = payload.weekStatus.find((w) => w.status === "future");
  const activeWeekLabel = firstFutureWeek
    ? `Prochaine semaine modifiable : ${payload.weekRows[firstFutureWeek.week]?.label ?? `Semaine ${firstFutureWeek.week + 1}`}`
    : "";

  const q = payload.quality;
  const nWeeks = payload.weekRows.length;
  const blockedWeekCount = payload.weekRows.filter((w) => w.blocked).length;
  const matieres = new Set(payload.rows.map((r) => r.c)).size;

  const stats: [string, string | number, string?][] = [
    ["Séances placées", payload.rows.length.toLocaleString("fr-FR")],
    ["Matières", matieres],
    ["Semaines affichées", nWeeks + (blockedWeekCount ? ` (dont ${blockedWeekCount} bloquée(s))` : "")],
    ["Trous détectés", q?.total_gaps ?? "—"],
    ["Jours isolés", q?.isolated_days ?? "—"],
    ["Score objectif", `${(payload.objective ?? 0).toLocaleString("fr-FR")} `, "plus bas = meilleur"],
  ];

  return (
    <>
      <header className="top">
        <div className="titles">
          <h1>Planning généré</h1>
          <p>Sortie du solveur CP-SAT cal-iut.</p>
        </div>
        {activeWeekLabel && <span className="pill">{activeWeekLabel}</span>}
        <span className={`pill lg dot ${cls}`}>{label}</span>
      </header>

      <section className="stats">
        {stats.map(([l, v, sub]) => (
          <div className="stat" key={l}>
            <span className="label">{l}</span>
            <span className="value mono">
              {v}
              {sub && <small> {sub}</small>}
            </span>
          </div>
        ))}
      </section>
    </>
  );
}
