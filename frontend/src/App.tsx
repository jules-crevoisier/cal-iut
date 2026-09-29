import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyFeedback,
  ecouterLiaison,
  ErreurApi,
  exportCsvUrl,
  exportJson,
  extractTeachers,
  fetchAppState,
  fetchDiff,
  fetchDoublons,
  fetchFeedbackAnalysis,
  fetchMeta,
  fetchMoi,
  fetchSante,
  fetchTimetable,
  fetchVersion,
  logout,
  setAccessToken,
} from "./api/client";
import type { EtatSante, MoiResponse } from "./api/client";
import { AccountPendingGate } from "./components/AccountPendingGate";
import { BandeauPanne, BandeauServeurDegrade } from "./components/BandeauPanne";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DayStrip, todayIndex } from "./components/DayStrip";
import { DiffPanel } from "./components/DiffPanel";
import { EmailConfirmedPage } from "./components/EmailConfirmedPage";
import { ForgotPasswordPage } from "./components/ForgotPasswordPage";
import { GlobalSearch } from "./components/GlobalSearch";
import { ConfirmModal } from "./components/ConfirmModal";
import { ContextePreferences, ecrirePreferences, lirePreferences, type Preferences } from "./utils/preferences";
import { PreferencesModal } from "./components/PreferencesModal";
import { LoginGate } from "./components/LoginGate";
import { PageHeader } from "./components/PageHeader";
import { ResetPasswordPage } from "./components/ResetPasswordPage";
import { SideNav } from "./components/SideNav";
import { SessionPanel } from "./components/SessionPanel";
import { SignupPage } from "./components/SignupPage";
import { TdWeekGrid } from "./components/TdWeekGrid";
import { TimetableCalendar } from "./components/TimetableCalendar";
import { Toolbar } from "./components/Toolbar";
import { AdminCelcatView } from "./views/AdminCelcatView";
import { AdminUsersView } from "./views/AdminUsersView";
import { McpKeysView } from "./views/McpKeysView";
import { SauvegardesView } from "./views/SauvegardesView";
import { indexSemaineCourante } from "./utils/semaineCourante";
import { compterATraiter } from "./utils/todo";
import type { RouteView } from "./hooks/useHashRoute";
import { useHashRoute } from "./hooks/useHashRoute";
import { useNarrowScreen } from "./hooks/useNarrowScreen";
import { useRevision } from "./hooks/useRevision";
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
import { DEFAULT_YEARS } from "./utils/years";
import { ContraintesView } from "./views/ContraintesView";
import { CoursView } from "./views/CoursView";
import { EnseignantView } from "./views/EnseignantView";
import { GroupeView } from "./views/GroupeView";
import { PromoView } from "./views/PromoView";
import { ReferenceView } from "./views/ReferenceView";
import { APlacerView } from "./views/APlacerView";
import { KanbanView } from "./views/KanbanView";
import { SalleView } from "./views/SalleView";
import { SallesLibresView } from "./views/SallesLibresView";
import { TodoView } from "./views/TodoView";

