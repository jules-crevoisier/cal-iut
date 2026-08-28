"""API REST FastAPI — générateur d'emplois du temps IUT MMI Troyes."""

import threading
import uuid
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cal_iut.api import auth, forced_pending, mailer
from cal_iut.api.regen import RegenError, regen_and_persist, resolve_semestre
from cal_iut.api.schemas import (
    DiffEntryResponse,
    DiffResponse,
    ExceptionCreateRequest,
    ExceptionResponse,
    FeedbackAnalysisResponse,
    ForcagePedagogiqueResponse,
    GroupMeta,
    IngestRequest,
    LoginRequest,
    MetaResponse,
    MoveSessionRequest,
    PlacementResponse,
    QualityResponse,
    RegenRequest,
    RegenResultResponse,
    CompletionResponse,
    CreneauLibreResponse,
    CreneauxLibresResponse,
    RoomMeta,
    SeanceAPlacerResponse,
    SeancePlaceeAutoResponse,
    SeanceRefuseeResponse,
    SeancesAPlacerResponse,
    SendTeacherMailsRequest,
    SendTeacherMailsResponse,
    SlotSuggestionResponse,
    SolveRequest,
    TeacherMailPreviewListResponse,
    TeacherMailPreviewResponse,
    TeacherMailSendResultResponse,
    TimetableResponse,
    ValidationResponse,
    WeightsResponse,
    YearMeta,
)
from cal_iut.api.state import get_repo, get_state
from cal_iut.api.validation import suggest_alternative_slots, validate_move
from cal_iut.calendar.academic import semester_week_offset, week_status
from cal_iut.db.models import CurrentPlacement
from cal_iut.export.formatter import build_export_rows, to_csv, to_json
from cal_iut.export.html_view import build_and_render
from cal_iut.feedback.weights import analyze_corrections, apply_learned_weights
from cal_iut.ingestion.config_loader import (
    load_groups,
    load_objective_weights,
    load_room_assignment_rules,
    load_rooms,
    load_room_reservations,
    load_teacher_availability,
    load_teacher_duos,
)
from cal_iut.ingestion.constraints_loader import load_all_constraints, merge_teacher_availability
from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR, run_ingestion
from cal_iut.models.entities import Group
from cal_iut.models.group_scope import expand_group_filter, related_group_ids
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.cpsat import PlacedSession, SolverConfig, TimetableSolver
from cal_iut.solver.quality import compute_quality
from cal_iut.solver.rooms import PlacedSessionWithRoom, _build_conflict_map, assign_rooms, parse_room_rules

def _export_semestre(state) -> str:
    """Semestre servant de référence temporelle à l'export (dates, numéros de
    semaine). Même résolution que la régénération, réutilisée telle quelle."""
    from cal_iut.api.regen import resolve_semestre

    return resolve_semestre(state)


YEAR_DEFINITIONS: list[tuple[int, str, list[str]]] = [
    (1, "1re année (S1–S2)", ["S1", "S2"]),
    (2, "2e année (S3–S4)", ["S3", "S4"]),
    (3, "3e année (S5–S6)", ["S5", "S6"]),
]


def _parcours_for_year(parcours_list: list[str], year: int) -> list[str]:
    prefix = f"BUT{year}"
    return sorted(p for p in parcours_list if p == prefix or p.startswith(f"{prefix}-"))

CONFIG_DIR = Path(__file__).resolve().parents[3] / "data" / "config"
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

app = FastAPI(title="cal-iut API", version="1.0.0")


@dataclass
class SolveJob:
    """
    Suivi d'un `/solve` lancé en arrière-plan (`POST /solve/async`). Un seul
    job actif à la fois — cohérent avec l'état applicatif global (un seul
    `AppState`, pas de session par utilisateur) : lancer un 2e job pendant
    qu'un premier tourne remplacerait le même état partagé de toute façon,
    donc autant l'interdire explicitement plutôt que produire une course.
    """

    job_id: str
    status: str  # "running" | "done" | "error"
    result: object = None  # TimetableResponse une fois terminé
    error_detail: str | None = None
    error_status: int = 500


_job_lock = threading.Lock()
_current_job: SolveJob | None = None


@dataclass
class RegenJob:
    """Suivi d'un `POST /regen/week` — même patron que `SolveJob`."""

    job_id: str
    status: str  # "running" | "done" | "error"
    result: object = None  # RegenResultResponse une fois terminé
    error_detail: str | None = None
    error_status: int = 500


_current_regen_job: RegenJob | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chemins d'API réels (mêmes préfixes que le proxy de dev Vite,
# `frontend/vite.config.ts`) — tout ce qui n'est PAS ici (page HTML, JS/CSS
# buildés, favicon...) reste servi sans authentification : sans ça, le
# formulaire de mot de passe lui-même ne pourrait jamais s'afficher.
_PROTECTED_PREFIXES = (
    "/app-state", "/corrections", "/diff", "/exceptions", "/export",
    "/feedback", "/ics", "/ingest", "/legacy", "/mail", "/meta", "/placements",
    "/regen", "/sessions", "/solve", "/timetable", "/weeks", "/weights",
)


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith(_PROTECTED_PREFIXES):
        return await call_next(request)

    password = auth.get_password()
    if not password:
        # Volontairement un blocage total, pas un accès libre — un
        # `CAL_IUT_PASSWORD` non configuré à un vrai déploiement est une
        # erreur de configuration, jamais silencieusement "pas de mot de
        # passe" (retour utilisateur : « met moi un mot de passe... qui
        # bloque l'entrée »).
        return JSONResponse(status_code=503, content={"detail": "Authentification non configurée (CAL_IUT_PASSWORD absent)."})

    # Lien personnel (prof ou groupe) — public depuis le 28/08/2026, cf.
    # docstring de `auth.py` pour l'historique (jeton HMAC d'abord, puis
    # "on s'en fiche on veut qu'il soit public" en retour utilisateur final).
    if auth.verify_personal_link_param(request.query_params.get("t")):
        return await call_next(request)
    if auth.verify_session_token(request.cookies.get(auth.SESSION_COOKIE)):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "Authentification requise."})


