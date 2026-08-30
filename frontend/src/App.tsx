import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyFeedback,
  checkAuthStatus,
  exportCsvUrl,
  exportJson,
  extractTeachers,
  fetchAppState,
  fetchDiff,
  fetchFeedbackAnalysis,
  fetchMeta,
  fetchTimetable,
  setAccessToken,
} from "./api/client";
import { DayStrip, todayIndex } from "./components/DayStrip";
import { DiffPanel } from "./components/DiffPanel";
import { GlobalSearch } from "./components/GlobalSearch";
import { ConfirmModal } from "./components/ConfirmModal";
import { ContextePreferences, ecrirePreferences, lirePreferences, type Preferences } from "./utils/preferences";
import { PreferencesModal } from "./components/PreferencesModal";
import { LoginGate } from "./components/LoginGate";
import { PageHeader } from "./components/PageHeader";
import { SideNav } from "./components/SideNav";
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
import { APlacerView } from "./views/APlacerView";
import { TodoView } from "./views/TodoView";

const DEFAULT_PARCOURS = "BUT1";
const DEFAULT_SEMESTRE = "S1";
// Plage d'affichage du sélecteur de semaine dans le Toolbar (UI uniquement) —
// l'horizon réel du solveur est calculé côté backend depuis le calendrier
// (cf. cal_iut.calendar.academic.default_horizon_weeks), pas fixé ici.
const MAX_WEEKS = 24;

