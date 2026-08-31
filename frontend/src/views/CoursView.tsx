/**
 * Fiche matière — toutes les entrées catalogue de ce code + grille de la semaine.
 * La recherche atterrit ici au lieu d'une Vue Semaine non filtrée.
 */

import { useEffect, useMemo, useState } from "react";

import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { DayStrip, todayIndex } from "../components/DayStrip";
import { SessionGrid } from "../components/SessionGrid";
import { WeekBar } from "../components/WeekBar";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates } from "../utils/ics";
import { displayIndexForSolverWeek } from "../utils/weekDisplay";

interface CoursViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  onOpenSearch?: () => void;
}

export function CoursView({ payload, route, setRoute, onOpenSearch }: CoursViewProps) {
  const code = route.cours;
  const entrees = payload.courses.filter((c) => c.code === code);
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, route.sem));
  const [mobileDay, setMobileDay] = useState(todayIndex());
  const narrow = useNarrowScreen();

  useEffect(() => {
    if (route.sem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, route.sem));
  }, [payload, route.sem]);

  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.c === code)),
    [payload, code],
  );
  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const rowsThisWeek = solverWeek === null ? [] : allItems.filter((r) => r.w === solverWeek);

  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + (it.dur || 1) * 1.5);

  if (!code || entrees.length === 0) {
    return <FicheIntrouvable libelle="Matière" id={code || "?"} onOpenSearch={onOpenSearch} />;
  }

  const nom = entrees[0]?.name ?? code;
  const teachers = [...new Set(entrees.flatMap((e) => e.teachers))];
  const groupes = [...new Set(allItems.flatMap((r) => r.g))];
  const salles = [...new Set(allItems.map((r) => r.r).filter(Boolean))];
  const manquantes = (payload.seancesNonPlacees ?? []).filter((s) => s.code === code);
  const nPlaced = entrees.reduce((n, e) => n + e.nPlaced, 0);

  return (
    <section className="view">
      <div className="panel">
        <h3>
          {code} — {nom}
        </h3>
        <p className="muted">
          {nPlaced} séance(s) placée(s)
          {manquantes.length > 0 ? ` · ${manquantes.length} non placée(s)` : ""}
        </p>
        <div className="ref-table-wrap">
          <table className="ref">
            <thead>
              <tr>
                <th>Parcours</th>
                <th>Semestre</th>
                <th>CM</th>
                <th>TD</th>
                <th>TP</th>
                <th>Éval</th>
                <th>Placées</th>
                <th>Progression</th>
              </tr>
            </thead>
            <tbody>
              {entrees.map((e) => (
                <tr key={`${e.code}-${e.parcours}`}>
                  <td>{e.parcours || "—"}</td>
                  <td>{e.semestre}</td>
                  <td>{e.nCM}</td>
                  <td>{e.nTD}</td>
                  <td>{e.nTP}</td>
                  <td>{e.nEval}</td>
                  <td>{e.nPlaced}</td>
                  <td>{e.progressionDefined ? "oui" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {teachers.length > 0 && (
          <>
            <div className="raw-label">Enseignants</div>
            <p>
              {teachers.map((t, i) => (
                <span key={t}>
                  {i > 0 ? " · " : null}
                  <button type="button" className="linklike" onClick={() => setRoute({ vue: "prof", prof: t })}>
                    {payload.teacherLabels[t] ?? t}
                  </button>
                </span>
              ))}
            </p>
          </>
        )}
        {groupes.length > 0 && (
          <>
            <div className="raw-label">Groupes</div>
            <p>{groupes.map((g) => payload.groupLabels[g] ?? g).join(" · ")}</p>
          </>
        )}
        {salles.length > 0 && (
          <>
            <div className="raw-label">Salles utilisées</div>
            <p>{salles.join(" · ")}</p>
          </>
        )}
        {entrees.some((e) => e.ordonnancement.length > 0) && (
          <>
            <div className="raw-label">Ordonnancement</div>
            <ul>
              {entrees.flatMap((e) =>
                e.ordonnancement.map((o, i) => (
                  <li key={`${e.parcours}-${i}`}>
                    {e.parcours}: {o.position} → {o.target}
                  </li>
                )),
              )}
            </ul>
          </>
        )}
        {manquantes.length > 0 && (
          <>
            <div className="raw-label">Non placées</div>
            <ul>
              {manquantes.map((s) => (
                <li key={s.id}>
                  {s.type} · {s.groupes.join(", ")} · {s.profs.join(", ")}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="panel controls">
        <div className="field weekfield">
          <WeekBar
            weekRows={payload.weekRows}
            countByWeekIndex={hoursByWeek}
            selected={displayWeek}
            onSelect={setDisplayWeek}
            unit="heures"
          />
        </div>
      </div>

      {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

      <div className="panel">
        <h3>{payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}</h3>
        {solverWeek === null ? (
          <p className="muted">Semaine bloquée (vacances/fermeture).</p>
        ) : (
          <SessionGrid payload={payload} rows={rowsThisWeek} week={solverWeek} onlyDay={narrow ? mobileDay : null} showPromo />
        )}
      </div>
    </section>
  );
}