def require_admin_session(request: Request) -> None:
    """Garde-fou supplémentaire pour `/mail/*` : la vraie session (mot de
    passe partagé) est exigée, un simple jeton prof ne suffit PAS ici — à
    la différence du reste de `_PROTECTED_PREFIXES`. Un jeton prof donne un
    accès en LECTURE à son propre planning (limite déjà documentée,
    `auth.py`), mais ne doit jamais pouvoir, à lui seul, déclencher un envoi
    de mail à TOUS les collègues (`require_auth` a déjà laissé passer la
    requête à ce stade — ceci resserre spécifiquement pour cette action)."""
    if not auth.verify_session_token(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(401, "Session administrateur requise pour cette action.")


@app.post("/auth/login")
def auth_login(body: LoginRequest, response: Response) -> dict:
    password = auth.get_password()
    if not password or body.password != password:
        raise HTTPException(401, "Mot de passe incorrect.")
    response.set_cookie(
        auth.SESSION_COOKIE, auth.make_session_token(),
        max_age=auth.SESSION_MAX_AGE_S, httponly=True, samesite="lax",
    )
    return {"ok": True}


@app.post("/auth/logout")
def auth_logout(response: Response) -> dict:
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/auth/status")
def auth_status(request: Request) -> dict:
    return {"authenticated": auth.verify_session_token(request.cookies.get(auth.SESSION_COOKIE))}


@app.on_event("startup")
def startup() -> None:
    state = get_state()
    state.config_dir = CONFIG_DIR
    state.groups = load_groups(CONFIG_DIR)
    state.rooms = load_rooms(CONFIG_DIR)
    state.room_rules = parse_room_rules(load_room_assignment_rules(CONFIG_DIR))
    state.room_reservations = load_room_reservations(CONFIG_DIR, state.calendar)
    state.teacher_duos = load_teacher_duos(CONFIG_DIR)

    yaml_teachers = load_teacher_availability(CONFIG_DIR)
    project_root = CONFIG_DIR.parents[1]
    bundle = load_all_constraints(project_root)
    state.calendar = bundle.calendar
    state.student_presences = bundle.student_presences
    state.teacher_availability = merge_teacher_availability(yaml_teachers, bundle.teachers)

    # Référent SAE = très peu disponible ces jours-là pour un cours classique
    # (retour utilisateur 11/08/2026, cf. docs/DATA.md §48.2/§49) — augmenté
    # ICI, une seule fois au démarrage, pour que le glisser-déposer manuel
    # (`_teacher_availability_violations`) en tienne compte exactement comme
    # le solveur (même fonction `augment_teacher_availability_with_sae_supervision`).
    # Sur TOUS les semestres connus (pas seulement le groupe actuellement
    # chargé) : l'état applicatif peut changer de scope via `/ingest` sans
    # redémarrage, cette augmentation doit rester valable dans tous les cas.
    from cal_iut.ingestion.constraints_loader import (
        augment_teacher_availability_with_sae_supervision as _augment_sae,
    )
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUPS
    from cal_iut.ingestion.planning_loader import (
        load_mmi_planning_for_semestres,
        sae_supervisor_dates_by_teacher,
    )

    all_semestres = sorted({s for group in SEMESTRE_GROUPS.values() for s in group})
    planning_all = load_mmi_planning_for_semestres(project_root, all_semestres)
    supervisor_dates = sae_supervisor_dates_by_teacher(planning_all)
    state.teacher_availability = _augment_sae(state.teacher_availability, supervisor_dates)

    repo = get_repo()
    db_weights = repo.weights_as_dict()
    yaml_weights = load_objective_weights(CONFIG_DIR)
    state.objective_weights = {**yaml_weights, **db_weights}

    _try_restore_latest(state)


def _try_restore_latest(state: object) -> None:
    repo = get_repo()
    run = repo.get_latest_run()
    if not run:
        return
    state.current_run_id = run.id

    # Run global multi-parcours restauré depuis la DB : `PlanningRun.parcours`/
    # `.semestre` ne sont pas nullable (pas de migration de schéma pour ça),
    # donc encodés via un sentinel reconnu dans `semestre` (cf.
    # `scratchpad/load_group_a_to_db.py` — script one-off, pas dans le repo —
    # qui sauvegarde `semestre="ODD"`/`"EVEN"` pour un run `--semestre-group`).
    semestre_group = run.semestre.lower() if run.semestre in ("ODD", "EVEN") else None
    if semestre_group:
        state.filter_parcours = None
        state.filter_semestre = None
        state.semestre_group = semestre_group
    else:
        state.filter_parcours = run.parcours
        state.filter_semestre = run.semestre
        state.semestre_group = None

    try:
        result = run_ingestion(
            state.config_dir,
            parcours=state.filter_parcours,
            semestre=state.filter_semestre,
            semestre_group=semestre_group,
        )
        state.sessions = result.sessions
        state.courses = result.courses
        state.sessions_by_id = {s.id: s for s in result.sessions}

        current = repo.db.query(CurrentPlacement).filter_by(run_id=run.id).all()
        if current:
            state.timetable = [
                PlacedSessionWithRoom(
                    session_id=c.session_id,
                    week=c.week,
                    day=c.day,
                    slot=c.slot,
                    course_code=c.course_code,
                    group_ids=state.sessions_by_id[c.session_id].group_ids if c.session_id in state.sessions_by_id else [],
                    teacher_codes=state.sessions_by_id[c.session_id].teacher_codes if c.session_id in state.sessions_by_id else [],
                    room_id=c.room_id,
                    room_label=c.room_label,
                )
                for c in current
            ]
            for c in current:
                s = state.sessions_by_id.get(c.session_id)
                if s:
                    s.locked = c.locked
    except Exception:
        pass



@dataclass
class _AppContext:
    """Tout ce dont `build_payload` a besoin, calculé une seule fois et
    partagé entre `/app-state` (JSON, consommé par le frontend React) et
    `/legacy` (page HTML/JS historique) — même donnée, deux présentations."""

    timetable_dict: dict[str, object]
    semestre: str | None
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None
    planning_events: list[dict[str, object]] | None
    planning_event_slots: list[dict[str, object]] | None
    exceptions: list[dict[str, object]]
    sae_supervisor_dates: dict[str, set] | None = None


def _build_app_context(state: object) -> _AppContext:
    if not state.timetable:
        raise HTTPException(404, "Aucun planning résolu — lancez POST /ingest puis POST /solve d'abord")

    timetable_dict = {
        "status": state.last_status or "CACHED",
        "objective_value": state.last_objective_value,
        "gap_penalty": state.last_gap_penalty,
        "placements": [
            {
                "session_id": p.session_id,
                "week": p.week,
                "day": p.day,
                "slot": p.slot,
                "course_code": p.course_code,
                "group_ids": p.group_ids,
                "teacher_codes": p.teacher_codes,
                "room_id": getattr(p, "room_id", None),
                "room_label": getattr(p, "room_label", None),
            }
            for p in state.timetable
        ],
    }

    sae_days_by_course = None
    planning_events = None
    planning_event_slots = None
    sae_supervisor_dates = None
    semestre = state.filter_semestre or (SEMESTRE_GROUP_ANCHOR.get(state.semestre_group) if state.semestre_group else None)
    if not semestre and state.sessions:
        semestre = state.sessions[0].semestre
    if semestre:
        from cal_iut.calendar.academic import semester_week_offset
        from cal_iut.ingestion.planning_loader import (
            load_mmi_planning_for_semestres,
            planning_events_as_week_day_slots,
            planning_events_as_week_days,
            sae_supervisor_dates_by_teacher,
            sae_windows_as_week_days,
        )

        week_offset = semester_week_offset(state.calendar, semestre)
        n_weeks = (max((p.week for p in state.timetable), default=-1)) + 1
        # cf. docs/DATA.md §37 : `semestre` n'est que l'ancre du groupe
        # multi-parcours ("S1" pour odd) — charger tous les semestres réels
        # présents, sinon BUT2/BUT3 n'ont ni SAE ni événements affichés.
        real_semestres = sorted({s.semestre for s in state.sessions}) or [semestre]
        planning = load_mmi_planning_for_semestres(state.config_dir.parents[1], real_semestres)
        sae_days_by_course = sae_windows_as_week_days(
            planning, state.calendar.date_to_week_day, week_offset, n_weeks
        )
        planning_events = planning_events_as_week_days(
            planning, state.calendar.date_to_week_day_any, week_offset, n_weeks
        )
        planning_event_slots = planning_events_as_week_day_slots(
            planning, state.calendar.date_to_week_day_any, week_offset, n_weeks
        )
        # Distingue, dans les violations enseignant affichées, un compromis
        # MOU accepté (référent SAE ce jour-là) d'une vraie indisponibilité
        # déclarée non respectée — cf. `_teacher_payload`, docs/DATA.md §59.
        sae_supervisor_dates = sae_supervisor_dates_by_teacher(planning)

    repo = get_repo()
    exceptions = [_exception_to_response(r).model_dump() for r in repo.list_exceptions(active_only=True)]

    return _AppContext(
        timetable_dict=timetable_dict,
        semestre=semestre,
        sae_days_by_course=sae_days_by_course,
        planning_events=planning_events,
        planning_event_slots=planning_event_slots,
        exceptions=exceptions,
        sae_supervisor_dates=sae_supervisor_dates,
    )


@app.get("/app-state")
def app_state() -> dict[str, object]:
    """
    Tout l'état applicatif en JSON — même calcul (`build_payload`) que celui
    embarqué dans la page `/legacy`, exposé ici comme API pour le frontend
    React (retour utilisateur 11/08/2026 : « je veux react en local, passe
    toutes les fonctionnalités en local »). Source de vérité UNIQUE : les
    vérifications (contraintes, SAE, violations enseignant) restent calculées
    côté serveur, jamais redérivées côté client — cf. philosophie du projet
    (« jamais une affirmation pré-écrite »).
    """
    state = get_state()
    ctx = _build_app_context(state)
    from cal_iut.export.html_view import build_payload
    from cal_iut.ingestion.config_loader import load_teacher_contacts

    return build_payload(
        ctx.timetable_dict,
        state.sessions,
        state.groups,
        calendar=state.calendar,
        semestre=ctx.semestre,
        teacher_availability=state.teacher_availability,
        sae_days_by_course=ctx.sae_days_by_course,
        rooms=state.rooms,
        planning_events=ctx.planning_events,
        planning_event_slots=ctx.planning_event_slots,
        exceptions=ctx.exceptions,
        teacher_contacts=load_teacher_contacts(state.config_dir),
        sae_supervisor_dates=ctx.sae_supervisor_dates,
    )


@app.get("/legacy", response_class=HTMLResponse)
def timetable_view() -> HTMLResponse:
    """
    Page HTML/JS historique (même rendu que `cal-iut export --format html`),
    générée en direct depuis l'état courant du serveur. Conservée en accès
    direct pour qui préfère cette présentation ou veut vérifier un rendu
    identique à un fichier exporté ; l'interface par défaut est désormais le
    frontend React servi à `/` (retour utilisateur 11/08/2026).
    """
    state = get_state()
    ctx = _build_app_context(state)
    from cal_iut.ingestion.config_loader import load_teacher_contacts

    html = build_and_render(
        ctx.timetable_dict,
        state.sessions,
        state.groups,
        calendar=state.calendar,
        semestre=ctx.semestre,
        teacher_availability=state.teacher_availability,
        sae_days_by_course=ctx.sae_days_by_course,
        rooms=state.rooms,
        planning_events=ctx.planning_events,
        planning_event_slots=ctx.planning_event_slots,
        exceptions=ctx.exceptions,
        teacher_contacts=load_teacher_contacts(state.config_dir),
        sae_supervisor_dates=ctx.sae_supervisor_dates,
    )
    return HTMLResponse(html)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/meta", response_model=MetaResponse)
def get_meta() -> MetaResponse:
    state = get_state()
    parcours_list = sorted({g.parcours for g in state.groups})
    # Même filtre que le payload de l'interface (cf. `html_view.build_payload`) :
    # un groupe sans aucune séance n'est pas proposé — cas des groupes TP des
    # cohortes à groupe unique, conservés côté solveur mais dont toutes les
    # séances sont émises en TD sur le groupe TD.
    groups_with_sessions = {gid for s in state.sessions for gid in s.group_ids}
    visible_groups = [g for g in state.groups if g.kind == "promo" or g.id in groups_with_sessions] or state.groups
    return MetaResponse(
        groups=[
            GroupMeta(
                id=g.id,
                label=g.label,
                parcours=g.parcours,
                kind=g.kind,
                related_ids=related_group_ids(g, state.groups),
                annee=g.annee,
            )
            for g in visible_groups
        ],
        rooms=[RoomMeta(id=r.id, label=r.label, capacity=r.capacity, room_type=r.room_type.value) for r in state.rooms],
        parcours=parcours_list,
        semestres=["S1", "S2", "S3", "S4", "S5", "S6"],
        years=[
            YearMeta(
                id=year_id,
                label=label,
                semestres=semestres,
                parcours=_parcours_for_year(parcours_list, year_id),
            )
            for year_id, label, semestres in YEAR_DEFINITIONS
        ],
    )


@app.get("/weights", response_model=WeightsResponse)
def get_weights() -> WeightsResponse:
    repo = get_repo()
    w = repo.get_or_create_weights()
    return WeightsResponse(weights=repo.weights_as_dict(), reason=w.reason)


@app.post("/ingest")
def ingest(body: IngestRequest) -> dict[str, object]:
    state = get_state()
    result = run_ingestion(
        state.config_dir,
        parcours=body.parcours,
        semestre=body.semestre,
        semestre_group=body.semestre_group,
    )
    state.sessions = result.sessions
    state.courses = result.courses
    state.sessions_by_id = {s.id: s for s in result.sessions}
    state.filter_parcours = body.parcours
    state.filter_semestre = body.semestre
    state.semestre_group = body.semestre_group
    return result.stats


@app.get("/sessions")
def list_sessions(parcours: str | None = None, semestre: str | None = None, group_id: str | None = None) -> list[dict[str, object]]:
    state = get_state()
    sessions = state.sessions
    if parcours:
        sessions = [s for s in sessions if s.parcours == parcours]
    if semestre:
        sessions = [s for s in sessions if s.semestre == semestre]
    if group_id:
        scope = expand_group_filter(group_id, state.groups)
        sessions = [s for s in sessions if scope.intersection(s.group_ids)]
    return [s.model_dump(mode="json") for s in sessions]


def _solve_and_persist(body: SolveRequest) -> TimetableResponse:
    """
    Cœur de `/solve` : même logique de résolution (mode paliers par défaut,
    identique quel que soit l'appelant) — extrait pour être réutilisée à la
    fois par l'endpoint synchrone et par le job asynchrone
    (`POST /solve/async`), sans dupliquer ni dégrader la résolution elle-même.
    """
    state = get_state()
    if not state.sessions:
        raise HTTPException(400, "Run POST /ingest first")

    unlocked = _filter_unlocked(state.sessions, body.parcours, body.semestre)
    locked = [s for s in state.sessions if s.locked]
    gap_weight = body.gap_weight or state.objective_weights.get("gap_penalty", 100)

    optimize_gaps = body.optimize_gaps and len(unlocked) <= 150
    solver = TimetableSolver(
        SolverConfig(weeks=body.weeks, gap_weight=gap_weight, optimize_gaps=optimize_gaps)
    )
    all_sessions = unlocked + locked
    if body.decomposed:
        solve_fn = solver.solve_decomposed
    elif body.legacy_weighted:
        solve_fn = solver.solve
    else:
        solve_fn = solver.solve_tiered

    # Run global multi-parcours : le semestre "ancre" (S1 pour odd, S2 pour
    # even) résout calendrier/horizon — les 3 semestres d'un même groupe le
    # partagent déjà par construction (cf. SEMESTRE_GROUPS).
    semestre_group = body.semestre_group or state.semestre_group
    resolved_semestre = body.semestre or state.filter_semestre
    if semestre_group and not resolved_semestre:
        resolved_semestre = SEMESTRE_GROUP_ANCHOR[semestre_group]

    try:
        result = solve_fn(
            all_sessions,
            state.teacher_availability,
            calendar=state.calendar,
            student_presences=state.student_presences,
            semestre=resolved_semestre,
            groups=state.groups,
            duos=state.teacher_duos,
        )
    except MemoryError:
        raise HTTPException(
            507,
            "Mémoire insuffisante pour le solveur — réessayez avec optimize_gaps=false",
        ) from None

    if result.status not in ("OPTIMAL", "FEASIBLE"):
        raise HTTPException(422, f"Solver failed: {result.status}")

    sessions_by_id = {s.id: s for s in all_sessions}
    placements = _merge_locked_placements(result.placements, locked, state.timetable)

    with_rooms = (
        assign_rooms(
            placements, sessions_by_id, state.rooms, state.groups, state.room_rules,
            state.teacher_duos, reserved=state.room_reservations,
        )
        if body.assign_rooms
        else [
            PlacedSessionWithRoom(
                session_id=p.session_id,
                week=p.week,
                day=p.day,
                slot=p.slot,
                course_code=p.course_code,
                group_ids=p.group_ids,
                teacher_codes=p.teacher_codes,
            )
            for p in placements
        ]
    )

    quality = compute_quality(placements, sessions_by_id)
    state.timetable = with_rooms
    state.sessions_by_id = sessions_by_id
    state.last_status = result.status
    state.last_objective_value = result.objective_value
    state.last_gap_penalty = result.gap_penalty

    repo = get_repo()
    run = repo.save_run(
        parcours=body.parcours or state.filter_parcours or "BUT1",
        semestre=body.semestre or state.filter_semestre or "S1",
        status=result.status,
        objective_value=result.objective_value,
        gap_penalty=result.gap_penalty,
        weeks=solver.config.weeks,  # résolu (calendrier) par solver.solve(), plus jamais None ici
        solver_placements=[_placement_dict(p) for p in with_rooms],
        current_placements=[_placement_dict(p, sessions_by_id) for p in with_rooms],
    )
    state.current_run_id = run.id

    return _build_response(result.status, result.objective_value, result.gap_penalty, with_rooms, sessions_by_id, quality, run.id)


@app.post("/solve", response_model=TimetableResponse)
def solve(body: SolveRequest) -> TimetableResponse:
    return _solve_and_persist(body)


@app.post("/solve/async")
def solve_async(body: SolveRequest) -> dict[str, str]:
    """
    Variante non bloquante de `/solve` : lance la même résolution (identique,
    aucune perte de qualité) dans un thread d'arrière-plan et rend la main
    immédiatement — utile car un run BUT1-S1 complet peut prendre jusqu'à
    900s (cf. docs/DATA.md §12.3), largement au-delà d'un timeout HTTP
    raisonnable. Suivre l'avancement via `GET /solve/status`.
    """
    global _current_job
    state = get_state()
    if not state.sessions:
        raise HTTPException(400, "Run POST /ingest first")

    with _job_lock:
        if _current_job is not None and _current_job.status == "running":
            raise HTTPException(409, f"Un solve est déjà en cours (job {_current_job.job_id})")
        job = SolveJob(job_id=str(uuid.uuid4()), status="running")
        _current_job = job

    def _worker() -> None:
        try:
            response = _solve_and_persist(body)
            job.result = response
            job.status = "done"
        except HTTPException as exc:
            job.error_detail = str(exc.detail)
            job.error_status = exc.status_code
            job.status = "error"
        except Exception as exc:  # sécurité : ne jamais laisser le job bloqué en "running"
            job.error_detail = str(exc)
            job.error_status = 500
            job.status = "error"

    threading.Thread(target=_worker, daemon=True, name=f"solve-{job.job_id}").start()
    return {"job_id": job.job_id, "status": "running"}


@app.get("/solve/status")
def solve_status(job_id: str | None = None) -> dict[str, object]:
    """Statut du dernier job `/solve/async` (ou d'un `job_id` précis)."""
    if _current_job is None or (job_id and job_id != _current_job.job_id):
        raise HTTPException(404, "Aucun job trouvé")
    job = _current_job
    if job.status == "done":
        return {"job_id": job.job_id, "status": "done", "result": job.result}
    if job.status == "error":
        return {"job_id": job.job_id, "status": "error", "error": job.error_detail}
    return {"job_id": job.job_id, "status": "running"}


@app.post("/regen/week")
def regen_week(body: RegenRequest) -> dict[str, str]:
    """
    Régénère UNE semaine future, ou cette semaine + la suivante
    (`extend_next`) — jamais une semaine passée/en cours (cf.
    `week_status`), jamais tout le semestre. Même patron asynchrone que
    `POST /solve/async` (thread + verrou global) : un recalcul même sur 2
    semaines reste de l'ordre de la minute.
    """
    global _current_regen_job
    state = get_state()
    if not state.timetable:
        raise HTTPException(400, "Aucun planning — lancez POST /solve d'abord")

    weeks = [body.week, body.week + 1] if body.extend_next else [body.week]

    with _job_lock:
        if _current_job is not None and _current_job.status == "running":
            raise HTTPException(409, f"Un solve est déjà en cours (job {_current_job.job_id})")
        if _current_regen_job is not None and _current_regen_job.status == "running":
            raise HTTPException(409, f"Une régénération est déjà en cours (job {_current_regen_job.job_id})")
        job = RegenJob(job_id=str(uuid.uuid4()), status="running")
        _current_regen_job = job

    def _worker() -> None:
        try:
            repo = get_repo()
            result = regen_and_persist(state, repo, weeks)
            job.result = RegenResultResponse(
                status=result.status,
                touched_weeks=result.touched_weeks,
                placements=[_to_placement(p, state.sessions_by_id) for p in result.placements],
                message=result.message,
            )
            job.status = "done"
        except RegenError as exc:
            job.error_detail = str(exc)
            job.error_status = 409
            job.status = "error"
        except Exception as exc:  # sécurité : ne jamais laisser le job bloqué en "running"
            job.error_detail = str(exc)
            job.error_status = 500
            job.status = "error"

    threading.Thread(target=_worker, daemon=True, name=f"regen-{job.job_id}").start()
    return {"job_id": job.job_id, "status": "running"}


@app.get("/regen/status")
def regen_status(job_id: str | None = None) -> dict[str, object]:
    """Statut du dernier job `/regen/week` (ou d'un `job_id` précis)."""
    if _current_regen_job is None or (job_id and job_id != _current_regen_job.job_id):
        raise HTTPException(404, "Aucun job trouvé")
    job = _current_regen_job
    if job.status == "done":
        return {"job_id": job.job_id, "status": "done", "result": job.result}
    if job.status == "error":
        return {"job_id": job.job_id, "status": "error", "error": job.error_detail}
    return {"job_id": job.job_id, "status": "running"}


@app.get("/weeks/status")
def weeks_status() -> list[dict[str, object]]:
    """Statut past/current/future de chaque semaine affichée — sert au
    rendu initial ET au ré-affichage léger après une action (déplacement/
    régénération), sans recharger toute la page."""
    state = get_state()
    if not state.timetable:
        return []
    semestre = resolve_semestre(state)
    n_weeks = (max((p.week for p in state.timetable), default=-1)) + 1
    return [{"week": w, "status": week_status(state.calendar, semestre, w)} for w in range(n_weeks)]


@app.post("/exceptions", response_model=ExceptionResponse)
def create_exception(body: ExceptionCreateRequest) -> ExceptionResponse:
    state = get_state()
    repo = get_repo()
    exc_date = _date.fromisoformat(body.exception_date)

    semestre = resolve_semestre(state)
    week_offset_mapped = state.calendar.date_to_week_day_any(exc_date)
    if week_offset_mapped is not None:
        rel_week = week_offset_mapped[0] - semester_week_offset(state.calendar, semestre)
        if week_status(state.calendar, semestre, rel_week) != "future":
            raise HTTPException(409, "Cette date tombe sur une semaine passée/en cours — non modifiable")

    row = repo.create_exception(
        kind=body.kind, exception_date=exc_date, teacher_code=body.teacher_code,
        room_id=body.room_id, slots=body.slots, reason=body.reason,
    )
    return _exception_to_response(row)


@app.get("/exceptions", response_model=list[ExceptionResponse])
def list_exceptions(active_only: bool = True) -> list[ExceptionResponse]:
    repo = get_repo()
    return [_exception_to_response(r) for r in repo.list_exceptions(active_only=active_only)]


@app.delete("/exceptions/{exception_id}")
def delete_exception(exception_id: int) -> dict[str, bool]:
    repo = get_repo()
    ok = repo.deactivate_exception(exception_id)
    if not ok:
        raise HTTPException(404, "Exception introuvable")
    return {"deleted": True}


def _exception_to_response(row) -> ExceptionResponse:
    return ExceptionResponse(
        id=row.id, kind=row.kind, exception_date=row.exception_date.isoformat(),
        teacher_code=row.teacher_code, room_id=row.room_id,
        slots=[int(s) for s in row.slots.split(",")] if row.slots else None,
        reason=row.reason, active=row.active,
    )


@app.get("/timetable", response_model=TimetableResponse)
def get_timetable(
    group_id: str | None = None,
    teacher_code: str | None = None,
    room_id: str | None = None,
    week: int | None = None,
) -> TimetableResponse:
    state = get_state()
    if not state.timetable:
        raise HTTPException(404, "No timetable — run POST /solve first")

    filtered = _filter_timetable(state.timetable, group_id, teacher_code, room_id, week, state.groups)
    quality = compute_quality(_as_placed(filtered), state.sessions_by_id)
    return _build_response("CACHED", None, 0, filtered, state.sessions_by_id, quality, state.current_run_id)


@app.get("/diff", response_model=DiffResponse)
def get_diff(run_id: int | None = None) -> DiffResponse:
    repo = get_repo()
    rid = run_id or get_state().current_run_id
    entries = repo.get_diff(rid)
    changed = [e for e in entries if e.changed]
    return DiffResponse(
        run_id=rid,
        total=len(entries),
        changed_count=len(changed),
        entries=[DiffEntryResponse(**e.__dict__) for e in entries if e.changed],
    )


@app.get("/feedback/analysis", response_model=FeedbackAnalysisResponse)
def feedback_analysis() -> FeedbackAnalysisResponse:
    repo = get_repo()
    analysis = analyze_corrections(repo.list_corrections())
    return FeedbackAnalysisResponse(**analysis)


@app.post("/feedback/apply")
def feedback_apply() -> dict[str, object]:
    repo = get_repo()
    result = apply_learned_weights(repo)
    if result.get("applied"):
        get_state().objective_weights = result["weights"]
    return result


@app.get("/export/json")
def export_json() -> list[dict[str, object]]:
    state = get_state()
    if not state.timetable:
        raise HTTPException(404, "No timetable")
    rows = build_export_rows(
        state.timetable, state.sessions_by_id,
        state.calendar, semester_week_offset(state.calendar, _export_semestre(state)),
    )
    return to_json(rows)


@app.get("/export/csv")
def export_csv() -> Response:
    state = get_state()
    if not state.timetable:
        raise HTTPException(404, "No timetable")
    rows = build_export_rows(
        state.timetable, state.sessions_by_id,
        state.calendar, semester_week_offset(state.calendar, _export_semestre(state)),
    )
    content = to_csv(rows)
    return Response(content=content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=emploi_du_temps.csv"})


def _ics_items_for_placements(state: object, placements: list) -> list:
    """`IcsItem` par placement — date calculée depuis le SEMESTRE PROPRE à
    chaque séance (pas un semestre de référence unique, cf. `ics_feed.py`
    pour pourquoi c'est important pour un flux personnel)."""
    from cal_iut.api.ics_feed import IcsItem
    from cal_iut.export.formatter import SLOT_TIMES as _ICS_SLOT_TIMES

    items = []
    for p in placements:
        session = state.sessions_by_id.get(p.session_id)
        semestre = getattr(session, "semestre", None) or _export_semestre(state)
        start, end = _ICS_SLOT_TIMES[p.slot] if 0 <= p.slot < len(_ICS_SLOT_TIMES) else ("", "")
        items.append(IcsItem(
            session_id=p.session_id,
            course_code=p.course_code,
            course_name=getattr(session, "course_name", "") if session else "",
            date=_date_iso(state, semestre, p.week, p.day),
            time_start=start,
            time_end=end,
            room_label=getattr(p, "room_label", None),
            group_ids=list(p.group_ids or []),
            teacher_codes=list(p.teacher_codes or []),
        ))
    return items


@app.get("/ics/prof/{code}.ics")
def ics_teacher(code: str) -> Response:
    """Flux .ics abonnable pour UN enseignant — cf. `api/ics_feed.py`."""
    state = get_state()
    placements = [p for p in state.timetable if code in (p.teacher_codes or [])]
    items = _ics_items_for_placements(state, placements)
    noms = _noms_enseignants(state)
    group_labels = {g.id: g.label for g in state.groups}
    from cal_iut.api.ics_feed import build_ics

    content = build_ics(items, noms.get(code, code), f"prof-{code}", group_labels, noms)
    return Response(
        content=content, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="planning-{code}.ics"'},
    )


@app.get("/ics/groupe/{group_id}.ics")
def ics_groupe(group_id: str) -> Response:
    """Flux .ics abonnable pour UN groupe (cohorte complète : CM promo + TD
    + TP jumelé, mêmes séances que sur son lien personnel) — cf.
    `api/ics_feed.py`."""
    from cal_iut.models.group_scope import expand_group_filter

    state = get_state()
    if not any(g.id == group_id for g in state.groups):
        raise HTTPException(404, f"Groupe {group_id} inconnu")
    cohort = expand_group_filter(group_id, state.groups)
    placements = [p for p in state.timetable if cohort.intersection(p.group_ids or [])]
    items = _ics_items_for_placements(state, placements)
    noms = _noms_enseignants(state)
    group_labels = {g.id: g.label for g in state.groups}
    label = group_labels.get(group_id, group_id)
    from cal_iut.api.ics_feed import build_ics

    content = build_ics(items, label, f"groupe-{group_id}", group_labels, noms)
    return Response(
        content=content, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="planning-{group_id}.ics"'},
    )


def _check_move_editable(state: object, session_id: str, source_week: int, dest_week: int) -> None:
    """
    Rejette un déplacement (manuel, glisser-déposer) touchant une semaine
    passée ou en cours — que ce soit la semaine SOURCE ou DESTINATION. Ce
    contrôle n'existait pas jusqu'ici sur l'endpoint unitaire (`PATCH
    /placements/{id}`), seule la régénération par lot (`/regen/week`) le
    faisait — retrofit nécessaire : un simple glisser-déposer aurait pu
    déplacer une séance déjà passée sans qu'aucun garde-fou ne l'empêche.
    """
    session = state.sessions_by_id.get(session_id)
    semestre = session.semestre if session else resolve_semestre(state)
    for w in {source_week, dest_week}:
        status = week_status(state.calendar, semestre, w)
        if status != "future":
            raise HTTPException(409, f"Semaine {w + 1} non modifiable (statut : {status})")


def _is_duo_synced(session: object, duos: list) -> bool:
    """Séance faisant partie d'un duo enseignant salle rare (WR110/112/113,
    cf. `add_duo_synchronized_rare_room_constraints`) : déplacer UNE moitié
    sans l'autre casse la synchronisation — pas de suggestion automatique
    possible dans ce cas (une régénération de semaine reste correcte)."""
    if not session or not duos:
        return False
    teacher_codes = set(session.teacher_codes or [])
    for duo in duos:
        if session.course_code in (duo.course_codes or []) and teacher_codes & set(duo.teacher_codes or []):
            return True
    return False


_DUO_SYNC_NOTE = (
    "Cette séance fait partie d'un binôme enseignant synchronisé sur une salle rare "
    "(cf. WR110/112/113) : la déplacer seule casserait la synchronisation avec l'autre "
    "moitié. Aucune suggestion automatique n'est proposée dans ce cas — utilisez la "
    "régénération de semaine, qui respecte cette contrainte."
)


def _resolve_room(state: object, session: object, week: int, day: int, slot: int, prefer_room_id: str | None) -> object | None:
    """Salle libre et adaptée à ce créneau (`find_room_for_slot`) — garde
    `prefer_room_id` si elle est encore libre, recalcule sinon plutôt que de
    bloquer sur un conflit de salle évitable (retour utilisateur : "si on
    modifie [le créneau] il faut recalculer [la salle]")."""
    from cal_iut.solver.rooms import find_room_for_slot

    # `state.timetable` DIRECTEMENT (pas `_as_placed`, qui construit des
    # `PlacedSession` sans champ `room_id` — bug réel trouvé le 06/08/2026 en
    # testant en conditions réelles : `find_room_for_slot` ne voyait alors
    # AUCUNE salle comme occupée et laissait passer un double-booking).
    return find_room_for_slot(
        session, week, day, slot, state.timetable, state.sessions_by_id,
        state.rooms, state.groups, state.room_rules, prefer_room_id=prefer_room_id,
        reserved=getattr(state, "room_reservations", None),
    )


def _hard_constraint_context(
    state: object, session: object
) -> tuple[set[tuple[int, int, int]], set[tuple[int, int, int]], set[int]]:
    """
    `(extra_blocked, extra_blocked_pedago, allowed_weeks)` pour une séance
    donnée — verrou jeudi PAC, jours SAE sanctuarisés, événements du planning
    officiel à horaire précis, ordre pédagogique. Réutilisé à la fois pour
    filtrer les suggestions ET pour bloquer RÉELLEMENT un déplacement qui
    violerait une de ces règles (cf. `_institutional_violations`/
    `_pedagogical_order_violations`, appelés depuis `move_session`/
    `validate_placement`/`placer_seance` — retour utilisateur : "vérifie bien
    toutes les contraintes avant que ça s'effectue". Avant ce correctif,
    ces règles ne servaient qu'à filtrer les suggestions ; un glisser-déposer
    direct sur une case arbitraire — hors suggestion — pouvait les violer
    sans qu'aucun garde-fou serveur ne l'empêche).

    `extra_blocked` (PAC, fin de semestre FI, présence alternant FC,
    événement planning officiel, SAE sanctuarisée) reste JAMAIS contournable.
    `extra_blocked_pedago`/`allowed_weeks` (ordre pédagogique CM/TD/TP) sont
    séparés depuis le 28/08/2026 (retour utilisateur : « on veut que si on
    appuie sur forcer cela soit bon et que le placement se fasse ») — un
    humain qui force ici sait qu'il place sciemment une séance hors de
    l'ordre de contenu attendu, à la différence des verrous institutionnels
    ci-dessus, qui n'ont jamais de bonne raison d'être cassés.
    """
    semestre = session.semestre
    from cal_iut.ingestion.planning_loader import (
        ALL_PARCOURS,
        load_mmi_planning,
        planning_event_blocked_slots_by_parcours,
        sae_group_labels_by_course,
        sae_windows_as_week_days,
    )
    from cal_iut.solver.constraints import sae_blocked_days_by_group, sae_blocked_days_by_parcours
    from cal_iut.solver.decomposed import FI_MAX_WEEK_DEFAULT, _build_sequence_neighbors, _movable_bounds

    week_offset = semester_week_offset(state.calendar, semestre)
    n_weeks = (max((p.week for p in state.timetable), default=-1)) + 1

    extra_blocked: set[tuple[int, int, int]] = set()

    # Jeudi après-midi réservé aux PAC — jamais pour la FC.
    if "FC" not in session.parcours:
        for week in range(n_weeks):
            for slot in (3, 4, 5):
                extra_blocked.add((week, 3, slot))

    # Fin de semestre FI (retour utilisateur 27/08/2026 : « les FI doivent
    # finir leur semestre le 1er février, les FC eux ont jusqu'au 12 mars »)
    # — jamais pour la FC, symétrique du verrou PAC ci-dessus. Trouvé le
    # même jour : `assign_weeks` respecte déjà cette borne dès la génération
    # (`fi_max_week`), mais ce chemin manuel (glisser-déposer, suggestions,
    # `cal-iut completer`) ne la connaissait pas du tout — une séance FI
    # manquante pouvait être "complétée" avec succès sur une semaine hors
    # délai, aussi silencieusement que les 76 séances FC placées hors
    # présence avant le correctif `alternance_presence` du même jour.
    if "FC" not in session.parcours:
        for week in range(FI_MAX_WEEK_DEFAULT + 1, n_weeks):
            for day in range(5):
                for slot in range(6):
                    extra_blocked.add((week, day, slot))

    # Alternants FC : présents à l'IUT seulement certains jours (calendrier
    # d'alternance). Le solveur l'impose comme contrainte DURE
    # (`add_student_presence_constraints`) ; ce chemin — placement manuel,
    # suggestions, complétion automatique — n'en avait AUCUNE connaissance
    # jusqu'au 27/08/2026, découvert en auditant un run complété : 76 séances
    # FC placées alors que les étudiants étaient en entreprise. Jamais
    # contournable, au même titre que le verrou PAC ci-dessus.
    if "FC" in session.parcours:
        presence = next(
            (p for p in (state.student_presences or []) if session.parcours in p.parcours_keys),
            None,
        )
        if presence and presence.presence_dates:
            from cal_iut.ingestion.constraints_loader import allowed_week_days_for_parcours

            allowed_days = allowed_week_days_for_parcours(presence, state.calendar, week_offset, n_weeks)
            if allowed_days:
                for week in range(n_weeks):
                    for day in range(5):
                        if (week, day) not in allowed_days:
                            for slot in range(6):
                                extra_blocked.add((week, day, slot))

    planning = load_mmi_planning(state.config_dir.parents[1], semestre)
    # Événements fixes : seuls ceux du parcours de la séance (ou sans parcours
    # déclaré) la bloquent — la rentrée BUT1 ne doit pas geler un créneau BUT3.
    event_blocked = planning_event_blocked_slots_by_parcours(
        planning, state.calendar.date_to_week_day_any, week_offset, n_weeks
    )
    extra_blocked |= event_blocked.get(ALL_PARCOURS, set())
    extra_blocked |= event_blocked.get(session.parcours, set())

    sae_days_by_course = sae_windows_as_week_days(planning, state.calendar.date_to_week_day, week_offset, n_weeks)
    sae_group_labels = sae_group_labels_by_course(planning)
    blocked_by_parcours = sae_blocked_days_by_parcours(
        state.sessions, sae_days_by_course, sae_group_labels
    )
    blocked_days = set(blocked_by_parcours.get(session.parcours, set()))
    if sae_group_labels:
        blocked_by_group = sae_blocked_days_by_group(
            state.sessions, sae_days_by_course, sae_group_labels, state.groups
        )
        for gid in session.group_ids:
            blocked_days |= blocked_by_group.get(gid, set())
    for w, d in blocked_days:
        for slot in range(6):
            extra_blocked.add((w, d, slot))

    # Ordre pédagogique : mêmes bornes que la régénération ciblée
    # (`_movable_bounds`, déjà utilisé par `api/regen.py`) — ne jamais
    # autoriser une semaine qui violerait l'ordre avec un voisin de séquence.
    # `state.groups` : sans lui, les suggestions de créneau proposeraient des
    # semaines qui placent un CM après les TD qu'il doit précéder (les paires
    # inter-granularités CM promo ↔ TD/TP de sous-groupe seraient ignorées).
    neighbors = _build_sequence_neighbors(state.sessions, state.groups)
    week_by_session = {p.session_id: p.week for p in state.timetable}
    lo, hi = _movable_bounds(session.id, neighbors, week_by_session, n_weeks)
    allowed_weeks = set(range(lo, hi + 1))

    # Affinage AU CRÉNEAU sur les deux semaines-limites, ajouté le 27/08/2026.
    # `_movable_bounds` ne borne qu'à la SEMAINE (résolution utilisée pour le
    # rééquilibrage, moins coûteuse) — mais l'ordre pédagogique se vérifie au
    # créneau précis (comparaison stricte, cf. `export/html_view.py::
    # _rule_checks`, comparaison `t_of[a] < t_of[b]`). Deux séances liées
    # peuvent légitimement PARTAGER une semaine ; il faut alors seulement
    # garantir que leur jour/créneau respecte encore le sens de la relation.
    #
    # Trouvé en auditant un run complété : 102 séances (« ordre pédagogique
    # CM→TD→TP ») et 111 paires (« vu par l'étudiant ») en semaine correcte
    # mais créneau incorrect — le placement manuel et la complétion
    # automatique acceptaient sans le savoir des créneaux « techniquement
    # dans les clous » côté semaine, mais chronologiquement à l'envers.
    from cal_iut.models.timetable import DAYS_PER_WEEK as _DPW
    from cal_iut.models.timetable import SLOTS_PER_DAY as _SPD

    preds, succs = neighbors.get(session.id, ([], []))
    placement_by_id = {p.session_id: p for p in state.timetable}
    extra_blocked_pedago: set[tuple[int, int, int]] = set()
    temps_preds_a_lo = [
        placement_by_id[pid].day * _SPD + placement_by_id[pid].slot
        for pid in preds
        if pid in placement_by_id and week_by_session.get(pid) == lo
    ]
    if temps_preds_a_lo:
        seuil = max(temps_preds_a_lo)
        for day in range(_DPW):
            for slot in range(_SPD):
                if day * _SPD + slot <= seuil:
                    extra_blocked_pedago.add((lo, day, slot))
    temps_succs_a_hi = [
        placement_by_id[sid].day * _SPD + placement_by_id[sid].slot
        for sid in succs
        if sid in placement_by_id and week_by_session.get(sid) == hi
    ]
    if temps_succs_a_hi:
        seuil = min(temps_succs_a_hi)
        for day in range(_DPW):
            for slot in range(_SPD):
                if day * _SPD + slot >= seuil:
                    extra_blocked_pedago.add((hi, day, slot))

    return extra_blocked, extra_blocked_pedago, allowed_weeks


def _institutional_violations(
    week: int, day: int, slot: int,
    extra_blocked: set[tuple[int, int, int]],
) -> list[str]:
    """
    Violations JAMAIS contournables via `force` (verrous institutionnels durs :
    jeudi PAC, fin de semestre FI, présence IUT d'un alternant FC, événement
    du planning officiel à horaire précis, journée SAE sanctuarisée) —
    distinct des conflits de ressources groupe/enseignant/salle (force-ables,
    un humain peut avoir une bonne raison de les outrepasser ponctuellement)
    ET de l'ordre pédagogique (`_pedagogical_order_violations`, lui aussi
    force-able depuis le 28/08/2026) : casser un verrou institutionnel n'a
    jamais de bonne raison, casser l'ordre pédagogique peut légitimement en
    avoir une (retour utilisateur explicite).
    """
    violations: list[str] = []
    if (week, day, slot) in extra_blocked:
        violations.append(
            "Créneau institutionnellement bloqué (jeudi après-midi PAC, fin de semestre, "
            "journée SAE sanctuarisée, événement du planning officiel à cet horaire précis, "
            "ou présence IUT d'un alternant) — non modifiable, même en forçant."
        )
    return violations


def _pedagogical_order_violations(
    week: int, day: int, slot: int,
    extra_blocked_pedago: set[tuple[int, int, int]], allowed_weeks: set[int],
) -> list[str]:
    """
    Violations d'ordre pédagogique (CM/TD/TP doivent rester dans le bon
    ordre de contenu par rapport à leurs voisins de séquence) — contournables
    via `force` depuis le 28/08/2026 (retour utilisateur : « on veut que si
    on appuie sur forcer cela soit bon et que le placement se fasse »), à la
    différence des verrous institutionnels (`_institutional_violations`),
    qui eux restent définitivement non contournables. Un humain qui force
    ici sait qu'il place sciemment une séance hors de l'ordre de contenu
    attendu (ex. avant le TD qui doit la précéder).
    """
    violations: list[str] = []
    if (week, day, slot) in extra_blocked_pedago:
        violations.append(
            "Ordre pédagogique : ce créneau précis contredit une séance voisine du "
            "même cours déjà placée dans la même semaine (contenu attendu avant/après)."
        )
    if allowed_weeks and week not in allowed_weeks:
        violations.append(
            "Ordre pédagogique : cette semaine contredit une séance voisine du "
            "même cours (contenu attendu avant/après)."
        )
    return violations


def _teacher_availability_violations(state: object, session: object, week: int, day: int, slot: int) -> list[str]:
    """
    Indisponibilité enseignant DÉCLARÉE — récurrente, dates précises, liste
    blanche, parité de semaine, ET supervision SAE (`state.teacher_availability`
    augmenté une fois au démarrage, cf. `startup()`) — jamais contournable via
    `force`, au même titre que le verrou PAC/SAE/ordre pédagogique : un humain
    n'a jamais de bonne raison de placer un cours chez un enseignant qui a
    explicitement signalé son indisponibilité ce jour-là (retour utilisateur
    11/08/2026 : "vérifie bien toutes les contraintes avant que ça
    s'effectue"). Avant ce correctif, ces indisponibilités ne servaient qu'à
    FILTRER les suggestions (`_teacher_free_at`, déjà appelé par
    `_suggestions_for`) — un glisser-déposer direct sur une case arbitraire,
    hors suggestion, pouvait les violer sans aucun garde-fou serveur.
    """
    from cal_iut.api.validation import _teacher_free_at

    if not session.teacher_codes or not state.teacher_availability:
        return []
    semestre = session.semestre
    week_offset = semester_week_offset(state.calendar, semestre)
    d = state.calendar.week_day_to_date(week_offset + week, day)
    if _teacher_free_at(
        session.teacher_codes, week, day, slot, d, state.teacher_availability, state.calendar, week_offset
    ):
        return []
    return [
        f"Enseignant indisponible à ce créneau ({', '.join(session.teacher_codes)}) — "
        "indisponibilité déclarée (contrainte enseignant ou encadrement SAE) — "
        "non modifiable, même en forçant."
    ]


def _suggestions_for(state: object, session_id: str, match: object) -> tuple[list[SlotSuggestionResponse], str | None]:
    """
    Assemble le contexte complet de contraintes dures pour
    `suggest_alternative_slots` — retour utilisateur : "il faut que les
    suggestions... prennent en compte les contraintes et vérifient si cela
    est possible dans tous les autres parcours". Le conflit groupe/
    enseignant (déjà inter-parcours par construction, `validate_move` est
    appelé contre `state.timetable` COMPLET) est géré dans
    `suggest_alternative_slots` lui-même ; ici, on ajoute ce qui manquait :
    verrou jeudi PAC, jours SAE sanctuarisés, événements du planning
    officiel à horaire précis, ordre pédagogique — et la salle, recalculée
    par candidat plutôt que figée sur l'ancienne (une suggestion n'est
    écartée pour motif de salle que si AUCUNE salle adaptée n'est libre).

    Retourne `(suggestions, note)` — `note` explique pourquoi aucune
    suggestion n'est proposée quand c'est le cas (ex. duo synchronisé).
    """
    session = state.sessions_by_id.get(session_id)
    if session is None:
        return [], None

    if _is_duo_synced(session, state.teacher_duos):
        return [], _DUO_SYNC_NOTE

    extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
    original_room_id = getattr(match, "room_id", None)
    # `room_id=None` ici volontairement : le conflit de salle n'écarte plus un
    # candidat au 1er passage, il est résolu séparément ci-dessous (une salle
    # DIFFÉRENTE peut très bien convenir même si l'ancienne est prise).
    #
    # `extra_blocked_pedago` reste exclu ici même si l'ordre pédagogique est
    # devenu force-able (28/08/2026) : une SUGGESTION doit rester un créneau
    # ne nécessitant AUCUN forçage — sinon on proposerait à l'utilisateur, en
    # candidat "propre", un créneau qu'il faudrait ensuite forcer quand même.
    raw = suggest_alternative_slots(
        session_id, match.group_ids, match.teacher_codes, _as_placed(state.timetable),
        state.calendar, session.semestre, teacher_availability=state.teacher_availability,
        room_id=None, search_from_week=match.week, max_suggestions=8,
        extra_blocked=extra_blocked | extra_blocked_pedago, allowed_weeks=allowed_weeks,
        sessions_by_id=state.sessions_by_id, groups=state.groups,
    )

    resolved: list[SlotSuggestionResponse] = []
    for s in raw:
        if len(resolved) >= 3:
            break
        room = _resolve_room(state, session, s.week, s.day, s.slot, original_room_id) if original_room_id else None
        if original_room_id and room is None:
            continue  # aucune salle disponible à ce créneau, pas une vraie alternative
        room_changed = bool(room and room.id != original_room_id)
        label = s.label + (f" (salle {room.label})" if room_changed else "")
        resolved.append(SlotSuggestionResponse(week=s.week, day=s.day, slot=s.slot, label=label))
    return resolved, None


@app.post("/placements/{session_id}/validate", response_model=ValidationResponse)
def validate_placement(session_id: str, body: MoveSessionRequest) -> ValidationResponse:
    state = get_state()
    match = _find_placement(state, session_id)
    session = state.sessions_by_id.get(session_id)
    _check_move_editable(state, session_id, match.week, body.week)

    # Règles institutionnelles/pédagogiques : contrôlées ICI, sur le
    # déplacement réellement demandé — pas seulement utilisées pour filtrer
    # les suggestions (retour utilisateur : "vérifie bien toutes les
    # contraintes avant que ça s'effectue"). Jamais contournables.
    if session and _is_duo_synced(session, state.teacher_duos):
        return ValidationResponse(valid=False, hard_conflicts=[_DUO_SYNC_NOTE], soft_warnings=[], suggestions=[], suggestions_note=_DUO_SYNC_NOTE)
    if session:
        extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
        institutional = _institutional_violations(body.week, body.day, body.slot, extra_blocked)
        institutional += _teacher_availability_violations(state, session, body.week, body.day, body.slot)
        # L'ordre pédagogique est signalé ici (dry-run, avant décision de
        # l'utilisateur) même si `body.force` n'est pas encore posé — c'est
        # ce qui déclenche la modale de confirmation côté front ; le forçage
        # réel n'intervient qu'au vrai déplacement (`move_session`/
        # `placer_seance`), pas dans cette prévisualisation.
        pedago = _pedagogical_order_violations(body.week, body.day, body.slot, extra_blocked_pedago, allowed_weeks)
        if institutional or pedago:
            return ValidationResponse(valid=False, hard_conflicts=institutional + pedago, soft_warnings=[], suggestions=[], suggestions_note=None)

    # Même résolution de salle que `move_session` — sinon un dry-run
    # pourrait signaler un conflit que le déplacement réel n'aurait pas
    # (puisque celui-ci recalcule la salle automatiquement).
    target_room_id = body.room_id or getattr(match, "room_id", None)
    if not body.room_id and session and target_room_id:
        resolved_room = _resolve_room(state, session, body.week, body.day, body.slot, target_room_id)
        if resolved_room is not None:
            target_room_id = resolved_room.id

    result = validate_move(
        session_id, body.week, body.day, body.slot, _as_placed(state.timetable), match.group_ids, match.teacher_codes,
        target_room_id, conflicting_room_ids=_build_conflict_map(state.rooms).get(target_room_id, set()) if target_room_id else None,
    )
    suggestions, note = ([], None) if result.valid else _suggestions_for(state, session_id, match)
    return ValidationResponse(valid=result.valid, hard_conflicts=result.hard_conflicts, soft_warnings=result.soft_warnings, suggestions=suggestions, suggestions_note=note)


@app.patch("/placements/{session_id}")
def move_session(session_id: str, body: MoveSessionRequest) -> PlacementResponse:
    state = get_state()
    match = _find_placement(state, session_id)
    session = state.sessions_by_id.get(session_id)

    if session and session.locked and not body.lock:
        raise HTTPException(409, "Session is locked")

    _check_move_editable(state, session_id, match.week, body.week)

    # Règles institutionnelles (PAC, fin de semestre FI, présence alternant
    # FC, événement planning officiel, SAE sanctuarisée) : JAMAIS
    # contournables via `force` (un humain peut avoir une bonne raison
    # ponctuelle de forcer un conflit de ressources ; casser un de ces
    # verrous n'en a jamais une bonne). Retour utilisateur : "vérifie bien
    # toutes les contraintes avant que ça s'effectue" — avant ce correctif,
    # ces règles ne servaient qu'à filtrer les suggestions, un
    # glisser-déposer direct sur une case arbitraire (hors suggestion)
    # pouvait les violer sans aucun garde-fou serveur.
    #
    # La synchro duo (WR110/112/113) EST contournable via `force` depuis le
    # 28/08/2026 (retour utilisateur : « il faut que je puisse forcer ») —
    # à la différence des règles ci-dessus, c'est une optimisation de
    # confort, pas une contrainte réglementaire. L'ordre pédagogique EST
    # AUSSI contournable via `force` depuis le 28/08/2026 (retour
    # utilisateur : « on veut que si on appuie sur forcer cela soit bon et
    # que le placement se fasse ») — cf. `_pedagogical_order_violations`,
    # vérifié séparément plus bas, après le bloc institutionnel ci-dessous.
    if session and _is_duo_synced(session, state.teacher_duos) and not body.force:
        raise HTTPException(409, detail={
            "message": "Conflit", "hard_conflicts": [_DUO_SYNC_NOTE],
            "soft_warnings": [], "suggestions": [], "suggestions_note": _DUO_SYNC_NOTE,
        })
    if session:
        extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
        institutional = _institutional_violations(body.week, body.day, body.slot, extra_blocked)
        institutional += _teacher_availability_violations(state, session, body.week, body.day, body.slot)
        if institutional:
            raise HTTPException(409, detail={
                "message": "Conflit", "hard_conflicts": institutional,
                "soft_warnings": [], "suggestions": [], "suggestions_note": None,
            })
        # Ordre pédagogique : contournable via `force` depuis le 28/08/2026
        # (cf. `_pedagogical_order_violations`), à la différence du bloc
        # institutionnel ci-dessus. Calculé même si `force` est déjà vrai —
        # `forced_pending.sync_after_move`, appelé plus bas UNE FOIS le
        # déplacement réellement effectué (pas ici : un conflit de ressource
        # peut encore faire échouer le déplacement après ce point), en a
        # besoin pour savoir si CE déplacement doit rester suivi.
        pedago = _pedagogical_order_violations(body.week, body.day, body.slot, extra_blocked_pedago, allowed_weeks)
        if pedago and not body.force:
            raise HTTPException(409, detail={
                "message": "Conflit", "hard_conflicts": pedago,
                "soft_warnings": [], "suggestions": [], "suggestions_note": None,
            })
    else:
        pedago = []

    # Résolution de salle : garde l'actuelle si elle est encore libre à ce
    # créneau, recalcule sinon (retour utilisateur : "si on modifie [le
    # créneau] il faut recalculer [la salle]" — ne pas bloquer un
    # déplacement juste parce que la salle d'origine n'est plus libre, si
    # une autre salle adaptée l'est). Seulement quand l'utilisateur n'a PAS
    # explicitement demandé une salle précise (`body.room_id`) : dans ce
    # cas son choix est respecté tel quel, `validate_move` juge normalement.
    target_room_id = body.room_id or getattr(match, "room_id", None)
    if not body.room_id and session and target_room_id:
        resolved_room = _resolve_room(state, session, body.week, body.day, body.slot, target_room_id)
        if resolved_room is not None:
            target_room_id = resolved_room.id

    validation = validate_move(
        session_id, body.week, body.day, body.slot, _as_placed(state.timetable),
        match.group_ids, match.teacher_codes, target_room_id,
        # Sans ces deux-là, la validation ignorait la DURÉE des séances (un
        # bloc de 3h n'était vu que sur son premier créneau) et la COHORTE
        # étudiante (un TD posé sur le CM de sa promo passait sans conflit).
        sessions_by_id=state.sessions_by_id,
        groups=state.groups,
        conflicting_room_ids=_build_conflict_map(state.rooms).get(target_room_id, set()) if target_room_id else None,
    )

    if not validation.valid and not body.force:
        suggestions, note = _suggestions_for(state, session_id, match)
        raise HTTPException(409, detail={
            "message": "Conflit",
            "hard_conflicts": validation.hard_conflicts,
            "soft_warnings": validation.soft_warnings,
            "suggestions": [s.model_dump() for s in suggestions],
            "suggestions_note": note,
        })

    proposed = {"week": match.week, "day": match.day, "slot": match.slot}
    match.week, match.day, match.slot = body.week, body.day, body.slot

    if target_room_id:
        room = next((r for r in state.rooms if r.id == target_room_id), None)
        if room:
            match.room_id, match.room_label = room.id, room.label

    if body.lock and session:
        session.locked = True
        session.locked_day = body.day
        session.locked_slot = body.slot
        session.metadata["locked_week"] = body.week

    if session:
        forced_pending.sync_after_move(session_id, body.week, body.day, body.slot, bool(pedago))

    correction = {
        "session_id": session_id,
        "proposed": proposed,
        "manual": {"week": body.week, "day": body.day, "slot": body.slot},
        "locked": body.lock,
        "forced": body.force,
    }
    state.corrections.append(correction)

    if state.current_run_id:
        repo = get_repo()
        repo.save_correction(
            state.current_run_id,
            session_id,
            proposed,
            {"week": body.week, "day": body.day, "slot": body.slot},
            body.lock,
            body.force,
            match.course_code,
            match.teacher_codes,
        )
        persiste = repo.update_current_placement(
            session_id, body.week, body.day, body.slot,
            getattr(match, "room_id", None), getattr(match, "room_label", None),
            body.lock or (session.locked if session else False),
            run_id=state.current_run_id, course_code=match.course_code,
        )
        if not persiste:
            # Ne jamais laisser croire qu'un déplacement est enregistré quand il
            # ne l'est pas : à l'écran il resterait visible jusqu'au prochain
            # redémarrage, puis disparaîtrait sans explication.
            raise HTTPException(
                500,
                detail={
                    "message": "Déplacement non enregistré : aucun run en base.",
                    "quoi_faire": "Relancer une génération (`POST /solve`) avant de modifier le planning.",
                },
            )

    return _to_placement(match, state.sessions_by_id)


@app.get("/corrections")
def list_corrections() -> list[dict[str, object]]:
    state = get_state()
    repo = get_repo()
    db_rows = repo.list_corrections(state.current_run_id)
    if db_rows:
        return [
            {
                "id": r.id,
                "session_id": r.session_id,
                "course_code": r.course_code,
                "proposed": {"week": r.proposed_week, "day": r.proposed_day, "slot": r.proposed_slot},
                "manual": {"week": r.manual_week, "day": r.manual_day, "slot": r.manual_slot},
                "locked": r.locked,
                "forced": r.forced,
            }
            for r in db_rows
        ]
    return state.corrections


# ==========================================================================
# Placement manuel des séances que le solveur n'a pas su placer
# ==========================================================================
#
# Pourquoi ces routes existent (26/08/2026). Le solveur place ~96,5 % des
# séances ; les quelques dizaines restantes butent sur des combinaisons
# PROUVÉES infaisables par l'étage 3 (cf. `decomposed._cuts_from_failed_weeks`)
# — pas sur un manque de temps de calcul ni de capacité. Jusqu'ici elles
# disparaissaient purement et simplement : le planning avait l'air complet
# alors qu'il manquait des heures, et rien dans l'interface ne les mentionnait.
#
# Décision de l'utilisateur : accepter ce reliquat et le placer à la main, à
# condition que l'interface le permette. C'est à quoi servent ces routes —
# inventorier ce qui manque, proposer des créneaux réellement libres, et poser
# la séance en passant par EXACTEMENT les mêmes contrôles que le
# glisser-déposer (`move_session`), pour qu'un placement manuel ne puisse
# jamais introduire ce que le solveur s'interdit.


_LIBELLES_DUREE = {1: "1h30", 2: "3h", 3: "4h30", 4: "6h"}


def _noms_enseignants(state: object) -> dict[str, str]:
    """code -> « Prénom NOM », pour ne jamais afficher un trigramme seul.

    ALO, FME, BTO... ne parlent qu'aux initiés ; la personne qui reprendra ce
    travail l'an prochain doit pouvoir lire l'écran sans glossaire.
    """
    noms: dict[str, str] = {}
    for course in getattr(state, "courses", []) or []:
        candidats = [getattr(course, "lead", None)]
        candidats += [b.teacher for b in (getattr(course, "profs", None) or [])]
        for t in candidats:
            if t is not None and getattr(t, "code", None) and t.code not in noms:
                noms[t.code] = f"{t.prenom} {t.nom}".strip()
    return noms


def _raison_non_placee(state: object, session: object, allowed_weeks: set[int], n_semaines: int) -> str:
    """Ce qui rend cette séance difficile, en une phrase.

    Un inventaire qui dit seulement « 85 séances manquantes » n'aide personne à
    les placer. On donne le motif le plus probable, annoncé comme tel : CP-SAT
    ne rend aucune justification d'infaisabilité, tout ce qui serait présenté
    comme une certitude serait inventé.

    Une fenêtre d'ordre pédagogique très étroite (1-2 semaines valides sur un
    horizon bien plus long) passe maintenant AVANT le motif "disponibilités
    enseignant" — trouvé le 28/08/2026 sur WR106-S1-CM-1 (retour utilisateur) :
    ce message accusait à tort la dispo de MRI (dont il existait bien UNE
    entrée quelque part dans `state.teacher_availability`, sans rapport avec
    ce blocage précis) alors que la vraie cause était deux TP voisins placés
    une semaine "en avance" par rapport à leurs pairs, réduisant la fenêtre
    pédagogiquement valide à une seule semaine déjà saturée pour le groupe.
    """
    motifs: list[str] = []
    duree = session.duration_slots or 1
    if duree >= 2:
        motifs.append(f"bloc de {_LIBELLES_DUREE.get(duree, '?')} d'affilée à caser")
    if len(session.teacher_codes or []) > 1:
        motifs.append("plusieurs enseignants à réunir sur le même créneau")
    fenetre_etroite = 0 < len(allowed_weeks) <= 2 < n_semaines
    if fenetre_etroite:
        libelle_fenetre = "une seule semaine" if len(allowed_weeks) == 1 else "deux semaines"
        motifs.insert(
            0,
            f"ordre pédagogique très contraint par des séances voisines (fenêtre réduite à "
            f"{libelle_fenetre}) — un placement manuel avec « Forcer » peut débloquer, si "
            "le contenu le permet",
        )
    else:
        for code in session.teacher_codes or []:
            if any(a.teacher_code == code for a in (state.teacher_availability or [])):
                motifs.append(f"disponibilités restreintes déclarées pour {code}")
                break
    if not motifs:
        motifs.append("semaine saturée pour ce groupe ou cet enseignant")
    return "Probablement : " + ", ".join(motifs) + "."


def _date_iso(state: object, semestre: str, week: int, day: int) -> str:
    from datetime import timedelta

    index = semester_week_offset(state.calendar, semestre) + week
    if 0 <= index < len(state.calendar.teaching_mondays):
        return (state.calendar.teaching_mondays[index] + timedelta(days=day)).isoformat()
    return ""


@app.get("/placements/manquantes", response_model=SeancesAPlacerResponse)
def seances_manquantes() -> SeancesAPlacerResponse:
    """Inventaire des séances absentes du planning.

    Calculé par DIFFÉRENCE — séances à placer moins séances placées — plutôt
    que lu dans un champ du solveur : l'inventaire reste ainsi juste même si
    une séance disparaît par un autre chemin (reprise d'un run partiel,
    régénération de semaine interrompue, correction manuelle).
    """
    state = get_state()
    places = {p.session_id for p in state.timetable}
    placement_by_id = {p.session_id: p for p in state.timetable}
    # Placées en forçant l'ordre pédagogique, pas encore validées : restent
    # listées ici même si elles SONT au planning (`session.id in places`),
    # cf. `api/forced_pending.py` — retour utilisateur 28/08/2026.
    en_attente = forced_pending.all_pending()
    noms = _noms_enseignants(state)
    libelle_groupe = {g.id: g.label for g in state.groups}

    # Les bornes d'ordre pédagogique sont calculées ICI, une fois pour toutes,
    # au lieu de passer par `_hard_constraint_context` séance par séance :
    # celui-ci relit le planning officiel sur disque et reparcourt les 3101
    # séances à chaque appel. Mesuré sur un run très incomplet (795 séances
    # manquantes) : 13,6 s pour dresser l'inventaire, contre une fraction de
    # seconde ici. Le résultat est identique — `allowed_weeks` n'y vient que
    # de `_movable_bounds`.
    from cal_iut.solver.decomposed import _build_sequence_neighbors, _movable_bounds

    voisins = _build_sequence_neighbors(state.sessions, state.groups)
    semaine_par_seance = {p.session_id: p.week for p in state.timetable}
    n_semaines = max((p.week for p in state.timetable), default=-1) + 1

    # Exclut les SAE non planifiées par le solveur (préfixe "WS", sauf
    # `solver_scheduled_sae`, ex. WSA501D) — même filtre que l'audit
    # (`resultat.seances_non_placees`) et `scripts/solve_until_ok.py::score_run`.
    # Bug réel trouvé le 27/08/2026 (retour utilisateur : « j'ai 1121 à
    # placer pas 426 ») : cet inventaire — l'onglet « À placer » réel de
    # l'appli — comptait encore les 695 séances SAE dont la semaine vient du
    # calendrier réel, jamais du solveur, jamais censées être placées à la
    # main.
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    scheduled_sae = load_solver_scheduled_sae(state.config_dir)

    manquantes: list[SeanceAPlacerResponse] = []
    par_parcours: dict[str, int] = {}
    for session in state.sessions:
        provisoire = session.id in en_attente
        if session.id in places and not provisoire:
            continue
        if session.course_code.upper().startswith("WS") and (session.course_code.upper(), session.semestre) not in scheduled_sae:
            continue
        lo, hi = _movable_bounds(session.id, voisins, semaine_par_seance, n_semaines)
        semaines_ok = set(range(lo, hi + 1))
        par_parcours[session.parcours] = par_parcours.get(session.parcours, 0) + 1
        actuel = placement_by_id.get(session.id) if provisoire else None
        manquantes.append(SeanceAPlacerResponse(
            session_id=session.id,
            course_code=session.course_code,
            course_name=session.course_name,
            session_type=str(getattr(session.session_type, "value", session.session_type)),
            semestre=session.semestre,
            parcours=session.parcours,
            annee=session.annee,
            duration_slots=session.duration_slots or 1,
            duree_libelle=_LIBELLES_DUREE.get(session.duration_slots or 1, "?"),
            group_ids=list(session.group_ids or []),
            groupes_libelles=[libelle_groupe.get(g, g) for g in (session.group_ids or [])],
            teacher_codes=list(session.teacher_codes or []),
            enseignants_libelles=[noms.get(c, c) for c in (session.teacher_codes or [])],
            sequence_order=session.sequence_order,
            semaines_possibles=sorted(semaines_ok),
            raison=_raison_non_placee(state, session, semaines_ok, n_semaines),
            placee_provisoirement=provisoire,
            semaine_actuelle=actuel.week if actuel else None,
            jour_actuel=actuel.day if actuel else None,
            slot_actuel=actuel.slot if actuel else None,
        ))

    manquantes.sort(key=lambda m: (m.parcours, m.course_code, m.sequence_order or 0))
    total = len(state.sessions)
    n_provisoires = sum(1 for m in manquantes if m.placee_provisoirement)
    n_reellement_manquantes = len(manquantes) - n_provisoires
    if not manquantes:
        resume = "Toutes les séances sont placées."
    elif n_reellement_manquantes == 0:
        resume = (
            f"Toutes les séances sont placées. {n_provisoires} en attente de validation "
            "(ordre pédagogique forcé) — à vérifier ci-dessous."
        )
    else:
        resume = (
            f"{n_reellement_manquantes} séance(s) sur {total} restent à placer à la main"
            + (f", + {n_provisoires} en attente de validation (ordre pédagogique forcé)" if n_provisoires else "")
            + ". Ouvrez-en une : l'application ne propose que des créneaux où aucune "
            "règle n'est violée."
        )
    return SeancesAPlacerResponse(
        total_a_placer=total,
        total_placees=len(places),
        manquantes=manquantes,
        par_parcours=par_parcours,
        resume=resume,
    )


@app.get("/placements/{session_id}/creneaux-libres", response_model=CreneauxLibresResponse)
def creneaux_libres(session_id: str, depuis_semaine: int = 0, maximum: int = 12) -> CreneauxLibresResponse:
    """Créneaux où cette séance PEUT réellement aller.

    Même moteur que les suggestions du glisser-déposer, mais balayant tout
    l'horizon plutôt que six semaines : une séance jamais placée n'a pas de
    position d'origine autour de laquelle chercher.
    """
    state = get_state()
    session = state.sessions_by_id.get(session_id)
    if session is None:
        raise HTTPException(404, f"Séance {session_id} inconnue")
    if _is_duo_synced(session, state.teacher_duos):
        return CreneauxLibresResponse(session_id=session_id, creneaux=[], note=_DUO_SYNC_NOTE)

    extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
    # Les candidats proposés ici évitent aussi `extra_blocked_pedago` : une
    # suggestion doit rester un créneau ne nécessitant AUCUN forçage, même
    # si l'ordre pédagogique est devenu force-able (28/08/2026, cf. note
    # ci-dessous pour le cas où ça laisse zéro candidat).
    brutes = suggest_alternative_slots(
        session_id, list(session.group_ids or []), list(session.teacher_codes or []),
        _as_placed(state.timetable), state.calendar, session.semestre,
        teacher_availability=state.teacher_availability, room_id=None,
        search_from_week=depuis_semaine,
        max_weeks=len(state.calendar.teaching_mondays),
        max_suggestions=maximum, extra_blocked=extra_blocked | extra_blocked_pedago, allowed_weeks=allowed_weeks,
        sessions_by_id=state.sessions_by_id, groups=state.groups,
    )

    creneaux: list[CreneauLibreResponse] = []
    for suggestion in brutes:
        salle = _resolve_room(state, session, suggestion.week, suggestion.day, suggestion.slot, None)
        remarques: list[str] = []
        if salle is None:
            # Signalé, pas éliminé : une séance sans salle reste plaçable, et
            # la salle peut très bien s'arbitrer hors application.
            remarques.append("aucune salle libre trouvée à ce créneau")
        if suggestion.slot >= 5:
            remarques.append("dernier créneau de la journée (17h-18h30)")
        creneaux.append(CreneauLibreResponse(
            week=suggestion.week, day=suggestion.day, slot=suggestion.slot,
            label=suggestion.label,
            date=_date_iso(state, session.semestre, suggestion.week, suggestion.day),
            salle_label=getattr(salle, "label", None),
            remarques=remarques,
        ))

    note = None
    if not creneaux:
        # Un deuxième balayage, SANS exclure `extra_blocked_pedago`, dit si
        # l'ordre pédagogique est la seule chose qui manque — dans ce cas
        # (28/08/2026) un placement manuel avec `force: true` peut réussir
        # là où aucune suggestion "propre" n'existe.
        forcable = suggest_alternative_slots(
            session_id, list(session.group_ids or []), list(session.teacher_codes or []),
            _as_placed(state.timetable), state.calendar, session.semestre,
            teacher_availability=state.teacher_availability, room_id=None,
            search_from_week=depuis_semaine,
            max_weeks=len(state.calendar.teaching_mondays),
            max_suggestions=1, extra_blocked=extra_blocked, allowed_weeks=None,
            sessions_by_id=state.sessions_by_id, groups=state.groups,
        )
        if forcable:
            note = (
                "Aucun créneau ne respecte l'ordre pédagogique pour cette séance, mais "
                "d'autres existent une fois l'ordre pédagogique ignoré : posez-la à la "
                "main sur une case libre et confirmez « Forcer le placement » — ça "
                "fonctionnera, en plaçant sciemment cette séance hors de l'ordre de "
                "contenu attendu."
            )
        else:
            note = (
                "Aucun créneau ne respecte toutes les règles pour cette séance, même en "
                "forçant l'ordre pédagogique. Deux pistes : régénérer une semaine entière "
                "(elle réarrange les autres cours pour faire de la place), ou assouplir "
                "une contrainte dans les fichiers de configuration."
            )
    return CreneauxLibresResponse(session_id=session_id, creneaux=creneaux, note=note)


@app.post("/placements/{session_id}/placer", response_model=PlacementResponse)
def placer_seance(session_id: str, body: MoveSessionRequest) -> PlacementResponse:
    """Pose au planning une séance qui n'y était pas.

    `PATCH /placements/{id}` ne sait que DÉPLACER : il commence par chercher la
    séance dans le planning et rend 404 si elle n'y est pas — précisément le cas
    de toutes les séances que le solveur a laissées de côté. D'où cette route
    jumelle, qui applique les MÊMES contrôles dans le MÊME ordre : règles
    institutionnelles d'abord (jamais contournables), conflits de ressources
    ensuite (contournables via `force`). Un placement manuel ne doit pas pouvoir
    introduire ce qu'un déplacement manuel interdit.
    """
    state = get_state()
    session = state.sessions_by_id.get(session_id)
    if session is None:
        raise HTTPException(404, f"Séance {session_id} inconnue")
    if any(p.session_id == session_id for p in state.timetable):
        raise HTTPException(
            409,
            "Cette séance est déjà au planning : utilisez le déplacement plutôt "
            "que le placement.",
        )

    statut = week_status(state.calendar, session.semestre, body.week)
    if statut != "future":
        raise HTTPException(409, f"Semaine {body.week + 1} non modifiable (statut : {statut})")

    # `force` contourne la synchro duo depuis le 28/08/2026 (retour
    # utilisateur : « il faut que je puisse forcer ») et l'ordre pédagogique
    # depuis le même jour, plus tard (retour utilisateur : « on veut que si
    # on appuie sur forcer cela soit bon et que le placement se fasse »,
    # cf. `_pedagogical_order_violations` plus bas) — jusque-là jamais
    # contournables, au même titre que PAC/SAE (cf. commentaire dans
    # `move_session` ci-dessus). Contrairement au bloc institutionnel
    # ci-dessous (toujours non contournable), une synchro duo est une
    # optimisation de confort (garder deux moitiés de cours alignées), pas
    # une contrainte réglementaire — un humain qui force ici sait qu'il
    # désynchronise sciemment le binôme.
    if _is_duo_synced(session, state.teacher_duos) and not body.force:
        raise HTTPException(409, detail={
            "message": "Conflit", "hard_conflicts": [_DUO_SYNC_NOTE],
            "soft_warnings": [], "suggestions": [], "suggestions_note": _DUO_SYNC_NOTE,
        })

    extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
    institutional = _institutional_violations(body.week, body.day, body.slot, extra_blocked)
    institutional += _teacher_availability_violations(state, session, body.week, body.day, body.slot)
    if institutional:
        raise HTTPException(409, detail={
            "message": "Conflit", "hard_conflicts": institutional,
            "soft_warnings": [], "suggestions": [], "suggestions_note": None,
        })
    # Ordre pédagogique : contournable via `force` depuis le 28/08/2026 (cf.
    # `_pedagogical_order_violations`), à la différence du bloc institutionnel
    # ci-dessus. Calculé même si `force` est déjà vrai — `forced_pending.
    # sync_after_move`, appelé plus bas UNE FOIS le placement réellement
    # effectué (un conflit de ressource peut encore le faire échouer après
    # ce point), en a besoin pour savoir si CE placement doit rester suivi.
    pedago = _pedagogical_order_violations(body.week, body.day, body.slot, extra_blocked_pedago, allowed_weeks)
    if pedago and not body.force:
        raise HTTPException(409, detail={
            "message": "Conflit", "hard_conflicts": pedago,
            "soft_warnings": [], "suggestions": [], "suggestions_note": None,
        })

    if body.room_id:
        salle = next((r for r in state.rooms if r.id == body.room_id), None)
    else:
        salle = _resolve_room(state, session, body.week, body.day, body.slot, None)

    salle_id = getattr(salle, "id", None)
    validation = validate_move(
        session_id, body.week, body.day, body.slot, _as_placed(state.timetable),
        list(session.group_ids or []), list(session.teacher_codes or []),
        salle_id,
        sessions_by_id=state.sessions_by_id, groups=state.groups,
        conflicting_room_ids=_build_conflict_map(state.rooms).get(salle_id, set()) if salle_id else None,
    )
    if not validation.valid and not body.force:
        raise HTTPException(409, detail={
            "message": "Conflit",
            "hard_conflicts": validation.hard_conflicts,
            "soft_warnings": validation.soft_warnings,
            "suggestions": [], "suggestions_note": None,
        })

    place = PlacedSessionWithRoom(
        session_id=session_id, week=body.week, day=body.day, slot=body.slot,
        course_code=session.course_code, group_ids=list(session.group_ids or []),
        teacher_codes=list(session.teacher_codes or []),
        room_id=getattr(salle, "id", None), room_label=getattr(salle, "label", None),
    )
    state.timetable.append(place)
    forced_pending.sync_after_move(session_id, body.week, body.day, body.slot, bool(pedago))

    if body.lock:
        session.locked = True
        session.locked_day = body.day
        session.locked_slot = body.slot
        session.metadata["locked_week"] = body.week

    state.corrections.append({
        "session_id": session_id,
        # Aucune position proposée : le solveur ne l'avait pas placée du tout.
        "proposed": None,
        "manual": {"week": body.week, "day": body.day, "slot": body.slot},
        "locked": body.lock,
        "forced": body.force,
    })

    if state.current_run_id:
        persiste = get_repo().update_current_placement(
            session_id, body.week, body.day, body.slot,
            getattr(salle, "id", None), getattr(salle, "label", None),
            body.lock, run_id=state.current_run_id, course_code=session.course_code,
        )
        if not persiste:
            # Ne jamais laisser croire qu'un placement est enregistré quand il
            # ne l'est pas : à l'écran il resterait visible jusqu'au prochain
            # redémarrage, puis disparaîtrait sans explication.
            state.timetable.remove(place)
            raise HTTPException(500, detail={
                "message": "Placement non enregistré : aucun run en base.",
                "quoi_faire": "Relancer une génération avant de modifier le planning.",
            })

    return _to_placement(place, state.sessions_by_id)


@app.post("/placements/{session_id}/valider", response_model=ForcagePedagogiqueResponse)
def valider_forcage_pedagogique(session_id: str) -> ForcagePedagogiqueResponse:
    """Confirme un placement qui avait dû forcer l'ordre pédagogique — le
    retire du suivi (`api/forced_pending.py`), il n'apparaît plus dans « À
    placer » (retour utilisateur 28/08/2026 : « il faut peut-être un bouton
    valider »). Idempotent : cliquer deux fois, ou valider quelque chose qui
    n'était pas en attente, ne fait rien de plus qu'un no-op — jamais
    d'erreur pour un état déjà atteint."""
    etait_en_attente = forced_pending.get(session_id) is not None
    forced_pending.clear(session_id)
    return ForcagePedagogiqueResponse(session_id=session_id, etait_en_attente=etait_en_attente)


@app.delete("/placements/{session_id}", response_model=ForcagePedagogiqueResponse)
def retirer_placement_force(session_id: str) -> ForcagePedagogiqueResponse:
    """Retire du planning un placement qui avait forcé l'ordre pédagogique —
    la séance redevient une séance « à placer » normale (retour utilisateur
    28/08/2026 : « il faut le laisser dans la liste pour peut-être revenir
    en arrière »). Volontairement restreint aux placements EN ATTENTE de
    validation (`forced_pending`) : ce n'est pas un endpoint générique de
    suppression de placement — retirer un cours normalement placé n'a pas
    été demandé et mérite un chemin (et une confirmation) dédiés s'il l'est
    un jour."""
    if forced_pending.get(session_id) is None:
        raise HTTPException(
            400,
            "Ce placement n'est pas un forçage d'ordre pédagogique en attente de validation — rien à retirer ici.",
        )
    state = get_state()
    state.timetable[:] = [p for p in state.timetable if p.session_id != session_id]
    if state.current_run_id:
        get_repo().remove_current_placement(session_id)
    forced_pending.clear(session_id)
    return ForcagePedagogiqueResponse(session_id=session_id, etait_en_attente=True)


@app.post("/placements/completer", response_model=CompletionResponse)
def completer() -> CompletionResponse:
    """Place d'un coup toutes les séances que le solveur a laissées de côté.

    Constat qui justifie cette route (26/08/2026) : sur 20 séances manquantes
    tirées du run réel, **20** avaient au moins un créneau parfaitement
    valable. Faire cliquer une personne 85 fois pour poser des séances que la
    machine sait poser serait un gâchis — et une source d'erreurs.

    Ce remplissage ne déplace jamais une séance déjà posée et ne cherche aucun
    optimum : il complète, il ne réarrange pas. Ce qu'il ne sait pas faire est
    rendu à la décision humaine avec son motif, jamais passé sous silence.
    """
    from cal_iut.solver.completion import completer_placements

    state = get_state()
    if not state.timetable:
        raise HTTPException(404, "Aucun planning chargé : lancez d'abord une génération.")

    semestre = next((s.semestre for s in state.sessions), "S1")
    horizon = max((p.week for p in state.timetable), default=-1) + 1

    def _candidats(session):
        if _is_duo_synced(session, state.teacher_duos):
            # Déplacer une moitié de duo sans l'autre casse la synchronisation
            # salle rare : jamais automatiquement.
            return []
        extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
        # La complétion automatique n'a personne pour DÉCIDER de forcer
        # l'ordre pédagogique (28/08/2026) : elle continue donc à l'exclure
        # comme un verrou institutionnel, au même titre que la synchro duo
        # ci-dessus — seul un placement manuel confirmé par un humain force.
        brutes = suggest_alternative_slots(
            session.id, list(session.group_ids or []), list(session.teacher_codes or []),
            _as_placed(state.timetable), state.calendar, session.semestre,
            teacher_availability=state.teacher_availability, room_id=None,
            search_from_week=0, max_weeks=horizon, max_suggestions=25,
            extra_blocked=extra_blocked | extra_blocked_pedago, allowed_weeks=allowed_weeks,
            sessions_by_id=state.sessions_by_id, groups=state.groups,
        )
        return [(b.week, b.day, b.slot) for b in brutes]

    def _poser(session, week, day, slot) -> bool:
        try:
            placer_seance(
                session.id,
                MoveSessionRequest(week=week, day=day, slot=slot, lock=False, force=False),
            )
        except HTTPException:
            return False
        return True

    a_traiter = list(state.sessions)
    rapport = completer_placements(
        sessions=a_traiter,
        placements=list(state.timetable),
        groups=state.groups,
        calendar=state.calendar,
        semestre_par_defaut=semestre,
        config_dir=state.config_dir,
        teacher_availability=state.teacher_availability,
        contexte_dur=lambda s: _hard_constraint_context(state, s),
        creneaux_candidats=_candidats,
        poser=_poser,
    )

    return CompletionResponse(
        placees=[
            SeancePlaceeAutoResponse(
                session_id=p.session_id, course_code=p.course_code,
                week=p.week, day=p.day, slot=p.slot, date=p.date_iso,
            )
            for p in rapport.placees
        ],
        refusees=[
            SeanceRefuseeResponse(session_id=r.session_id, course_code=r.course_code, raison=r.raison)
            for r in rapport.refusees
        ],
        resume=rapport.resume(),
    )


def _semestres_couverts_label(state: object) -> str:
    """Libellé humain des semestres couverts par le run chargé (« S1, S3 et
    S5 ») — dérivé de `state.semestre_group`, pas codé en dur (retour
    utilisateur 28/08/2026 : « préciser dans le mail que c'est les emploi du
    temps pour les semestre impaire S1 S3 et S5 ») : coder ça en dur serait
    devenu FAUX le jour où un run "even" (S2/S4/S6) est chargé à la place."""
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUPS

    semestres = sorted(SEMESTRE_GROUPS.get(state.semestre_group or "", set()))
    if not semestres:
        # Groupe de semestres inconnu (run par parcours unique, pas par
        # groupe pair/impair) : reconstitue depuis ce qui est réellement
        # chargé plutôt que de ne rien dire.
        semestres = sorted({s.semestre for s in state.sessions if s.semestre})
    if not semestres:
        return ""
    if len(semestres) == 1:
        return semestres[0]
    return ", ".join(semestres[:-1]) + " et " + semestres[-1]


def _teacher_a_des_seances_non_placees(state: object, code: str) -> bool:
    """Un enseignant peut avoir des séances qui lui reviennent, mais que le
    solveur n'a pas su placer (cf. écran « À placer ») — sans ce signal, son
    lien perso lui montrerait un planning qui a l'air complet alors qu'il
    manque des heures, sans qu'il sache qu'il doit relancer quelqu'un.
    Même filtre SAE que `seances_manquantes` (l'inventaire réel de l'écran
    « À placer ») pour rester cohérent avec ce qu'il verrait en l'ouvrant."""
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    placees = {p.session_id for p in state.timetable}
    scheduled_sae = load_solver_scheduled_sae(state.config_dir)
    for s in state.sessions:
        if s.id in placees:
            continue
        if code not in (s.teacher_codes or []):
            continue
        if s.course_code.upper().startswith("WS") and (s.course_code.upper(), s.semestre) not in scheduled_sae:
            continue
        return True
    return False


def _teacher_mail_text(state: object, code: str, name: str, link: str) -> tuple[str, str, str]:
    """`(subject, text_body, html_body)` — le texte brut reste la base
    identique au brouillon `mailto:` existant (`frontend/src/utils/
    mailto.ts`), pour que le contenu reste le même qu'un enseignant reçoive
    son lien via le mail auto ou via le bouton « Écrire » manuel de
    l'annuaire. Deux ajouts SPÉCIFIQUES à l'envoi auto, volontairement
    absents du brouillon manuel (celui-ci se rédige alors que l'admin
    regarde déjà l'écran de CET enseignant, ces deux infos y sont déjà
    visibles autrement) : le rappel des semestres couverts, et l'alerte
    "séances à placer" quand elle s'applique.

    Le HTML existe UNIQUEMENT pour que cette alerte ressorte comme un vrai
    encart d'avertissement (fond coloré, gras) — retour utilisateur
    28/08/2026 : « met l'invitation à placer les cours en warning pour que
    cela soit bien lu ». Un `text/plain` seul ne peut pas porter de mise en
    forme ; Resend (comme la plupart des clients mail) envoie les deux et
    laisse le client choisir, donc le texte brut reste la version de repli
    pour qui n'affiche pas le HTML."""
    items = [p for p in state.timetable if code in (p.teacher_codes or [])]
    sessions_by_id = state.sessions_by_id
    hours = sum((sessions_by_id[p.session_id].duration_slots or 1) if p.session_id in sessions_by_id else 1 for p in items) * 1.5
    hours_label = f"{hours:g}".replace(".", ",")
    semestres_label = _semestres_couverts_label(state)
    a_placer = _teacher_a_des_seances_non_placees(state, code)

    lignes = [
        f"Bonjour {name},",
        "",
        f"Voici votre emploi du temps : {link}",
        "",
        f"Il compte {len(items)} séance(s), soit {hours_label} h.",
        "Le lien ouvre directement votre planning ; un bouton permet d'exporter",
        "les séances vers votre agenda personnel (fichier .ics).",
    ]
    if semestres_label:
        lignes += ["", f"Cet emploi du temps couvre le(s) semestre(s) {semestres_label}."]
    if a_placer:
        lignes += [
            "",
            "⚠ Vous avez des séances qui n'ont pas encore pu être placées",
            "automatiquement dans l'emploi du temps. Merci de contacter le",
            "référent pour les positionner.",
        ]
    lignes += ["", "Une question ? Contactez Kyllian Bresson au 07 81 25 78 87.", "", "Cordialement,"]
    texte = "\n".join(lignes)

    import html as _html

    e = _html.escape
    warning_html = (
        '<div style="margin:16px 0;padding:12px 16px;background:#fff3cd;'
        "border:1px solid #f0ad4e;border-left:4px solid #f0ad4e;border-radius:4px;"
        'color:#664d03;font-weight:bold;">'
        "⚠️ Vous avez des séances qui n'ont pas encore pu être placées automatiquement "
        "dans l'emploi du temps. Merci de contacter le référent pour les positionner."
        "</div>"
    ) if a_placer else ""
    semestres_html = f"<p>Cet emploi du temps couvre le(s) semestre(s) {e(semestres_label)}.</p>" if semestres_label else ""
    html_body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.5;">'
        f"<p>Bonjour {e(name)},</p>"
        f'<p>Voici votre emploi du temps : <a href="{e(link)}">{e(link)}</a></p>'
        f"<p>Il compte {len(items)} séance(s), soit {hours_label} h.<br>"
        "Le lien ouvre directement votre planning ; un bouton permet d'exporter "
        "les séances vers votre agenda personnel (fichier .ics).</p>"
        f"{semestres_html}"
        f"{warning_html}"
        "<p>Une question ? Contactez Kyllian Bresson au 07 81 25 78 87.</p>"
        "<p>Cordialement,</p>"
        "</div>"
    )
    return "Votre emploi du temps MMI", texte, html_body


@app.get("/mail/teacher-links", response_model=TeacherMailPreviewListResponse, dependencies=[Depends(require_admin_session)])
def mail_teacher_links_preview() -> TeacherMailPreviewListResponse:
    """Annuaire d'envoi : un enseignant par ligne, adresse connue ou non
    (affichée quand même — absence visible plutôt que silencieuse, même
    principe que le bouton « Écrire » existant), et date du dernier envoi
    si déjà contacté (garde-fou contre un ré-envoi accidentel, l'écran
    d'envoi peut alors avertir avant de laisser cocher à nouveau)."""
    state = get_state()
    from cal_iut.ingestion.config_loader import load_teacher_contacts

    contacts = load_teacher_contacts(state.config_dir)
    noms = _noms_enseignants(state)
    codes = sorted({code for p in state.timetable for code in (p.teacher_codes or [])})
    log = mailer.sent_log()
    return TeacherMailPreviewListResponse(
        configured=mailer.is_configured(),
        teachers=[
            TeacherMailPreviewResponse(
                code=code,
                name=noms.get(code, code),
                email=contacts.get(code),
                sent_at=log.get(code, {}).get("sent_at"),
            )
            for code in codes
        ],
    )


@app.post("/mail/teacher-links/send", response_model=SendTeacherMailsResponse, dependencies=[Depends(require_admin_session)])
def mail_teacher_links_send(body: SendTeacherMailsRequest) -> SendTeacherMailsResponse:
    """Envoie le lien personnel à chaque code de `body.codes` — sélection
    TOUJOURS explicite depuis l'écran d'envoi, jamais un "tout le monde" par
    défaut côté serveur (retour utilisateur 25/08/2026, principe déjà
    appliqué ailleurs dans l'app : chaque ambiguïté se pose à l'utilisateur).
    Un échec sur UN enseignant n'interrompt pas les suivants — le rapport
    dit qui a réussi, qui a échoué, et pourquoi, jamais une réussite globale
    qui masquerait un échec partiel."""
    state = get_state()
    from cal_iut.ingestion.config_loader import load_teacher_contacts

    contacts = load_teacher_contacts(state.config_dir)
    noms = _noms_enseignants(state)
    resultats: list[TeacherMailSendResultResponse] = []
    for code in body.codes:
        email = contacts.get(code)
        if not email:
            resultats.append(TeacherMailSendResultResponse(code=code, ok=False, error="Aucune adresse connue pour ce trigramme."))
            continue
        try:
            link = mailer.personal_link(code)
            subject, texte, html_body = _teacher_mail_text(state, code, noms.get(code, code), link)
            message_id = mailer.send_email(email, subject, texte, html=html_body)
            mailer.record_sent(code, message_id)
            resultats.append(TeacherMailSendResultResponse(code=code, ok=True))
        except mailer.MailerNotConfigured as exc:
            resultats.append(TeacherMailSendResultResponse(code=code, ok=False, error=str(exc)))
        except Exception as exc:  # noqa: BLE001 — un envoi individuel raté ne doit jamais interrompre les autres
            resultats.append(TeacherMailSendResultResponse(code=code, ok=False, error=str(exc)))
    return SendTeacherMailsResponse(results=resultats)


def _find_placement(state: object, session_id: str) -> PlacedSessionWithRoom:
    if not state.timetable:
        raise HTTPException(404, "No timetable")
    match = next((p for p in state.timetable if p.session_id == session_id), None)
    if not match:
        raise HTTPException(404, f"Session {session_id} not found")
    return match


def _filter_unlocked(sessions: list[SessionToPlace], parcours: str | None, semestre: str | None) -> list[SessionToPlace]:
    result = [s for s in sessions if not s.locked]
    if parcours:
        result = [s for s in result if s.parcours == parcours]
    if semestre:
        result = [s for s in result if s.semestre == semestre]
    return result


def _merge_locked_placements(solver_placements: list[PlacedSession], locked: list[SessionToPlace], previous: list[object]) -> list[PlacedSession]:
    by_id = {p.session_id: p for p in solver_placements}
    prev = {p.session_id: p for p in previous} if previous else {}
    for s in locked:
        if s.id in by_id:
            continue
        p = prev.get(s.id)
        if p:
            by_id[s.id] = PlacedSession(s.id, p.week, p.day, p.slot, s.course_code, s.group_ids, s.teacher_codes)
        elif s.locked_day is not None:
            by_id[s.id] = PlacedSession(s.id, int(s.metadata.get("locked_week", 0)), s.locked_day, s.locked_slot, s.course_code, s.group_ids, s.teacher_codes)
    return list(by_id.values())


def _filter_timetable(
    timetable: list[PlacedSessionWithRoom],
    group_id: str | None,
    teacher_code: str | None,
    room_id: str | None,
    week: int | None,
    groups: list[Group] | None = None,
) -> list[PlacedSessionWithRoom]:
    result = list(timetable)
    if group_id:
        scope = expand_group_filter(group_id, groups or [])
        result = [p for p in result if scope.intersection(p.group_ids)]
    if teacher_code:
        result = [p for p in result if teacher_code in p.teacher_codes]
    if room_id:
        result = [p for p in result if getattr(p, "room_id", None) == room_id]
    if week is not None:
        result = [p for p in result if p.week == week]
    return result


def _as_placed(timetable: list[PlacedSessionWithRoom]) -> list[PlacedSession]:
    return [PlacedSession(p.session_id, p.week, p.day, p.slot, p.course_code, p.group_ids, p.teacher_codes) for p in timetable]


def _placement_dict(p: PlacedSessionWithRoom, sessions_by_id: dict[str, SessionToPlace] | None = None) -> dict[str, object]:
    locked = False
    if sessions_by_id and p.session_id in sessions_by_id:
        locked = sessions_by_id[p.session_id].locked
    return {
        "session_id": p.session_id,
        "week": p.week,
        "day": p.day,
        "slot": p.slot,
        "course_code": p.course_code,
        "room_id": getattr(p, "room_id", None),
        "room_label": getattr(p, "room_label", None),
        "locked": locked,
    }


def _build_response(status: str, objective: int | None, gap_penalty: int, placements: list[PlacedSessionWithRoom], sessions_by_id: dict[str, SessionToPlace], quality: object, run_id: int | None) -> TimetableResponse:
    return TimetableResponse(
        status=status,
        objective_value=objective,
        gap_penalty=gap_penalty,
        run_id=run_id,
        placements=[_to_placement(p, sessions_by_id) for p in placements],
        quality=QualityResponse(
            total_gaps=quality.total_gaps,
            isolated_days=quality.isolated_days,
            eval_days_with_multiple=quality.eval_days_with_multiple,
            unbalanced_groups=quality.unbalanced_groups,
            gaps_by_group=quality.gaps_by_group,
        ),
    )


def _to_placement(p: PlacedSessionWithRoom, sessions_by_id: dict[str, SessionToPlace]) -> PlacementResponse:
    s = sessions_by_id.get(p.session_id)
    return PlacementResponse(
        session_id=p.session_id,
        week=p.week,
        day=p.day,
        slot=p.slot,
        course_code=p.course_code,
        course_name=s.course_name if s else "",
        session_type=s.session_type.value if s else "",
        group_ids=p.group_ids,
        teacher_codes=p.teacher_codes,
        room_id=getattr(p, "room_id", None),
        room_label=getattr(p, "room_label", None),
        is_eval=s.is_eval if s else False,
        locked=s.locked if s else False,
        duration_slots=max(1, s.duration_slots) if s else 1,
    )


if FRONTEND_DIST.exists():
    # Racine de l'app : le frontend React (retour utilisateur 11/08/2026,
    # inverse la décision précédente qui servait la page HTML/JS ici — cf.
    # `/legacy`, conservée). DOIT rester le DERNIER mount/route déclaré dans ce
    # fichier : Starlette essaie les routes dans l'ORDRE D'AJOUT (donc l'ordre
    # du fichier), et `Mount("/")` matche n'importe quel chemin — placé plus
    # tôt, il aurait intercepté `/meta`, `/solve`, `/app-state`, etc. avant
    # qu'elles n'atteignent leur handler Python (bug réel évité ici, pas
    # théorique : c'était la position d'origine du mount avant ce correctif).
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
