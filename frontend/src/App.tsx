import { useCallback, useEffect, useState } from "react";

import {
  applyFeedback,
  exportCsvUrl,
  exportJson,
  extractTeachers,
  fetchAppState,
  fetchCorrections,
  fetchDiff,
  fetchFeedbackAnalysis,
  fetchMeta,
  fetchTimetable,
  ingest,
  solve,
} from "./api/client";
import { DayStrip, todayIndex } from "./components/DayStrip";
import { DiffPanel } from "./components/DiffPanel";
import { GlobalSearch } from "./components/GlobalSearch";
import { PageHeader } from "./components/PageHeader";
import { QualityPanel } from "./components/QualityPanel";
import { RegenPanel } from "./components/RegenPanel";
import { SessionPanel } from "./components/SessionPanel";
import { TdWeekGrid } from "./components/TdWeekGrid";
import { TimetableCalendar } from "./components/TimetableCalendar";
import { Toolbar } from "./components/Toolbar";
import { buildTodoList } from "./utils/todo";
import type { RouteView } from "./hooks/useHashRoute";
import { useHashRoute } from "./hooks/useHashRoute";
import { useNarrowScreen } from "./hooks/useNarrowScreen";
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
import type { AppPayload } from "./types/app";
import { DEFAULT_YEARS, yearFromSemestre } from "./utils/years";
import { ContraintesView } from "./views/ContraintesView";
import { EnseignantView } from "./views/EnseignantView";
import { GroupeView } from "./views/GroupeView";
import { PromoView } from "./views/PromoView";
import { ReferenceView } from "./views/ReferenceView";
import { TodoView } from "./views/TodoView";

const DEFAULT_PARCOURS = "BUT1";
const DEFAULT_SEMESTRE = "S1";
// Plage d'affichage du sélecteur de semaine dans le Toolbar (UI uniquement) —
// l'horizon réel du solveur est calculé côté backend depuis le calendrier
// (cf. cal_iut.calendar.academic.default_horizon_weeks), pas fixé ici.
const MAX_WEEKS = 24;

const TABS: { id: RouteView; label: string }[] = [
  { id: "semaine", label: "Vue Semaine" },
  { id: "groupe", label: "Vue Groupe" },
  { id: "prof", label: "Vue Enseignant" },
  { id: "promo", label: "Vue Promo" },
  { id: "reference", label: "Référence" },
  { id: "contraintes", label: "Contraintes" },
  { id: "apf", label: "À traiter" },
];

