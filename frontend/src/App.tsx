import { useCallback, useEffect, useState } from "react";

import {
  applyFeedback,
  exportCsvUrl,
  exportJson,
  extractTeachers,
  fetchCorrections,
  fetchDiff,
  fetchFeedbackAnalysis,
  fetchMeta,
  fetchTimetable,
  ingest,
  solve,
} from "./api/client";
import { DiffPanel } from "./components/DiffPanel";
import { QualityPanel } from "./components/QualityPanel";
import { SessionPanel } from "./components/SessionPanel";
import { TdWeekGrid } from "./components/TdWeekGrid";
import { TimetableCalendar } from "./components/TimetableCalendar";
import { Toolbar } from "./components/Toolbar";
import type {
  DiffResponse,
  FeedbackAnalysis,
  GroupMeta,
  MetaResponse,
  Placement,
  Quality,
  RoomMeta,
  ViewMode,
  YearMeta,
} from "./types";
import { DEFAULT_YEARS, yearFromSemestre } from "./utils/years";

const DEFAULT_PARCOURS = "BUT1";
const DEFAULT_SEMESTRE = "S1";
// Plage d'affichage du sélecteur de semaine dans le Toolbar (UI uniquement) —
// l'horizon réel du solveur est calculé côté backend depuis le calendrier
// (cf. cal_iut.calendar.academic.default_horizon_weeks), pas fixé ici.
const MAX_WEEKS = 24;