export function App() {
  const { route, setRoute } = useHashRoute();
  const [search, setSearch] = useState(false);
  // Tiroir de navigation mobile (<1024px) — la barre latérale devient un
  // panneau coulissant sous ce seuil (cf. .sidenav dans app.css).
  const [navOpen, setNavOpen] = useState(false);
  const navToggleRef = useRef<HTMLButtonElement>(null);
  const appContentRef = useRef<HTMLDivElement>(null);
  // Symétrique du focus posé sur le bouton fermer à l'ouverture
  // (SideNav.tsx) : à la fermeture, le focus clavier revient sur le ☰ qui
  // l'a ouvert plutôt que de se perdre sur le body (audit a11y du
  // 27/08/2026). Ignore le premier rendu (navOpen déjà à false).
  const wasNavOpen = useRef(false);
  useEffect(() => {
    if (wasNavOpen.current && !navOpen) navToggleRef.current?.focus();
    wasNavOpen.current = navOpen;
  }, [navOpen]);
  // `inert` posé impérativement (pas en prop JSX) : les types
  // `@types/react` 18.3 ne déclarent pas encore cet attribut HTML, alors
  // que `HTMLElement.inert` existe bien dans le DOM lui-même.
  useEffect(() => {
    if (appContentRef.current) appContentRef.current.inert = navOpen;
  }, [navOpen]);
  const narrow = useNarrowScreen();
  const [mobileDay, setMobileDay] = useState(todayIndex());

  // Préférence d'affichage, gardée sur l'appareil (cf.
  // `utils/preferences.ts`). Dans l'état de React plutôt que relue à
  // chaque rendu : c'est ce qui fait que la bascule repeint la grille
  // immédiatement, sans recharger la page.
  const [prefs, setPrefs] = useState<Preferences>(() => lirePreferences());
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [appPayload, setAppPayload] = useState<AppPayload | null>(null);
  const [placements, setPlacements] = useState<Placement[]>([]);
  // Vue Promo montre TOUT (aucun filtre groupe/enseignant/salle, contrairement
  // à `placements` ci-dessus, filtré par le Toolbar de Vue Semaine) — sans sa
  // propre liste, le glisser-déposer n'y trouverait sa cible que par hasard
  // (seulement si elle appartient au filtre Vue Semaine du moment). Retour
  // utilisateur 28/08/2026 : glisser-déposer déplacé de Vue Semaine à Vue Promo.
  const [promoPlacements, setPromoPlacements] = useState<Placement[]>([]);
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

  // Mot de passe partagé (retour utilisateur 28/08/2026) — `null` = statut
  // pas encore connu (évite un flash du formulaire avant la première
  // réponse de `/auth/status`, endpoint jamais bloqué lui-même).
  const [authentifie, setAuthentifie] = useState<boolean | null>(null);

  // Code du lien personnel (`route.t`, prof ou groupe) — posé AVANT tout
  // appel API (cf. api/client.ts::setAccessToken) : sans cet ordre, les
  // fetches initiaux ci-dessous partiraient sans lui.
  useEffect(() => {
    setAccessToken(route.t || null);
  }, [route.t]);

  useEffect(() => {
    checkAuthStatus()
      .then(setAuthentifie)
      .catch(() => setAuthentifie(false));
  }, []);

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

  useEffect(() => {
    // Lien perso (readOnlyTarget) : le paramètre `t` fait le travail d'auth
    // tout seul (public depuis le 28/08/2026), peu importe `authentifie`
    // (qui reste `false`, ces liens n'ont jamais la session admin). Sinon,
    // attend une session confirmée — partir plus tôt ne ferait qu'échouer
    // en 401 pour rien.
    if (!readOnlyTarget && authentifie !== true) return;
    void refreshMeta();
    void refreshAppState();
  }, [refreshMeta, refreshAppState, readOnlyTarget, authentifie]);

  const loadTimetable = useCallback(async () => {
    try {
      const data = await fetchTimetable({
        group_id: viewMode === "group" && groupId ? groupId : undefined,
        teacher_code: viewMode === "teacher" && teacherCode ? teacherCode : undefined,
        room_id: viewMode === "room" && roomId ? roomId : undefined,
      });
      setPlacements(data.placements);
      await refreshDiff();
    } catch {
      /* no timetable */
    }
  }, [viewMode, groupId, teacherCode, roomId, refreshDiff]);

  useEffect(() => {
    void loadTimetable();
  }, [loadTimetable]);

  const loadPromoTimetable = useCallback(async () => {
    try {
      const data = await fetchTimetable({});
      setPromoPlacements(data.placements);
    } catch {
      /* pas encore de planning */
    }
  }, []);

  useEffect(() => {
    if (activeTab === "promo" && !readOnlyTarget) void loadPromoTimetable();
  }, [activeTab, readOnlyTarget, loadPromoTimetable]);

  // `handleIngest`/`handleSolve` (boutons "Charger données"/"Générer"/
  // "Recalculer tout" du Toolbar) retirés (retour utilisateur 27/08/2026) —
  // génération toujours faite en CLI. `loading`/`setNotice`/`setError`
  // restent utilisées par les actions encore présentes (verrouillage,
  // panneau de diff/export...).

  const handlePlacementUpdated = (updated: Placement) => {
    setPlacements((prev) => prev.map((p) => (p.session_id === updated.session_id ? updated : p)));
    setPromoPlacements((prev) => prev.map((p) => (p.session_id === updated.session_id ? updated : p)));
    setSelected(updated);
    void refreshDiff();
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
  // `TimetableCalendar` (qui, lui, attend bien l'index solveur) et
  // `visiblePlacements` ci-dessous — un
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
      } else if (e.key === "Escape" && navOpen) {
        setNavOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [search, navOpen, readOnlyTarget]);

  // Mot de passe requis avant TOUT le reste — sauf lien perso (readOnlyTarget),
  // qui n'entre jamais dans ce couloir (retour utilisateur 28/08/2026 :
  // « uniquement les prof ai accès a leur lien sans mot de passe »).
  // `authentifie === null` : statut pas encore connu, écran neutre plutôt
  // qu'un flash du formulaire suivi d'un flash de l'app.
  if (!readOnlyTarget && authentifie === false) {
    return <LoginGate onSuccess={() => setAuthentifie(true)} />;
  }
  if (!readOnlyTarget && authentifie === null) {
    return <div className="app" aria-busy="true" />;
  }

  return (
    // Fournit la préférence à TOUT l'écran. Sans ce fournisseur, chaque
    // grille relisait `localStorage` de son côté et le clic ne repeignait
    // rien (retour utilisateur 30/08/2026).
    <ContextePreferences.Provider value={prefs}>
    <div className={`app ${readOnlyTarget ? "read-only-mode" : ""}`}>
      {/* Lien d'évitement : premier élément focusable de la page, il permet à
          qui navigue au clavier de sauter la navigation pour atteindre
          directement le contenu. Visible uniquement au focus (cf. `.skiplink`). */}
      {!readOnlyTarget && (
        <a className="skiplink" href="#contenu">
          Aller au contenu
        </a>
      )}

      <div className="app-shell">
        {!readOnlyTarget && (
          <>
            {/* Bande fine visible <1024px seulement (cf. app.css) — la barre
                latérale devient un tiroir coulissant sous ce seuil. */}
            <div className="navtoggle-bar no-print">
              <button
                type="button"
                ref={navToggleRef}
                className="navtoggle"
                onClick={() => setNavOpen(true)}
                aria-label="Ouvrir la navigation"
              >
                <span aria-hidden="true">☰</span> cal-iut
              </button>
            </div>
            <SideNav
              activeTab={activeTab}
              onSelect={(id) => setRoute({ vue: id })}
              onOpenSearch={() => setSearch(true)}
              hasPayload={!!appPayload}
              todoCount={todoCount}
              todoHasBad={todoHasBad}
              open={navOpen}
              onClose={() => setNavOpen(false)}
            />
          </>
        )}

        {/* `inert` pendant que le tiroir mobile est ouvert : sans lui, un
            `Tab` traverse le fond visuellement assombri par `.sidenav-scrim`
            comme si de rien n'était (le z-index n'affecte pas l'ordre de
            tabulation) — sûr ici car `navOpen` ne passe à `true` que via le
            ☰, lui-même masqué par CSS dès 1024px (audit a11y du
            27/08/2026). */}
        <div className="app-content" ref={appContentRef}>
          {!readOnlyTarget && appPayload && (
            <>
              <PageHeader payload={appPayload} />
              <ReglageCouleurs prefs={prefs} setPrefs={setPrefs} />
            </>
          )}

          {readOnlyTarget && appPayload && (
            <header className="readonly-banner">
              <h1>
                {readOnlyTarget === "prof"
                  ? `Planning de ${appPayload.teacherLabels[route.prof] ?? route.prof}`
                  : // Parcours en préfixe — retour utilisateur 28/08/2026 :
                    // « pourquoi on a pas le nom complet du groupe dessus ».
                    // Le libellé seul ("TD EF") existe en double identique
                    // entre plusieurs parcours (cf. ReferenceView.tsx, même
                    // correctif) : sans le parcours, impossible de savoir
                    // lequel des deux ce lien désigne.
                    `Planning — ${
                      appPayload.groupParcours[route.groupe]
                        ? `${appPayload.groupParcours[route.groupe]} · ${appPayload.groupLabels[route.groupe] ?? route.groupe}`
                        : (appPayload.groupLabels[route.groupe] ?? route.groupe)
                    }`}
              </h1>
              <p>Vue en lecture seule — pour toute correction, contactez le responsable des emplois du temps.</p>
              <ReglageCouleurs prefs={prefs} setPrefs={setPrefs} />
            </header>
          )}

          {/* `role="alert"` pour une erreur (annoncée immédiatement), `status` pour
              une information (annoncée sans interrompre). Sans eux, un message
              d'erreur apparaissait sans qu'un lecteur d'écran le signale. */}
          {(error || notice) && !readOnlyTarget && (
            <div
              className={`banner ${error ? "banner--error" : "banner--info"}`}
              role={error ? "alert" : "status"}
            >
              {error ?? notice}
              <button
                type="button"
                aria-label="Fermer ce message"
                onClick={() => { setError(null); setNotice(null); }}
              >
                <span aria-hidden="true">×</span>
              </button>
            </div>
          )}

          <main className="app-main" id="contenu" tabIndex={-1}>
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
                    <p className="muted">Lancez le solveur CP-SAT en CLI (cal-iut solve / load-run), puis rechargez cette page.</p>
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
                    onSelect={setSelected}
                  />
                )}
              </section>

              <aside className="sidebar">
                {/* QualityPanel (indicateurs trous/isolés/déséquilibre) et
                    RegenPanel (régénération ciblée) retirés de Vue Semaine
                    (retour utilisateur 28/08/2026 : « on enlève la
                    régénération ciblée [...] tu peux aussi enlever les
                    indicateurs »). */}
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
        {activeTab === "promo" && appPayload && !readOnlyTarget && (
          <PromoView
            payload={appPayload}
            route={route}
            placements={promoPlacements}
            onPlacementUpdated={handlePlacementUpdated}
            onError={(msg) => setNotice(msg)}
          />
        )}
        {activeTab === "reference" && appPayload && !readOnlyTarget && (
          <ReferenceView payload={appPayload} setRoute={setRoute} />
        )}
        {activeTab === "contraintes" && appPayload && !readOnlyTarget && (
          <ContraintesView payload={appPayload} setRoute={setRoute} />
        )}
        {activeTab === "apf" && appPayload && !readOnlyTarget && <TodoView payload={appPayload} setRoute={setRoute} />}
        {/* Placement manuel du reliquat que le solveur n'a pas su placer.
            Pas de `appPayload` requis : cet écran interroge le serveur
            directement, et doit rester accessible même quand le planning
            est trop incomplet pour que les autres vues aient du sens. */}
        {activeTab === "aplacer" && !readOnlyTarget && (
          <APlacerView onPlacement={() => void loadTimetable()} payload={appPayload} />
        )}
          </main>
        </div>
      </div>

      {appPayload && !readOnlyTarget && (
        <GlobalSearch payload={appPayload} open={search} onClose={() => setSearch(false)} onNavigate={setRoute} />
      )}
      {/* Une seule instance pour toute l'app — cf. utils/confirmDialog.ts. */}
      <ConfirmModal />
      {/* Posée une seule fois par appareil : c'est `repondu` qui ferme la
          question, pas la valeur choisie — sinon elle reviendrait à chaque
          visite de qui a répondu « non ». */}
      {!prefs.repondu && (
        <PreferencesModal
          onChoix={(couleursParMatiere) =>
            setPrefs(ecrirePreferences({ couleursParMatiere, repondu: true }))
          }
        />
      )}
    </div>
    </ContextePreferences.Provider>
  );
}


/** Réglage des couleurs, gardé accessible après le premier choix : une
 *  préférence qu'on ne peut plus changer est un piège.
 *
 *  Un `<select>` et non une bascule maison — retour utilisateur 30/08/2026 :
 *  « le sélecteur n'est pas du tout dans la DA du reste, fais juste un select
 *  au pire ». Il reprend exactement le patron `label > select` de la barre
 *  d'outils, donc son style suit celui de l'application sans rien de
 *  spécifique à maintenir. */
function ReglageCouleurs({
  prefs,
  setPrefs,
}: {
  prefs: Preferences;
  setPrefs: (p: Preferences) => void;
}) {
  return (
    <div className="prefs-reglage toolbar-controls">
      <label>
        Couleurs
        <select
          value={prefs.couleursParMatiere ? "matiere" : "type"}
          onChange={(e) =>
            setPrefs(
              ecrirePreferences({ couleursParMatiere: e.target.value === "matiere", repondu: true }),
            )
          }
        >
          <option value="type">Par type de séance</option>
          <option value="matiere">Par matière</option>
        </select>
      </label>
    </div>
  );
}
