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
import { mailtoForTeacher } from "../utils/mailto";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";

interface EnseignantViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
}

function displayIndexForSolverWeek(payload: AppPayload, solverWeek: number | null): number {
  if (solverWeek === null) return 0;
  const idx = payload.weekRows.findIndex((w) => w.weekIndex === solverWeek);
  return idx >= 0 ? idx : 0;
}

export function EnseignantView({ payload, route, setRoute, readOnly = false }: EnseignantViewProps) {
  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );
  const [code, setCode] = useState(route.prof || teacherCodes[0] || "");
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, route.sem));
  const [mobileDay, setMobileDay] = useState(todayIndex());
  const narrow = useNarrowScreen();

  useEffect(() => {
    if (route.prof && route.prof !== code) setCode(route.prof);
    if (route.sem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, route.sem));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.prof, route.sem]);

  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.te.includes(code))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, code],
  );
  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const rowsThisWeek = solverWeek === null ? [] : allItems.filter((r) => r.w === solverWeek);

  const countByWeek = new Map<number, number>();
  for (const it of allItems) countByWeek.set(it.w, (countByWeek.get(it.w) ?? 0) + 1);

  const info = payload.teachers.find((t) => t.code === code);

  const handleChangeTeacher = (next: string) => {
    setCode(next);
    setRoute({ vue: "prof", prof: next });
  };

  const personalLink = buildLink({ vue: "prof", prof: code, mode: "prof" });

  return (
    <section className="view">
      {!readOnly && (
        <div className="panel controls">
          <label>
            Enseignant
            <select value={code} onChange={(e) => handleChangeTeacher(e.target.value)}>
              {teacherCodes.map((c) => (
                <option key={c} value={c}>
                  {payload.teacherLabels[c]}
                  {payload.teachers.find((t) => t.code === c)?.hasConstraint ? " •" : ""}
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
        onCopyLink={() => personalLink}
        onDownloadIcs={() =>
          downloadIcs(allItems, payload.teacherLabels[code] ?? code, code, payload.groupLabels, payload.teacherLabels)
        }
        extra={
          <a
            className="btn btn--ghost btn--sm"
            href={mailtoForTeacher(payload, code, allItems, personalLink)}
            title={payload.teacherEmails[code] || "Adresse inconnue — à compléter dans data/config/teacher_contacts.yaml"}
          >
            Écrire{payload.teacherEmails[code] ? "" : " ⚠"}
          </a>
        }
      />

      {info && (() => {
        // Compromis MOU (encadrement SAE ce jour-là, `--no-sae-supervisor-hard`)
        // distingué d'une vraie indisponibilité déclarée non respectée —
        // sinon un enseignant référent SAE ressort à tort comme "en échec"
        // au même titre qu'un enseignant dont on a réellement ignoré les
        // disponibilités (retour utilisateur 11/08/2026, cf. docs/DATA.md §59).
        const saeCount = info.violations.filter((v) => v.reason === "sae_supervision").length;
        const declaredCount = info.violations.length - saeCount;
        const anyReal = declaredCount > 0;
        return (
          <div className={`callout ${!info.hasConstraint ? "" : anyReal ? "fail" : info.violations.length ? "warn" : "pass"}`}>
            {!info.hasConstraint ? (
              <span>Aucune contrainte déclarée dans le fichier CONTRAINTES ENSEIGNANTS pour {info.name}.</span>
            ) : info.violations.length === 0 ? (
              <span>
                <span className="icon">✓</span> Contrainte respectée sur les {info.nPlaced} séance(s) placée(s) pour{" "}
                {info.name}.
              </span>
            ) : (
              <span>
                <span className="icon">{anyReal ? "!" : "i"}</span>{" "}
                {declaredCount > 0 && <>{declaredCount} vraie(s) violation(s) de disponibilité déclarée</>}
                {declaredCount > 0 && saeCount > 0 && " + "}
                {saeCount > 0 && <>{saeCount} compromis accepté(s) (encadrement SAE ce jour-là)</>}
                {" "}sur les {info.nPlaced} séance(s) placée(s) pour {info.name}.
              </span>
            )}
          </div>
        );
      })()}

      {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

      <div className="layout">
        <div className="panel">
          <h3>
            {payload.teacherLabels[code] ?? code} —{" "}
            {payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
          </h3>
          {solverWeek === null ? (
            <p className="muted">Semaine bloquée (vacances/fermeture).</p>
          ) : (
            <SessionGrid payload={payload} rows={rowsThisWeek} week={solverWeek} onlyDay={narrow ? mobileDay : null} />
          )}
        </div>

        {info && (info.rawIndisponibilites || info.rawDisponibilites || info.rawContraintes || info.violations.length > 0) && (
          <div className="panel">
            <h3>Sa contrainte, telle que déclarée</h3>
            {info.rawIndisponibilites && (
              <>
                <div className="raw-label">Indisponibilités déclarées</div>
                <div className="raw">{info.rawIndisponibilites}</div>
              </>
            )}
            {info.rawDisponibilites && (
              <>
                <div className="raw-label">Disponibilités déclarées</div>
                <div className="raw">{info.rawDisponibilites}</div>
              </>
            )}
            {info.rawContraintes && (
              <>
                <div className="raw-label">Contraintes / progression</div>
                <div className="raw">{info.rawContraintes}</div>
              </>
            )}
            {info.violations.length > 0 && (
              <>
                <div className="raw-label">Violations détectées</div>
                <div className="slotlist">
                  {info.violations.map((v, i) => (
                    <span
                      key={i}
                      className={`slotchip${v.reason === "sae_supervision" ? " sae" : ""}`}
                      title={v.reason === "sae_supervision" ? "Compromis accepté : encadrement SAE ce jour-là (objectif mou)" : "Indisponibilité déclarée non respectée"}
                    >
                      {v.course_code} —{" "}
                      {v.date ?? `sem.${(v.week ?? 0) + 1} ${DAY_LABELS[v.day ?? 0]} ${SLOT_TIMES[v.slot ?? 0]?.label ?? ""}`}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Toutes ses interventions du semestre</h3>
        <SemesterAgenda payload={payload} items={allItems} />
      </div>
    </section>
  );
}