const DEFAULT_PARCOURS = "BUT1";
// Serveur injoignable : nouvelle tentative à ce rythme tant que dure la panne.
const REESSAI_PANNE_MS = 15_000;
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
  const [displayWeek, setDisplayWeek] = useState(0);
  // Une seule fois, au premier planning reçu : ouvrir sur la semaine EN
  // COURS plutôt que sur la première de l'année (retour utilisateur
  // 08/09/2026). Un drapeau plutôt qu'un effet sur `appPayload` : sans lui,
  // chaque rechargement de planning ramènerait l'utilisateur à aujourd'hui
  // alors qu'il consultait une autre semaine.
  const semaineInitialisee = useRef(false);
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
    route.mode === "prof" && route.prof
      ? "prof"
      : route.mode === "groupe" && route.groupe
        ? "groupe"
        : route.mode === "promo"
          ? "promo"
          : // Lien public « Salles libres » (retour utilisateur 25/09/2026,
            // Jules, dicté : « on met ça en lien public ») — même mécanisme
            // que "promo", cible le tableau d'occupation plutôt qu'une entité.
            route.mode === "salles"
            ? "salles-libres"
            : null;
  const activeTab: RouteView = readOnlyTarget ?? (route.vue || "semaine");

  // Système de comptes (31/08/2026, remplace le mot de passe partagé) —
  // `undefined` = statut pas encore connu (évite un flash du formulaire
  // avant la première réponse de `GET /auth/me`), `null` = pas de session,
  // sinon le compte connecté (actif ou non — `moi.status` distingue).
  const [moi, setMoi] = useState<MoiResponse | null | undefined>(undefined);
  const rafraichirMoi = useCallback(() => {
    // `fetchMoi` ne rend `null` que sur un vrai 401. Une panne laisse `moi`
    // tel quel (inconnu, ou le compte déjà connu) : le bandeau de panne le
    // dit, et jamais l'écran de connexion à quelqu'un de bien connecté
    // (audit du 29/09/2026, P1-13).
    fetchMoi()
      .then(setMoi)
      .catch(() => undefined);
  }, []);

  // Serveur injoignable (cf. `api/client.ts::ecouterLiaison`) : bandeau au
  // lieu d'écrans vides ou trompeurs. Et une session qui expire en cours de
  // travail (401 sur n'importe quel appel) ramène à l'écran de connexion —
  // jamais sur un lien public, qui n'a pas de session.
  const [panne, setPanne] = useState(false);
  const lienPublicRef = useRef(readOnlyTarget !== null);
  lienPublicRef.current = readOnlyTarget !== null;
  useEffect(
    () =>
      ecouterLiaison((evenement) => {
        if (evenement === "panne") setPanne(true);
        else if (evenement === "retablie") setPanne(false);
        else if (!lienPublicRef.current) setMoi((avant) => (avant ? null : avant));
      }),
    [],
  );

  // Code du lien personnel (`route.t`, prof ou groupe) — posé AVANT tout
  // appel API (cf. api/client.ts::setAccessToken) : sans cet ordre, les
  // fetches initiaux ci-dessous partiraient sans lui.
  useEffect(() => {
    setAccessToken(route.t || null);
  }, [route.t]);

  // Lien public (`?t=`, readOnlyTarget) : le serveur ne sert plus que les
  // lectures des vues publiques (`/meta`, `/app-state`, `/timetable`,
  // `/ics/`, cf. `_LIEN_PERSO_PREFIXES` dans `api/main.py`). Les routes
  // d'administration (diff, analyse des corrections, doublons) y répondent
  // 401 : ne pas les appeler du tout. Ni `/auth/me` : un lien public n'a
  // jamais de session, la question partait en 401 à chaque ouverture.
  const lienPublic = readOnlyTarget !== null;
  useEffect(() => {
    if (!lienPublic) rafraichirMoi();
  }, [rafraichirMoi, lienPublic]);

  const refreshMeta = useCallback(async () => {
    try {
      setMeta(await fetchMeta());
    } catch (e) {
      // Panne ou session : le bandeau (ou l'écran de connexion) le dit déjà.
      if (e instanceof ErreurApi && e.genre !== "refus") return;
      setError(e instanceof Error ? e.message : "Erreur meta");
    }
  }, []);

  // Pourquoi `appPayload` est vide : pas encore reçu, aucun planning côté
  // serveur (404), ou chargement impossible (panne). Avant, une panne
  // s'affichait « Aucun planning résolu » (audit du 29/09/2026, P1-13).
  const [etatPlanning, setEtatPlanning] = useState<"chargement" | "charge" | "absent" | "echec">("chargement");
  const refreshAppState = useCallback(async () => {
    try {
      const recu = await fetchAppState();
      setAppPayload(recu);
      setEtatPlanning("charge");
      if (!semaineInitialisee.current && recu?.weekRows?.length) {
        semaineInitialisee.current = true;
        setDisplayWeek(indexSemaineCourante(recu.weekRows));
      }
    } catch (e) {
      // Un état DÉJÀ affiché est gardé tel quel (jamais `setAppPayload(null)`) :
      // ce rechargement part aussi tout seul (`useRevision`), et une coupure
      // réseau ne doit pas vider l'écran de quelqu'un en train de travailler.
      setEtatPlanning((avant) =>
        avant === "charge" ? avant : e instanceof ErreurApi && e.status === 404 ? "absent" : "echec",
      );
    }
  }, []);

  const refreshDiff = useCallback(async () => {
    if (lienPublic) return;
    try {
      const [d, a] = await Promise.all([fetchDiff(), fetchFeedbackAnalysis()]);
      setDiff(d);
      setAnalysis(a);
    } catch {
      /* no diff yet */
    }
  }, [lienPublic]);

  // Total des doublons salle/enseignant (retour Kyllian Bresson 25/09/2026,
  // cf. `api/doublons.py`) — chargé ICI (pas seulement dans `TodoView`, qui
  // a son propre fetch pour sa liste détaillée) pour alimenter le badge de
  // la nav (`todoCount` ci-dessous, cf. `SideNav`) même quand l'onglet « À
  // traiter » n'a jamais été ouvert. Live (comme `TodoView`), pas le
  // contrôle hebdomadaire (`GET /controles/doublons/hebdo`) : le badge doit
  // rester juste même si le filet automatique n'a pas encore tourné cette
  // semaine.
  const [doublonsCount, setDoublonsCount] = useState(0);
  const refreshDoublonsCount = useCallback(async () => {
    if (lienPublic) return;
    try {
      const liste = await fetchDoublons();
      setDoublonsCount(liste.length);
    } catch {
      // Le badge garde son dernier total connu — jamais d'écran cassé pour
      // un chiffre secondaire.
    }
  }, [lienPublic]);

  useEffect(() => {
    // Lien perso (readOnlyTarget) : le paramètre `t` fait le travail d'auth
    // tout seul (public depuis le 28/08/2026), peu importe `moi` (qui reste
    // `null`, ces liens n'ont jamais de session compte). Sinon, attend un
    // compte ACTIF — partir plus tôt (compte en attente d'activation)
    // échouerait en 403 pour rien.
    if (!readOnlyTarget && moi?.status !== "active") return;
    void refreshMeta();
    void refreshAppState();
    // Doublons et historique des corrections : réservés aux comptes (rôle
    // « edit » côté serveur) et affichés nulle part sur un lien perso — les
    // demander là ne faisait que des 401.
    if (readOnlyTarget) return;
    void refreshDoublonsCount();
    void refreshDiff();
  }, [refreshMeta, refreshAppState, refreshDoublonsCount, refreshDiff, readOnlyTarget, moi]);

  const loadTimetable = useCallback(async () => {
    try {
      const data = await fetchTimetable({
        group_id: viewMode === "group" && groupId ? groupId : undefined,
        teacher_code: viewMode === "teacher" && teacherCode ? teacherCode : undefined,
        room_id: viewMode === "room" && roomId ? roomId : undefined,
      });
      setPlacements(data.placements);
    } catch {
      /* no timetable */
    }
  }, [viewMode, groupId, teacherCode, roomId]);

  // Comme `refreshAppState` ci-dessus : attendre un compte ACTIF. Parti au
  // montage, avant `/auth/me`, cet appel prenait un 401 et n'était jamais
  // relancé après la connexion — la Vue Semaine restait vide jusqu'à un F5.
  // Pas sur un lien perso : la Vue Semaine n'y est jamais affichée.
  const compteActif = moi?.status === "active";
  useEffect(() => {
    if (!compteActif || readOnlyTarget) return;
    void loadTimetable();
  }, [loadTimetable, compteActif, readOnlyTarget]);

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

  // Un collègue modifie le planning depuis un autre poste : sans F5, cet
  // écran le voit au plus tard au sondage suivant (cf. `hooks/useRevision.ts`).
  // Rien n'est rechargé tant que la révision ne bouge pas, et ce qui n'a pas
  // changé revient en 304 (ETag) — le coût d'un rechargement est celui de ce
  // qui a vraiment changé. Lien public en lecture seule : sondage espacé,
  // personne n'y attend une mise à jour à la seconde.
  // Planning enregistré mais non chargé côté serveur (`/health` en 503
  // `degraded`) : montré aux admins, les seuls à pouvoir y remédier.
  const estAdmin = !readOnlyTarget && compteActif && moi?.role === "admin";
  const [sante, setSante] = useState<EtatSante | null>(null);
  const rafraichirSante = useCallback(async () => {
    if (!estAdmin) return;
    try {
      setSante(await fetchSante());
    } catch {
      // Panne : c'est le bandeau de panne qui parle.
    }
  }, [estAdmin]);
  useEffect(() => {
    void rafraichirSante();
  }, [rafraichirSante]);

  const toutRecharger = () => {
    void refreshAppState();
    if (readOnlyTarget) return;
    void refreshMeta();
    void refreshDoublonsCount();
    void refreshDiff();
    void loadTimetable();
    if (activeTab === "promo") void loadPromoTimetable();
    void rafraichirSante();
  };
  const { verifierMaintenant } = useRevision({
    actif: !!readOnlyTarget || compteActif,
    intervalleMs: readOnlyTarget ? 3 * 60_000 : 30_000,
    onChange: toutRecharger,
  });

  // Pendant une panne : nouvelle tentative régulière (et immédiate avec
  // « Réessayer »). Tant que le compte est inconnu, c'est `/auth/me` qu'on
  // retente ; sinon, un sondage de révision suffit à savoir si le serveur
  // répond. Au retour, tout ce qui dépend du serveur est rechargé une fois :
  // un écran chargé PENDANT la panne est resté vide ou périmé.
  const reessayer = () => {
    if (!readOnlyTarget && moi === undefined) rafraichirMoi();
    else void fetchVersion().catch(() => undefined);
  };
  const reessayerRef = useRef(reessayer);
  reessayerRef.current = reessayer;
  const toutRechargerRef = useRef(toutRecharger);
  toutRechargerRef.current = toutRecharger;
  const panneAvant = useRef(false);
  const dernierRechargementApresPanne = useRef(0);
  useEffect(() => {
    const sortieDePanne = panneAvant.current && !panne;
    panneAvant.current = panne;
    if (sortieDePanne) {
      // Au plus un rechargement par intervalle de réessai : si une seule
      // ressource reste en échec pendant que les autres répondent, panne et
      // retour s'enchaîneraient sinon en boucle serrée contre le serveur.
      const maintenant = Date.now();
      if ((readOnlyTarget || compteActif) && maintenant - dernierRechargementApresPanne.current >= REESSAI_PANNE_MS) {
        dernierRechargementApresPanne.current = maintenant;
        toutRechargerRef.current();
      }
      return;
    }
    if (!panne) return;
    const minuterie = setInterval(() => reessayerRef.current(), REESSAI_PANNE_MS);
    return () => clearInterval(minuterie);
  }, [panne, readOnlyTarget, compteActif]);

  // Planning jamais reçu à cause d'une panne : il est retenté à son tour,
  // même si le reste du serveur répond (délai dépassé sur lui seul).
  useEffect(() => {
    if (etatPlanning !== "echec") return;
    const minuterie = setInterval(() => void refreshAppState(), REESSAI_PANNE_MS);
    return () => clearInterval(minuterie);
  }, [etatPlanning, refreshAppState]);

  const handlePlacementUpdated = (updated: Placement) => {
    setPlacements((prev) => prev.map((p) => (p.session_id === updated.session_id ? updated : p)));
    setPromoPlacements((prev) => prev.map((p) => (p.session_id === updated.session_id ? updated : p)));
    setSelected(updated);
    // Plutôt que `refreshDiff()` + `refreshAppState()` ici (et un second
    // `refreshDiff()` via `loadTimetable`) : une vérification de révision,
    // regroupée avec les écritures rapprochées, qui recharge tout ce qui
    // dépend du planning en un seul passage (`onChange` ci-dessus).
    verifierMaintenant();
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
  // Doublons salle/enseignant (retour Kyllian Bresson 25/09/2026) inclus
  // dans le compte : le badge « À traiter » doit refléter TOUT ce que cet
  // écran signale, pas seulement `buildTodoList` — un doublon EST quelque
  // chose « qui demande une décision », même s'il vient d'un calcul séparé
  // (`refreshDoublonsCount` ci-dessus).
  const { total: todoCount, aCorriger: todoACorriger } = compterATraiter(appPayload, doublonsCount);
  const todoHasBad = todoACorriger > 0;

  const handleYearChange = (nextYear: number) => {
    setYear(nextYear);
    const yearMeta = years.find((y) => y.id === nextYear);
    const nextParcoursList = yearMeta?.parcours?.length
      ? yearMeta.parcours
      : parcoursList.filter((p) => p === `BUT${nextYear}` || p.startsWith(`BUT${nextYear}-`));
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

  // Écrans du système de comptes (31/08/2026) — lus AVANT de savoir si une
  // session existe : inscription/mot de passe oublié sont volontairement
  // accessibles sans être connecté, et confirmation/réinitialisation sont
  // atteintes depuis un lien de mail, jamais depuis la nav.
  const retourConnexion = () => setRoute({ compte: "" });
  if (!readOnlyTarget && route.compte === "inscription") {
    return <SignupPage onRetourConnexion={retourConnexion} />;
  }
  if (!readOnlyTarget && route.compte === "mot-de-passe-oublie") {
    return <ForgotPasswordPage onRetourConnexion={retourConnexion} />;
  }
  if (!readOnlyTarget && route.compte === "confirme") {
    return (
      <EmailConfirmedPage
        statut={route.statut}
        onOuvrirInscription={() => setRoute({ compte: "inscription" })}
        onRetourConnexion={retourConnexion}
      />
    );
  }
  if (!readOnlyTarget && route.compte === "reinitialiser") {
    return <ResetPasswordPage token={route.token} onRetourConnexion={retourConnexion} />;
  }

  // Compte requis avant TOUT le reste — sauf lien perso (readOnlyTarget),
  // qui n'entre jamais dans ce couloir (retour utilisateur 28/08/2026 :
  // « uniquement les prof ai accès a leur lien sans mot de passe »).
  // `moi === undefined` : statut pas encore connu, écran neutre plutôt
  // qu'un flash du formulaire suivi d'un flash de l'app.
  if (!readOnlyTarget && moi === null) {
    return (
      <LoginGate
        onSuccess={rafraichirMoi}
        onOuvrirInscription={() => setRoute({ compte: "inscription" })}
        onOuvrirMotDePasseOublie={() => setRoute({ compte: "mot-de-passe-oublie" })}
      />
    );
  }
  if (!readOnlyTarget && moi === undefined) {
    // Serveur injoignable dès l'ouverture : on ne sait pas encore si une
    // session existe — le dire, plutôt qu'une page blanche ou le formulaire
    // de connexion.
    return (
      <div className="app" aria-busy={!panne}>
        {panne && <BandeauPanne onReessayer={reessayer} />}
      </div>
    );
  }
  if (!readOnlyTarget && moi !== null && moi !== undefined && moi.status !== "active") {
    return <AccountPendingGate email={moi.email} onDeconnecte={() => setMoi(null)} />;
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
              todoACorriger={todoACorriger}
              open={navOpen}
              onClose={() => setNavOpen(false)}
              estAdmin={moi?.role === "admin"}
              email={moi?.email}
              onLogout={() => {
                void logout().finally(() => {
                  window.location.assign("/");
                });
              }}
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
          {/* Le reglage des couleurs vit dans la barre d'outils cote admin
              (cf. `Toolbar`) : un bandeau de plus entre l'en-tete et le
              contenu etait mal place et sans rapport avec le reste
              (retour utilisateur 30/08/2026). */}
          {!readOnlyTarget && <PageHeader vue={activeTab} payload={appPayload} />}

          {readOnlyTarget && appPayload && (
            <header className="readonly-banner">
              <h1>
                {readOnlyTarget === "prof"
                  ? `Planning de ${appPayload.teacherLabels[route.prof] ?? route.prof}`
                  : readOnlyTarget === "promo"
                    ? "Vue Promo — toutes les promotions"
                    : readOnlyTarget === "salles-libres"
                      ? "Occupation des salles"
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
              {/* Sans effet sur le tableau d'occupation (aucune couleur par
                  matière) — proposer ce réglage ici n'y ferait rien voir de
                  différent, autant ne pas l'offrir. */}
              {readOnlyTarget !== "salles-libres" && <ReglageCouleurs prefs={prefs} setPrefs={setPrefs} />}
            </header>
          )}

          {panne && <BandeauPanne onReessayer={reessayer} />}
          {estAdmin && sante?.status === "degraded" && <BandeauServeurDegrade detail={sante.detail} />}

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
        {/* Un écran qui plante n'emporte plus toute la page (audit du
            29/09/2026, P1-13) : la navigation reste utilisable, et changer
            d'écran efface l'erreur. */}
        <ErrorBoundary cle={activeTab}>
        {activeTab === "semaine" && !readOnlyTarget && (
          // Vue Semaine, refonte du 29/09/2026 : barre d'outils en deux lignes
          // (quoi / quand), grille pleine largeur, détail de la séance choisie
          // en tête de la colonne de droite. Styles : `components/Toolbar.css`.
          <div className="view semaine">
            <Toolbar
              year={year}
              parcours={parcours}
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
              teacherLabels={appPayload?.teacherLabels}
              onYearChange={handleYearChange}
              onParcoursChange={handleParcoursChange}
              onWeekChange={setDisplayWeek}
              onViewModeChange={setViewMode}
              couleursParMatiere={prefs.couleursParMatiere}
              onCouleursChange={(parMatiere) =>
                setPrefs(ecrirePreferences({ couleursParMatiere: parMatiere, repondu: true }))
              }
              onGroupChange={setGroupId}
              onTeacherChange={setTeacherCode}
              onRoomChange={setRoomId}
            />

            <div className="semaine-layout">
              <section className="panel semaine-grille" aria-label="Planning de la semaine">
                <div className="semaine-grille-entete">
                  <p className="semaine-compte">
                    {visiblePlacements.length} séance{visiblePlacements.length > 1 ? "s" : ""} cette semaine
                    {selected ? "" : " · cliquez une séance pour son détail"}
                  </p>
                  {!prefs.couleursParMatiere && (
                    <ul className="semaine-legende" aria-label="Types de séance">
                      <li className="cm" title="Cours magistral : toute la promo, sur les deux colonnes">CM</li>
                      <li className="td" title="Travaux dirigés : les deux groupes TP, sur les deux colonnes">TD</li>
                      <li className="tp" title="Travaux pratiques : une colonne par groupe TP">TP</li>
                      <li className="eval">Évaluation / SAE</li>
                    </ul>
                  )}
                </div>

                {narrow && viewMode === "group" && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

                {placements.length === 0 ? (
                  <EtatPlanningVide etat={panne ? "echec" : etatPlanning} />
                ) : solverWeek === null ? (
                  <div className="empty-state">
                    <p>Semaine fermée (vacances). Choisissez une autre semaine.</p>
                  </div>
                ) : (viewMode === "teacher" && !teacherCode) || (viewMode === "room" && !roomId) ? (
                  <div className="empty-state">
                    <p>
                      Choisissez {viewMode === "teacher" ? "un enseignant" : "une salle"} dans la barre ci-dessus pour
                      afficher sa semaine.
                    </p>
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
                    selectedId={selected?.session_id ?? null}
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

              <aside className="semaine-cote">
                {/* QualityPanel (indicateurs) et RegenPanel (régénération
                    ciblée) retirés (retour utilisateur 28/08/2026), puis
                    supprimés du code le 29/09/2026. */}
                <SessionPanel
                  placement={selected}
                  onClose={() => setSelected(null)}
                  onUpdated={handlePlacementUpdated}
                  onError={setError}
                  weekRows={weekRows}
                  weekDates={weekDates}
                  groupLabels={groupLabels}
                  teacherLabels={appPayload?.teacherLabels}
                  onOuvrirPromo={(p) => setRoute({ vue: "promo", sem: p.week, jour: p.day })}
                />
                <DiffPanel
                  diff={diff}
                  analysis={analysis}
                  onApplyFeedback={handleApplyFeedback}
                  onExportCsv={handleExportCsv}
                  onExportJson={handleExportJson}
                  loading={loading}
                  weekRows={weekRows}
                  onAllerSemaine={setDisplayWeek}
                />
              </aside>
            </div>
          </div>
        )}
        {activeTab !== "semaine" &&
          activeTab !== "promo" &&
          activeTab !== "comptes" &&
          activeTab !== "celcat" &&
          activeTab !== "sauvegardes" &&
          activeTab !== "mcp" &&
          !appPayload && <EtatPlanningVide etat={etatPlanning} />}

        {activeTab === "groupe" && appPayload && (
          <GroupeView
            payload={appPayload}
            route={route}
            setRoute={setRoute}
            readOnly={readOnlyTarget === "groupe"}
            onOpenSearch={() => setSearch(true)}
          />
        )}
        {activeTab === "prof" && appPayload && (
          <EnseignantView
            payload={appPayload}
            route={route}
            setRoute={setRoute}
            readOnly={readOnlyTarget === "prof"}
            onOpenSearch={() => setSearch(true)}
          />
        )}
        {activeTab === "cours" && appPayload && !readOnlyTarget && (
          <CoursView
            payload={appPayload}
            route={route}
            setRoute={setRoute}
            onOpenSearch={() => setSearch(true)}
          />
        )}
        {activeTab === "salle" && appPayload && !readOnlyTarget && (
          <SalleView
            payload={appPayload}
            route={route}
            setRoute={setRoute}
            onOpenSearch={() => setSearch(true)}
          />
        )}
        {activeTab === "salles-libres" && appPayload && (!readOnlyTarget || readOnlyTarget === "salles-libres") && (
          <SallesLibresView
            payload={appPayload}
            route={route}
            setRoute={setRoute}
            readOnly={readOnlyTarget === "salles-libres"}
          />
        )}
        {activeTab === "promo" && appPayload && (!readOnlyTarget || readOnlyTarget === "promo") && (
          <PromoView
            payload={appPayload}
            route={route}
            readOnly={readOnlyTarget === "promo"}
            // Lien public (retour utilisateur 31/08/2026) : aucun de ces
            // callbacks n'est passé — `readOnly` seul suffirait déjà (il
            // coupe tout à l'intérieur du composant), mais ne pas les
            // fournir du tout retire toute tentation d'appui sur eux si
            // jamais ce garde-fou venait à être retiré par erreur plus tard.
            {...(readOnlyTarget === "promo"
              ? {}
              : {
                  placements: promoPlacements,
                  onPlacementUpdated: handlePlacementUpdated,
                  onError: (msg: string) => setNotice(msg),
                  onSeanceChangee: () => {
                    void refreshAppState();
                    void loadPromoTimetable();
                  },
                  setRoute,
                  onAPlacerRefresh: () => {
                    void loadTimetable();
                    void loadPromoTimetable();
                    void refreshAppState();
                  },
                })}
          />
        )}
        {activeTab === "promo" && !appPayload && !readOnlyTarget && (
          <APlacerView onPlacement={() => void loadTimetable()} payload={null} />
        )}
        {activeTab === "reference" && appPayload && !readOnlyTarget && (
          <ReferenceView payload={appPayload} setRoute={setRoute} />
        )}
        {activeTab === "contraintes" && appPayload && !readOnlyTarget && (
          <ContraintesView payload={appPayload} setRoute={setRoute} />
        )}
        {activeTab === "apf" && appPayload && !readOnlyTarget && <TodoView payload={appPayload} setRoute={setRoute} />}
        {activeTab === "taches" && appPayload && !readOnlyTarget && (
          <KanbanView payload={appPayload} role={moi?.role} setRoute={setRoute} />
        )}
        {activeTab === "comptes" && !readOnlyTarget && moi?.role === "admin" && <AdminUsersView />}
        {activeTab === "celcat" && !readOnlyTarget && moi?.role === "admin" && <AdminCelcatView />}
        {activeTab === "sauvegardes" && !readOnlyTarget && moi?.role === "admin" && <SauvegardesView />}
        {activeTab === "mcp" && !readOnlyTarget && moi?.status === "active" && <McpKeysView />}
        </ErrorBoundary>
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


/** Pas (encore) de planning à montrer — en disant pourquoi : chargement en
 *  cours, aucun planning côté serveur, ou serveur injoignable. Avant, une
 *  panne s'affichait « Aucun planning résolu » (audit du 29/09/2026, P1-13). */
function EtatPlanningVide({ etat }: { etat: "chargement" | "charge" | "absent" | "echec" }) {
  if (etat === "echec") {
    return (
      <div className="empty-state">
        <p>Le planning n'a pas pu être chargé : le serveur ne répond pas.</p>
        <p className="muted">Nouvelle tentative automatique — rien n'est perdu.</p>
      </div>
    );
  }
  if (etat === "chargement") {
    return (
      <div className="empty-state" aria-busy="true">
        <p>Chargement du planning…</p>
      </div>
    );
  }
  return (
    <div className="empty-state">
      <p>Aucun planning résolu.</p>
      <p className="muted">Le planning se génère en ligne de commande (cal-iut solve / load-run), puis rechargez cette page.</p>
    </div>
  );
}

/** Réglage des couleurs, gardé accessible après le premier choix : une
 *  préférence qu'on ne peut plus changer est un piège.
 *
 *  Un `<select>` et non une bascule maison — retour utilisateur 30/08/2026 :
 *  « le sélecteur n'est pas du tout dans la DA du reste, fais juste un select
 *  au pire ». Le `select` garde le style commun des champs ; seule sa place
 *  dans le bandeau est réglée (`.prefs-reglage`, app.css). */
function ReglageCouleurs({
  prefs,
  setPrefs,
}: {
  prefs: Preferences;
  setPrefs: (p: Preferences) => void;
}) {
  return (
    <div className="prefs-reglage">
      <label>
        <span>Couleurs</span>
        <select
          value={prefs.couleursParMatiere ? "matiere" : "type"}
          onChange={(e) =>
            setPrefs(
              ecrirePreferences({ couleursParMatiere: e.target.value === "matiere", repondu: true }),
            )
          }
        >
          <option value="type">Couleurs par type</option>
          <option value="matiere">Couleurs par matière</option>
        </select>
      </label>
    </div>
  );
}