export function App() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [status, setStatus] = useState<string>("—");
  const [correctionsCount, setCorrectionsCount] = useState(0);
  const [diff, setDiff] = useState<DiffResponse | null>(null);
  const [analysis, setAnalysis] = useState<FeedbackAnalysis | null>(null);

  const [year, setYear] = useState(1);
  const [parcours, setParcours] = useState(DEFAULT_PARCOURS);
  const [semestre, setSemestre] = useState(DEFAULT_SEMESTRE);
  const [displayWeek, setDisplayWeek] = useState(0);
  const [viewMode, setViewMode] = useState<ViewMode>("group");
  const [groupId, setGroupId] = useState("but1-td-ab");
  const [teacherCode, setTeacherCode] = useState("");
  const [roomId, setRoomId] = useState("");

  const [selected, setSelected] = useState<Placement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshMeta = useCallback(async () => {
    try {
      setMeta(await fetchMeta());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur meta");
    }
  }, []);

  const refreshDiff = useCallback(async () => {
    try {
      setDiff(await fetchDiff());
      setAnalysis(await fetchFeedbackAnalysis());
    } catch {
      /* no diff yet */
    }
  }, []);

  const refreshCorrections = useCallback(async () => {
    try {
      const c = await fetchCorrections();
      setCorrectionsCount(c.length);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  const loadTimetable = useCallback(async () => {
    try {
      const data = await fetchTimetable({
        group_id: viewMode === "group" && groupId ? groupId : undefined,
        teacher_code: viewMode === "teacher" && teacherCode ? teacherCode : undefined,
        room_id: viewMode === "room" && roomId ? roomId : undefined,
      });
      setPlacements(data.placements);
      setQuality(data.quality);
      setStatus(data.status);
      await refreshDiff();
      await refreshCorrections();
    } catch {
      /* no timetable */
    }
  }, [viewMode, groupId, teacherCode, roomId, refreshDiff, refreshCorrections]);

  useEffect(() => {
    void loadTimetable();
  }, [loadTimetable]);

  const handleIngest = async () => {
    setLoading(true);
    setError(null);
    try {
      await ingest(parcours, semestre);
      setNotice(`Données ${parcours} ${semestre} chargées`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur ingestion");
    } finally {
      setLoading(false);
    }
  };

  const handleSolve = async (regenerate = false) => {
    setLoading(true);
    setError(null);
    setNotice(regenerate ? "Régénération…" : "Génération…");
    try {
      await ingest(parcours, semestre);
      const data = await solve({
        parcours,
        semestre,
        optimize_gaps: false,
      });
      setPlacements(data.placements);
      setQuality(data.quality);
      setStatus(data.status);
      setNotice(`Planning généré — ${data.placements.length} séances`);
      await refreshDiff();
      await refreshCorrections();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur solveur");
    } finally {
      setLoading(false);
    }
  };

  const handlePlacementUpdated = (updated: Placement) => {
    setPlacements((prev) => prev.map((p) => (p.session_id === updated.session_id ? updated : p)));
    setSelected(updated);
    void refreshDiff();
    void refreshCorrections();
  };

  const handleApplyFeedback = async () => {
    setLoading(true);
    try {
      const result = await applyFeedback();
      setNotice(result.applied ? "Poids objectif mis à jour" : "Pas assez de corrections pour apprendre");
      setAnalysis(await fetchFeedbackAnalysis());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur feedback");
    } finally {
      setLoading(false);
    }
  };

  const handleExportCsv = () => {
    window.open(exportCsvUrl(), "_blank");
  };

  const handleExportJson = async () => {
    try {
      const data = await exportJson();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "emploi_du_temps.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur export");
    }
  };

  const teachers = extractTeachers(placements);
  const groups: GroupMeta[] = meta?.groups ?? [];
  const rooms: RoomMeta[] = meta?.rooms ?? [];
  const years: YearMeta[] = meta?.years?.length ? meta.years : DEFAULT_YEARS;
  const parcoursList = meta?.parcours.length ? meta.parcours : [DEFAULT_PARCOURS];
  const visiblePlacements = placements.filter((p) => p.week === displayWeek);
  const groupLabels = Object.fromEntries(groups.map((g) => [g.id, g.label]));

  const handleYearChange = (nextYear: number) => {
    setYear(nextYear);
    const yearMeta = years.find((y) => y.id === nextYear);
    const nextSemestres = yearMeta?.semestres ?? (nextYear === 1 ? ["S1", "S2"] : nextYear === 2 ? ["S3", "S4"] : ["S5", "S6"]);
    const nextParcoursList = yearMeta?.parcours?.length
      ? yearMeta.parcours
      : parcoursList.filter((p) => p === `BUT${nextYear}` || p.startsWith(`BUT${nextYear}-`));
    if (!nextSemestres.includes(semestre)) {
      setSemestre(nextSemestres[0] ?? "S1");
    }
    if (nextParcoursList.length && !nextParcoursList.includes(parcours)) {
      setParcours(nextParcoursList[0]);
    }
    const defaultTd = groups.find((g) => g.parcours === (nextParcoursList[0] ?? parcours) && g.kind === "td");
    if (defaultTd) {
      setGroupId(defaultTd.id);
    }
  };

  const handleParcoursChange = (next: string) => {
    setParcours(next);
    const defaultTd = groups.find((g) => g.parcours === next && g.kind === "td");
    setGroupId(defaultTd?.id ?? "");
  };

  const handleSemestreChange = (next: string) => {
    setSemestre(next);
    setYear(yearFromSemestre(next));
  };

  return (
    <div className="app">
      <Toolbar
        year={year}
        parcours={parcours}
        semestre={semestre}
        years={years}
        parcoursList={parcoursList}
        displayWeek={displayWeek}
        maxWeeks={MAX_WEEKS}
        viewMode={viewMode}
        groupId={groupId}
        teacherCode={teacherCode}
        roomId={roomId}
        groups={groups}
        teachers={teachers}
        rooms={rooms}
        loading={loading}
        onYearChange={handleYearChange}
        onParcoursChange={handleParcoursChange}
        onSemestreChange={handleSemestreChange}
        onWeekChange={setDisplayWeek}
        onViewModeChange={setViewMode}
        onGroupChange={setGroupId}
        onTeacherChange={setTeacherCode}
        onRoomChange={setRoomId}
        onIngest={handleIngest}
        onSolve={() => handleSolve(false)}
        onRegenerate={() => handleSolve(true)}
      />

      {(error || notice) && (
        <div className={`banner ${error ? "banner--error" : "banner--info"}`}>
          {error ?? notice}
          <button type="button" onClick={() => { setError(null); setNotice(null); }}>×</button>
        </div>
      )}

      <main className="layout">
        <section className="calendar-section">
          <div className="section-header">
            <h2>
              Semaine {displayWeek + 1}
              <span className="count">{visiblePlacements.length} séances</span>
            </h2>
            <div className="legend">
              <span className="legend-item cm">CM (promo, 2 col.)</span>
              <span className="legend-item td">TD (2 TP, 2 col.)</span>
              <span className="legend-item tp">TP (1 col.)</span>
              <span className="legend-item eval">Éval / SAE</span>
            </div>
          </div>

          {placements.length === 0 ? (
            <div className="empty-state">
              <p>Aucun planning chargé.</p>
              <p className="muted">Cliquez « Générer » pour lancer le solveur CP-SAT.</p>
            </div>
          ) : viewMode === "group" && groupId && groups.find((g) => g.id === groupId)?.kind === "td" ? (
            <TdWeekGrid
              placements={placements}
              displayWeek={displayWeek}
              tdGroupId={groupId}
              groups={groups}
              groupLabels={groupLabels}
              onSelect={setSelected}
            />
          ) : (
            <TimetableCalendar
              placements={placements}
              displayWeek={displayWeek}
              groupLabels={groupLabels}
              onPlacementUpdated={handlePlacementUpdated}
              onSelect={setSelected}
              onError={(msg) => setNotice(msg)}
            />
          )}
        </section>

        <aside className="sidebar">
          <QualityPanel quality={quality} status={status} correctionsCount={correctionsCount} />
          <DiffPanel
            diff={diff}
            analysis={analysis}
            onApplyFeedback={handleApplyFeedback}
            onExportCsv={handleExportCsv}
            onExportJson={handleExportJson}
            loading={loading}
          />
          <SessionPanel
            placement={selected}
            onClose={() => setSelected(null)}
            onUpdated={handlePlacementUpdated}
            onError={setError}
          />
        </aside>
      </main>
    </div>
  );
}