export function App() {
  const { route, setRoute } = useHashRoute();
  const [search, setSearch] = useState(false);
  const narrow = useNarrowScreen();
  const [mobileDay, setMobileDay] = useState(todayIndex());

  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [appPayload, setAppPayload] = useState<AppPayload | null>(null);
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [quality, setQuality] = useState<Quality | null>(null);
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

  // Fragment `#...&mode=prof` / `#...&mode=groupe` : lien personnel en
  // lecture seule (annuaire, mailto) — même mécanisme que la page HTML/JS
  // historique, pour que les liens restent valides quelle que soit
  // l'interface qui les ouvre.
  const readOnlyTarget: RouteView | null =
    route.mode === "prof" && route.prof ? "prof" : route.mode === "groupe" && route.groupe ? "groupe" : null;
  const activeTab: RouteView = readOnlyTarget ?? (route.vue || "semaine");

  const refreshMeta = useCallback(async () => {
    try {
      setMeta(await fetchMeta());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur meta");
    }
  }, []);

  const refreshAppState = useCallback(async () => {
    try {
      setAppPayload(await fetchAppState());
    } catch {
      // Pas encore de planning résolu — les vues en lecture seule affichent
      // un message d'attente plutôt qu'une erreur bruyante.
      setAppPayload(null);
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
    void refreshAppState();
  }, [refreshMeta, refreshAppState]);

  const loadTimetable = useCallback(async () => {
    try {
      const data = await fetchTimetable({
        group_id: viewMode === "group" && groupId ? groupId : undefined,
        teacher_code: viewMode === "teacher" && teacherCode ? teacherCode : undefined,
        room_id: viewMode === "room" && roomId ? roomId : undefined,
      });
      setPlacements(data.placements);
      setQuality(data.quality);
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
      setNotice(`Planning généré — ${data.placements.length} séances`);
      await refreshDiff();
      await refreshCorrections();
      await refreshAppState();
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
    void refreshAppState();
  };

  // `RegenPanel` (régénération ciblée d'UNE semaine) ne renvoie que les
  // séances de la (des) semaine(s) touchée(s) — remplace juste ces
  // entrées-là par `session_id`, laisse le reste du planning intact (c'est
  // tout l'intérêt d'une régénération ciblée par rapport à un `/solve`
  // complet, cf. docs/DATA.md).
  const handleRegenerated = (updated: Placement[]) => {
    const byId = new Map(updated.map((p) => [p.session_id, p]));
    setPlacements((prev) => prev.map((p) => byId.get(p.session_id) ?? p));
    void refreshDiff();
    void refreshCorrections();
    void refreshAppState();
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
  const groupLabels = Object.fromEntries(groups.map((g) => [g.id, g.label]));
  const weekDates = appPayload?.weekDates ?? [];
  // Charge par semaine (toutes séances de ce parcours/semestre confondues,
  // sans filtrer par groupe/enseignant/salle — la Vue Semaine n'a pas de
  // "cible" unique comme Groupe/Enseignant, contrairement à `GroupeView`/
  // `EnseignantView`) — alimente l'histogramme de la `WeekBar` dans la
  // barre d'outils (retour utilisateur 11/08/2026 : "il faut mettre les
  // semaine dans la vue semaine aussi").
  const weekCounts = new Map<number, number>();
  for (const p of placements) weekCounts.set(p.week, (weekCounts.get(p.week) ?? 0) + 1);
  const weekRows = appPayload?.weekRows ?? [];
  // `displayWeek` est l'index D'AFFICHAGE dans `weekRows` (28 lignes, TROUS
  // inclus pour les semaines bloquées — cf. `WeekBar`) — jamais l'index
  // solveur (0-23, SANS trou) qu'utilisent `placements[].week`/`weekDates`/
  // les endpoints de régénération. Bug réel du 12/08/2026 (retour
  // utilisateur : « FC S5 dev, aucune séance sur Semaine 11/14/26/29 » —
  // ces 4 semaines suivent toutes au moins une semaine bloquée, ce qui les
  // décale de l'index solveur réel) : `visiblePlacements` comparait
  // `displayWeek` directement à `p.week` sans jamais traduire via
  // `weekRows[displayWeek].weekIndex` — correct tant qu'aucune semaine
  // bloquée ne précède (les deux index coïncident), faux dès la première
  // semaine bloquée franchie (Toussaint ici). Même traduction déjà utilisée
  // correctement dans `PromoView.tsx` (`solverWeek`), reprise ici pour
  // `visiblePlacements` et tout ce qui est passé à `TdWeekGrid`/
  // `TimetableCalendar`/`RegenPanel` (qui, eux, attendent bien l'index
  // solveur — `RegenPanel.week` régénère CETTE semaine côté serveur, un
  // mauvais index y aurait régénéré la MAUVAISE semaine).
  const solverWeek = weekRows[displayWeek]?.weekIndex ?? null;
  const visiblePlacements = solverWeek === null ? [] : placements.filter((p) => p.week === solverWeek);
  const todoCount = appPayload ? buildTodoList(appPayload).length : 0;
  const todoHasBad = appPayload ? buildTodoList(appPayload).some((i) => i.sev === "bad") : false;

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

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (!readOnlyTarget) setSearch(true);
      } else if (e.key === "Escape" && search) {
        setSearch(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [search, readOnlyTarget]);

  return (
    <div className={`app ${readOnlyTarget ? "read-only-mode" : ""}`}>
      {!readOnlyTarget && appPayload && <PageHeader payload={appPayload} />}

      {!readOnlyTarget && (
        <nav className="tabbar">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`tabbtn ${activeTab === t.id ? "active" : ""}`}
              onClick={() => setRoute({ vue: t.id })}
            >
              {t.label}
              {t.id === "apf" && appPayload && (
                <span className={`pill mini ${todoHasBad ? "bad" : todoCount ? "warn" : "good"}`}>{todoCount}</span>
              )}
            </button>
          ))}
          <button type="button" className="searchopenbtn no-print" onClick={() => setSearch(true)}>
            Rechercher <span className="mono kbd">Ctrl+K</span>
          </button>
        </nav>
      )}

      {readOnlyTarget && appPayload && (
        <header className="readonly-banner">
          <h1>
            {readOnlyTarget === "prof"
              ? `Planning de ${appPayload.teacherLabels[route.prof] ?? route.prof}`
              : `Planning — ${appPayload.groupLabels[route.groupe] ?? route.groupe}`}
          </h1>
          <p>Vue en lecture seule — pour toute correction, contactez le responsable des emplois du temps.</p>
        </header>
      )}

      {(error || notice) && !readOnlyTarget && (
        <div className={`banner ${error ? "banner--error" : "banner--info"}`}>
          {error ?? notice}
          <button type="button" onClick={() => { setError(null); setNotice(null); }}>×</button>
        </div>
      )}

      <main className="app-main">
        {activeTab === "semaine" && !readOnlyTarget && (
          <>
            <Toolbar
              year={year}
              parcours={parcours}
              semestre={semestre}
              years={years}
              parcoursList={parcoursList}
              displayWeek={displayWeek}
              maxWeeks={MAX_WEEKS}
              weekRows={weekRows}
              weekCounts={weekCounts}
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

            <div className="layout">
              <section className="calendar-section">
                <div className="section-header">
                  <h2>
                    {weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
                    <span className="count">{visiblePlacements.length} séances</span>
                  </h2>
                  <div className="legend">
                    <span className="legend-item cm">CM (promo, 2 col.)</span>
                    <span className="legend-item td">TD (2 TP, 2 col.)</span>
                    <span className="legend-item tp">TP (1 col.)</span>
                    <span className="legend-item eval">Éval / SAE</span>
                  </div>
                </div>

                {narrow && viewMode === "group" && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

                {placements.length === 0 ? (
                  <div className="empty-state">
                    <p>Aucun planning chargé.</p>
                    <p className="muted">Cliquez « Générer » pour lancer le solveur CP-SAT.</p>
                  </div>
                ) : solverWeek === null ? (
                  <div className="empty-state">
                    <p>Semaine bloquée (vacances/fermeture).</p>
                  </div>
                ) : viewMode === "group" && groupId && groups.find((g) => g.id === groupId)?.kind === "td" ? (
                  <TdWeekGrid
                    placements={placements}
                    displayWeek={solverWeek}
                    tdGroupId={groupId}
                    groups={groups}
                    groupLabels={groupLabels}
                    onSelect={setSelected}
                    onPlacementUpdated={handlePlacementUpdated}
                    onError={(msg) => setNotice(msg)}
                    payload={appPayload}
                    parcours={parcours}
                    onlyDay={narrow ? mobileDay : null}
                  />
                ) : (
                  <TimetableCalendar
                    placements={placements}
                    displayWeek={solverWeek}
                    weekDates={weekDates}
                    groupLabels={groupLabels}
                    onPlacementUpdated={handlePlacementUpdated}
                    onSelect={setSelected}
                    onError={(msg) => setNotice(msg)}
                  />
                )}
              </section>

              <aside className="sidebar">
                <QualityPanel quality={quality} correctionsCount={correctionsCount} />
                {appPayload && solverWeek !== null && (
                  <RegenPanel
                    week={solverWeek}
                    weekLabel={appPayload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
                    weekStatus={appPayload.weekStatus}
                    teacherCodes={teachers}
                    teacherLabels={appPayload.teacherLabels}
                    rooms={rooms}
                    onRegenerated={handleRegenerated}
                    onNotice={setNotice}
                  />
                )}
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
            </div>
          </>
        )}

        {activeTab !== "semaine" && !appPayload && (
          <div className="empty-state">
            <p>Aucun planning résolu.</p>
            <p className="muted">Générez un planning depuis la Vue Semaine pour voir cette page.</p>
          </div>
        )}

        {activeTab === "groupe" && appPayload && (
          <GroupeView payload={appPayload} route={route} setRoute={setRoute} readOnly={readOnlyTarget === "groupe"} />
        )}
        {activeTab === "prof" && appPayload && (
          <EnseignantView payload={appPayload} route={route} setRoute={setRoute} readOnly={readOnlyTarget === "prof"} />
        )}
        {activeTab === "promo" && appPayload && !readOnlyTarget && <PromoView payload={appPayload} />}
        {activeTab === "reference" && appPayload && !readOnlyTarget && (
          <ReferenceView payload={appPayload} setRoute={setRoute} />
        )}
        {activeTab === "contraintes" && appPayload && !readOnlyTarget && (
          <ContraintesView payload={appPayload} setRoute={setRoute} />
        )}
        {activeTab === "apf" && appPayload && !readOnlyTarget && <TodoView payload={appPayload} setRoute={setRoute} />}
      </main>

      {appPayload && !readOnlyTarget && (
        <GlobalSearch payload={appPayload} open={search} onClose={() => setSearch(false)} onNavigate={setRoute} />
      )}
    </div>
  );
}
