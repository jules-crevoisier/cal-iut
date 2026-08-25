import { useEffect, useMemo, useState } from "react";

import { DayStrip, todayIndex } from "../components/DayStrip";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { SessionGrid } from "../components/SessionGrid";
import { ShareBar } from "../components/ShareBar";
import { WeekBar } from "../components/WeekBar";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { downloadIcs, sessionsWithDates } from "../utils/ics";

interface GroupeViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
}

/** Index d'affichage (dans `weekRows`, vacances incluses) le plus proche
 * d'une semaine SOLVEUR donnée — sert à faire pointer la `WeekBar` au bon
 * endroit quand on arrive depuis un lien qui ne connaît que l'index solveur
 * (recherche, panneau « à traiter »). */
function displayIndexForSolverWeek(payload: AppPayload, solverWeek: number | null): number {
  if (solverWeek === null) return 0;
  const idx = payload.weekRows.findIndex((w) => w.weekIndex === solverWeek);
  return idx >= 0 ? idx : 0;
}

export function GroupeView({ payload, route, setRoute, readOnly = false }: GroupeViewProps) {
  const groupIds = useMemo(
    () =>
      Object.keys(payload.groupLabels).sort((a, b) =>
        (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr"),
      ),
    [payload.groupLabels],
  );
  const [groupId, setGroupId] = useState(route.groupe || payload.defaultGroup || groupIds[0] || "");
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, route.sem));
  const [mobileDay, setMobileDay] = useState(todayIndex());
  const narrow = useNarrowScreen();

  // Resynchronise depuis un lien externe (recherche, « à traiter ») qui ne
  // touche que la route sans démonter cette vue.
  useEffect(() => {
    if (route.groupe && route.groupe !== groupId) setGroupId(route.groupe);
    if (route.sem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, route.sem));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.groupe, route.sem]);

  const cohort = new Set(payload.groupCohort[groupId] ?? [groupId]);
  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.g.some((g) => cohort.has(g)))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, groupId],
  );
  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const rowsThisWeek = solverWeek === null ? [] : allItems.filter((r) => r.w === solverWeek);

  const countByWeek = new Map<number, number>();
  for (const it of allItems) countByWeek.set(it.w, (countByWeek.get(it.w) ?? 0) + 1);

  const tpPair = payload.groupTpPair[groupId];
  const parcours = payload.groupParcours[groupId] ?? "";

  const handleChangeGroup = (gid: string) => {
    setGroupId(gid);
    setRoute({ vue: "groupe", groupe: gid });
  };

  return (
    <section className="view">
      {!readOnly && (
        <div className="panel controls">
          <label>
            Groupe étudiant
            <select value={groupId} onChange={(e) => handleChangeGroup(e.target.value)}>
              {groupIds.map((gid) => (
                <option key={gid} value={gid}>
                  {payload.groupLabels[gid]}
                </option>
              ))}
            </select>
          </label>
          <div className="field weekfield">
            <WeekBar
              weekRows={payload.weekRows}
              countByWeekIndex={countByWeek}
              selected={displayWeek}
              onSelect={setDisplayWeek}
            />
          </div>
        </div>
      )}

      <ShareBar
        onCopyLink={() => buildLink({ vue: "groupe", groupe: groupId, mode: "groupe" })}
        onDownloadIcs={() =>
          downloadIcs(allItems, payload.groupLabels[groupId] ?? groupId, groupId, payload.groupLabels, payload.teacherLabels)
        }
      />

      {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

      <div className="panel">
        <h3>
          {payload.groupLabels[groupId] ?? groupId} —{" "}
          {payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
        </h3>
        {solverWeek === null ? (
          <p className="muted">Semaine bloquée (vacances/fermeture).</p>
        ) : (
          <SessionGrid
            payload={payload}
            rows={rowsThisWeek}
            week={solverWeek}
            parcours={parcours}
            showPac={!parcours.includes("FC")}
            split={tpPair}
            onlyDay={narrow ? mobileDay : null}
          />
        )}
      </div>

      <div className="panel">
        <h3>Toutes les séances du semestre</h3>
        <SemesterAgenda payload={payload} items={allItems} />
      </div>
    </section>
  );
}
