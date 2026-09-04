"""API REST FastAPI — générateur d'emplois du temps IUT MMI Troyes."""

import hashlib
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cal_iut.api import accounts, auth, custom_rooms, custom_sessions, forced_pending, mailer, session_overrides
from cal_iut.api.regen import RegenError, regen_and_persist, resolve_semestre
from cal_iut.api.schemas import (
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
    DiffEntryResponse,
    EchangeRequest,
    EchangeResponse,
    DiffResponse,
    ExceptionCreateRequest,
    ExceptionResponse,
    FeedbackAnalysisResponse,
    ForcagePedagogiqueResponse,
    ForgotPasswordRequest,
    GroupMeta,
    IngestRequest,
    LoginRequest,
    MeResponse,
    MetaResponse,
    McpKeyCreatedResponse,
    McpKeyListResponse,
    McpKeyResponse,
    MoveSessionRequest,
    NotificationConfigRequest,
    NotificationConfigResponse,
    PatchSeanceRequest,
    PlacementResponse,
    QualityResponse,
    RegenRequest,
    RegenResultResponse,
    ResetPasswordRequest,
    CelcatCompteurs,
    CelcatEntreeResponse,
    CelcatEtatResponse,
    CelcatExtraActionResponse,
    CelcatPlanResponse,
    CelcatSaisieActiveRequest,
    CelcatSaisieRequest,
    CelcatSaisieResponse,
    CelcatValiderRequest,
    ChangeRoomRequest,
    CompletionResponse,
    CreerSeanceRequest,
    ModifierSeancePersonnaliseeRequest,
    CreneauLibreResponse,
    CreneauxLibresResponse,
    CreateRoomRequest,
    RoomMeta,
    SeanceAPlacerResponse,
    SeancePlaceeAutoResponse,
    SeanceRefuseeResponse,
    SeancesAPlacerResponse,
    SendTeacherMailsRequest,
    SendTeacherMailsResponse,
    SignupRequest,
    SignupResponse,
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
from cal_iut.db.accounts_repository import AccountRepository
from cal_iut.db.models import CurrentPlacement, User
from cal_iut.db.session import get_db
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
from cal_iut.models.entities import Group, SessionType
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


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Le session manager Streamable HTTP ne tourne PAS tout seul sur un
    # sous-app monté : le lifespan de l'hôte doit l'ouvrir (docs MCP v2).
    # `startup()` est appelé ICI plutôt qu'en `@app.on_event` : passer
    # `lifespan=` à FastAPI remplace les handlers on_event, et sans cet
    # appel le planning n'était plus restauré au démarrage.
    from cal_iut.mcp.server import mcp

    async with mcp.session_manager.run():
        startup()
        yield


app = FastAPI(title="cal-iut API", version="1.0.0", lifespan=_lifespan)

# Revue qualité du 31/08/2026 (système de comptes) : un mot de passe trop
# court (`Field(min_length=10)`) déclenche une 422 dont le corps par défaut
# de FastAPI/Pydantic renvoie le champ `input` = LA VALEUR SOUMISE TELLE
# QUELLE — le mot de passe en clair repart donc dans la réponse HTTP,
# capturable par les devtools, un historique de requêtes, ou un futur
# middleware de logs. Les champs sensibles sont donc caviardés avant que le
# corps d'erreur ne quitte le serveur, sans toucher au reste du
# comportement de validation (toujours 422, toujours le même message côté
# type d'erreur).
_CHAMPS_SENSIBLES_VALIDATION = {"password", "new_password"}


@app.exception_handler(RequestValidationError)
async def _erreurs_validation_sans_secret(request: Request, exc: RequestValidationError) -> JSONResponse:
    erreurs = []
    for erreur in exc.errors():
        erreur = dict(erreur)
        # `ctx.error` porte l'exception Python BRUTE d'un validateur custom
        # (ex. `_valider_email`, `schemas.py`) — non sérialisable en JSON,
        # `JSONResponse` (contrairement au `jsonable_encoder` par défaut de
        # FastAPI) ne sait pas l'encoder : trouvé en testant ce correctif
        # lui-même (500 sur un email malformé au lieu du 422 attendu).
        # `msg` porte déjà le texte utile, `ctx` est donc retiré plutôt que
        # converti — rien à en tirer côté client.
        erreur.pop("ctx", None)
        if any(str(segment) in _CHAMPS_SENSIBLES_VALIDATION for segment in erreur.get("loc", ())):
            erreur.pop("input", None)
            erreur["msg"] = "Valeur invalide."
        erreurs.append(erreur)
    return JSONResponse(status_code=422, content={"detail": erreurs})


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
    "/admin", "/app-state", "/celcat", "/corrections", "/diff", "/exceptions", "/export",
    "/feedback", "/ics", "/ingest", "/legacy", "/mail", "/meta", "/notifications",
    "/placements",
    "/auth/mcp-keys",
    "/regen", "/rooms", "/sessions", "/solve", "/timetable", "/weeks", "/weights",
)


# Routes volontairement PUBLIQUES. Toute route hors de cette liste ET hors
# de `_PROTECTED_PREFIXES` fait échouer le démarrage (cf.
# `_verifier_couverture_auth`) : c'est exactement comme ça que `POST /rooms`
# est resté accessible sans mot de passe le 28/08/2026 — un nouveau endpoint
# dont le chemin ne commençait par aucun préfixe connu devenait public en
# silence, sans que rien ne le signale (trouvé par l'utilisateur, pas par le
# code). Un oubli doit casser bruyamment, jamais ouvrir l'accès.
_PUBLIC_PATHS = frozenset({
    "/auth/login", "/auth/logout", "/auth/status", "/health",
    "/auth/signup", "/auth/confirm-email", "/auth/forgot-password",
    "/auth/reset-password", "/auth/me",
})

# Préfixes publics qui tombent DANS un préfixe protégé — l'exception doit
# donc être testée avant lui. Seul cas à ce jour : le pixel de suivi
# d'ouverture des mails, chargé par le client mail de l'enseignant, qui ne
# peut par nature présenter aucune session ni aucun lien perso.
_PUBLIC_PREFIXES = ("/mcp", "/mail/pixel/")


def _verifier_couverture_auth() -> list[str]:
    """Chemins ni protégés ni explicitement publics — vide = tout est couvert."""
    oublis = []
    for route in app.routes:
        chemin = getattr(route, "path", None)
        if not chemin or not getattr(route, "methods", None):
            continue
        if chemin.startswith(("/openapi", "/docs", "/redoc")):
            continue
        if chemin in _PUBLIC_PATHS or chemin.startswith(_PUBLIC_PREFIXES):
            continue
        if chemin.startswith(_PROTECTED_PREFIXES):
            continue
        oublis.append(chemin)
    return sorted(oublis)


def _account_repo() -> AccountRepository:
    return AccountRepository(get_db(get_state().db_path))


def _user_depuis_cle_api(request: Request) -> User | None:
    """Résout l'utilisateur depuis `Authorization: Bearer caliut_…` — même
    clé, même hash, même table que `/mcp` (`mcp.auth._principal_cle_user`),
    juste sans passer par le principal MCP puisqu'ici c'est un `User` complet
    qu'il faut, pour que `require_role` fonctionne à l'identique du cookie."""
    entete = request.headers.get("Authorization") or ""
    if not entete.startswith("Bearer "):
        return None
    brut = entete[len("Bearer ") :].strip()
    if not brut:
        return None
    from cal_iut.api.mcp_keys import hash_mcp_token

    repo = _account_repo()
    cle = repo.get_active_mcp_key_by_hash(hash_mcp_token(brut))
    if cle is None:
        return None
    user = repo.get_by_id(cle.user_id)
    if user is None:
        return None
    # PAS de `touch_mcp_key` ici : ça commit(), qui EXPIRE tous les objets
    # de la session (dont `user`) — `require_role`, appelé bien plus tard
    # dans la requête, retomberait sur un `DetachedInstanceError` dès que
    # cette fonction (et sa session locale) sort de portée. La date de
    # dernier usage reste à jour via `/mcp`, qui suit le même chemin de clé
    # mais garde sa session ouverte tout du long (`mcp.auth._principal_cle_user`).
    return user


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    if not path.startswith(_PROTECTED_PREFIXES):
        return await call_next(request)

    # Lien personnel (prof ou groupe) — public depuis le 28/08/2026, cf.
    # docstring de `auth.py` pour l'historique (jeton HMAC d'abord, puis
    # "on s'en fiche on veut qu'il soit public" en retour utilisateur final).
    if auth.verify_personal_link_param(request.query_params.get("t")):
        return await call_next(request)

    user_id = accounts.verify_account_session_token(request.cookies.get(accounts.ACCOUNT_SESSION_COOKIE))
    user = _account_repo().get_by_id(user_id) if user_id is not None else None
    if user is None:
        # Pas de cookie (ou cookie invalide) : une clé « caliut_… » créée
        # via /auth/mcp-keys authentifie aussi les routes générales,
        # exactement comme /mcp (`mcp.auth.authentifier_bearer`) — même
        # table, même hash, même rôle relu sur le compte. Retour
        # utilisateur 05/09/2026 : accès programmatique (`cal-iut prod
        # diff/pull/push`) sans donner d'identifiants personnels.
        user = _user_depuis_cle_api(request)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Authentification requise."})
    if user.status != "active":
        # Rôle et permissions précis restent du ressort de `require_role`
        # (Depends par route) — ce contrôle ICI ne fait que le PLANCHER
        # commun à toute route protégée : un compte encore en attente
        # d'activation admin, ou désactivé, ne doit accéder à RIEN de
        # protégé, même en lecture.
        return JSONResponse(
            status_code=403,
            content={"detail": "Compte en attente d'activation.", "status": user.status},
        )
    request.state.user = user
    return await call_next(request)


from cal_iut.mcp.auth import mcp_bearer_middleware

app.middleware("http")(mcp_bearer_middleware)

# `require_admin_session` (mot de passe partagé, `auth.verify_session_token`)
# a existé ici avant le système de comptes du 31/08/2026 — remplacé
# partout par `Depends(require_role("admin"))`, plus aucun appelant : cf.
# rebase de la branche comptes-utilisateurs sur celle-ci, aucune route ne
# référence plus `require_admin_session` après fusion (vérifié par grep).


@app.post("/auth/signup", response_model=SignupResponse, status_code=201)
def auth_signup(body: SignupRequest) -> SignupResponse | JSONResponse:
    # Vérifié EN PREMIER, avant toute écriture en base : un compte qu'aucun
    # mail de confirmation ne pourra jamais atteindre resterait bloqué en
    # `pending_email` pour toujours — même philosophie que l'ancien
    # `CAL_IUT_PASSWORD` absent (`api/auth.py`, historique) : un oubli de
    # configuration doit être visible, jamais confondu avec "ça a marché".
    # Corps `{"message": ...}` à PLAT, cf. `admin_update_user` pour pourquoi
    # `JSONResponse` directement plutôt que `HTTPException(detail=...)`.
    if not mailer.is_configured():
        return JSONResponse(
            status_code=503,
            content={"message": "Envoi d'email non configuré (RESEND_API_KEY/CAL_IUT_PUBLIC_URL absent)."},
        )

    email = accounts.normalize_email(body.email)
    repo = _account_repo()
    existing = repo.get_by_email(email)
    if existing is not None and existing.status != "pending_email":
        return JSONResponse(status_code=409, content={"message": "Un compte existe déjà pour cet email."})

    if existing is None:
        user = repo.create_pending_user(email, accounts.hash_password(body.password))
    else:
        # Anti mail-scanner-prefetch (décision verrouillée) : un second
        # signup sur une adresse encore `pending_email` ne 409 PAS, il
        # réémet un jeton frais et invalide les précédents plutôt que de
        # laisser croire qu'il n'y a rien à faire.
        user = existing
        repo.invalidate_outstanding_tokens(user.id, "confirm_email")

    raw, token_hash = accounts.build_confirm_token()
    repo.create_token(user.id, token_hash, "confirm_email", accounts.confirm_token_expiry())
    link = accounts.confirmation_link(raw)
    # Revue qualité du 31/08/2026 : contrairement à `/auth/forgot-password`,
    # cet envoi n'était pas protégé — une panne Resend (ou une adresse
    # rejetée) devenait une 500 brute côté client, alors que le compte
    # `pending_email` est déjà créé/committé à ce stade. Le compte reste
    # utilisable : un nouveau signup sur la même adresse réempruntera le
    # chemin "réémission" plus haut plutôt que d'échouer à nouveau à froid.
    try:
        mailer.send_email(
            email,
            "Confirmez votre compte cal-iut",
            f"Bonjour,\n\nConfirmez votre compte en cliquant sur ce lien : {link}\n\n"
            "Ce lien expire dans 48 heures.",
        )
    except Exception as exc:  # noqa: BLE001 — jamais une 500 brute pour un appel public non authentifié
        print(f"[auth_signup] échec d'envoi du mail de confirmation à {email} : {exc}", file=sys.stderr)
        return JSONResponse(
            status_code=502,
            content={"message": "Le compte a été créé mais l'email de confirmation n'a pas pu être envoyé. Réessayez dans un instant."},
        )
    return SignupResponse(status="pending_email")


@app.get("/auth/confirm-email")
def auth_confirm_email(token: str) -> RedirectResponse:
    base = accounts.public_base_url_or_placeholder()
    repo = _account_repo()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    entry = repo.get_valid_token(token_hash, "confirm_email")
    if entry is None:
        return RedirectResponse(f"{base}/#compte=confirme&statut=erreur", status_code=302)

    user = repo.get_by_id(entry.user_id)
    repo.consume_token(entry)
    if user is not None:
        repo.mark_email_confirmed(user)
    return RedirectResponse(f"{base}/#compte=confirme&statut=ok", status_code=302)


@app.post("/auth/login")
def auth_login(body: LoginRequest, response: Response) -> dict:
    email = accounts.normalize_email(body.email)
    repo = _account_repo()
    user = repo.get_by_email(email)
    # Message et code IDENTIQUES pour un email inconnu et un mauvais mot de
    # passe — pas d'énumération de comptes.
    if user is None or not accounts.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    if user.status == "pending_email":
        raise HTTPException(403, "Confirmez votre email avant de vous connecter.")
    if user.status == "disabled":
        raise HTTPException(403, "Compte désactivé.")
    response.set_cookie(
        accounts.ACCOUNT_SESSION_COOKIE, accounts.make_account_session_token(user.id),
        max_age=accounts.ACCOUNT_SESSION_MAX_AGE_S, httponly=True, samesite="lax",
    )
    return {"role": user.role, "status": user.status}


@app.post("/auth/logout")
def auth_logout(response: Response) -> dict:
    response.delete_cookie(accounts.ACCOUNT_SESSION_COOKIE)
    return {"ok": True}


@app.get("/auth/status")
def auth_status(request: Request) -> dict:
    return {"authenticated": accounts.get_current_user(request, optional=True) is not None}


@app.post("/auth/forgot-password")
def auth_forgot_password(body: ForgotPasswordRequest) -> dict:
    # TOUJOURS 200 — un email inconnu ne doit jamais être distinguable d'un
    # email connu (même principe anti-énumération que `/auth/login`).
    email = accounts.normalize_email(body.email)
    repo = _account_repo()
    user = repo.get_by_email(email)
    if user is not None and user.status == "active":
        repo.invalidate_outstanding_tokens(user.id, "reset_password")
        raw, token_hash = accounts.build_reset_token()
        repo.create_token(user.id, token_hash, "reset_password", accounts.reset_token_expiry())
        link = accounts.reset_password_link(raw)
        try:
            mailer.send_email(
                email,
                "Réinitialisation de votre mot de passe cal-iut",
                f"Bonjour,\n\nRéinitialisez votre mot de passe en cliquant sur ce lien : {link}\n\n"
                "Ce lien expire dans 1 heure. Si vous n'êtes pas à l'origine de cette "
                "demande, ignorez cet e-mail.",
            )
        except Exception:  # noqa: BLE001, S110 — un échec d'envoi ne doit jamais se voir depuis l'extérieur (200 toujours)
            pass
    # Autres cas (inconnu, pending, disabled) : silencieux côté réponse,
    # mais jamais côté serveur — un compte non éligible reste une trace
    # utile en cas d'abus répété.
    return {"ok": True}


@app.post("/auth/reset-password")
def auth_reset_password(body: ResetPasswordRequest) -> dict:
    repo = _account_repo()
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    entry = repo.get_valid_token(token_hash, "reset_password")
    if entry is None:
        raise HTTPException(400, "Lien de réinitialisation invalide ou expiré.")
    user = repo.get_by_id(entry.user_id)
    if user is None:
        raise HTTPException(400, "Lien de réinitialisation invalide ou expiré.")
    if user.status == "disabled":
        raise HTTPException(403, "Compte désactivé.")

    user.password_hash = accounts.hash_password(body.new_password)
    repo.db.commit()
    repo.consume_token(entry)
    # Invalide TOUT le reste (y compris un autre jeton reset encore valide,
    # jamais utilisé lui-même) : un mot de passe qui vient de changer rend
    # tout lien de réinitialisation antérieur obsolète, y compris ceux dont
    # on ignore s'ils ont fuité.
    repo.invalidate_outstanding_tokens(user.id, "reset_password")
    return {"ok": True}


@app.get("/auth/me", response_model=MeResponse)
def auth_me(request: Request) -> MeResponse:
    user = accounts.get_current_user(request)
    return MeResponse(id=user.id, email=user.email, role=user.role, status=user.status)


def _mcp_key_to_response(cle: object, *, token: str | None = None) -> McpKeyResponse | McpKeyCreatedResponse:
    base = {
        "id": cle.id,
        "prefix": cle.prefix,
        "created_at": cle.created_at.isoformat() if cle.created_at else "",
        "last_used_at": cle.last_used_at.isoformat() if cle.last_used_at else None,
    }
    if token is not None:
        return McpKeyCreatedResponse(token=token, **base)
    return McpKeyResponse(**base)


@app.get("/auth/mcp-keys", response_model=McpKeyListResponse, dependencies=[Depends(accounts.require_role("read_only"))])
def auth_list_mcp_keys(request: Request) -> McpKeyListResponse:
    user: User = request.state.user
    repo = _account_repo()
    return McpKeyListResponse(keys=[_mcp_key_to_response(c) for c in repo.list_active_mcp_keys(user.id)])


@app.post("/auth/mcp-keys", response_model=McpKeyCreatedResponse, dependencies=[Depends(accounts.require_role("read_only"))])
def auth_create_mcp_key(request: Request) -> McpKeyCreatedResponse | JSONResponse:
    from cal_iut.api.mcp_keys import MCP_MAX_ACTIVE_KEYS, generate_raw_mcp_token, hash_mcp_token, visible_prefix

    user: User = request.state.user
    repo = _account_repo()
    if repo.count_active_mcp_keys(user.id) >= MCP_MAX_ACTIVE_KEYS:
        return JSONResponse(
            status_code=409,
            content={"message": f"Limite de {MCP_MAX_ACTIVE_KEYS} clés MCP atteinte. Révoquez-en une d'abord."},
        )
    brut = generate_raw_mcp_token()
    cle = repo.create_mcp_key(user.id, hash_mcp_token(brut), visible_prefix(brut))
    return _mcp_key_to_response(cle, token=brut)


@app.delete("/auth/mcp-keys/{key_id}", dependencies=[Depends(accounts.require_role("read_only"))])
def auth_revoke_mcp_key(key_id: int, request: Request) -> dict:
    user: User = request.state.user
    repo = _account_repo()
    cle = repo.get_mcp_key_for_user(key_id, user.id)
    if cle is None:
        return JSONResponse(status_code=404, content={"message": "Clé introuvable."})
    repo.revoke_mcp_key(cle)
    return {"ok": True}


@app.get("/admin/users", response_model=AdminUserListResponse, dependencies=[Depends(accounts.require_role("admin"))])
def admin_list_users(status: str | None = None) -> AdminUserListResponse:
    repo = _account_repo()
    return AdminUserListResponse(users=[_user_to_admin_response(u) for u in repo.list_users(status=status)])


@app.patch("/admin/users/{user_id}", response_model=AdminUserResponse, dependencies=[Depends(accounts.require_role("admin"))])
def admin_update_user(user_id: int, body: AdminUserUpdateRequest, request: Request) -> AdminUserResponse | JSONResponse:
    # Corps d'erreur `{"message": ...}` à PLAT (pas sous `detail`, contrairement
    # au défaut de `HTTPException` — le contrat exige la même forme que le
    # reste des 409 de cette API) : construit via `JSONResponse` directement,
    # un route FastAPI peut rendre un `Response` en dehors de son
    # `response_model` sans que celui-ci intervienne.
    if body.role is None and body.status is None:
        return JSONResponse(status_code=400, content={"message": "Fournissez au moins `role` ou `status`."})

    repo = _account_repo()
    target = repo.get_by_id(user_id)
    if target is None:
        return JSONResponse(status_code=404, content={"message": "Utilisateur introuvable."})

    acting_admin: User = request.state.user  # posé par `require_auth`, toujours présent ici

    # Simule le résultat AVANT d'écrire quoi que ce soit, pour refuser
    # proprement (409) plutôt que de désactiver le dernier admin puis
    # constater le dégât.
    role_apres = body.role if body.role is not None else target.role
    status_apres = body.status if body.status is not None else target.status
    activation_implicite = (
        body.role is not None and body.status is None and target.status == "pending_admin_activation"
    )
    if activation_implicite:
        status_apres = "active"
    sera_admin_actif = role_apres == "admin" and status_apres == "active"
    etait_admin_actif = target.role == "admin" and target.status == "active"
    if etait_admin_actif and not sera_admin_actif and repo.count_active_admins() <= 1:
        return JSONResponse(
            status_code=409,
            content={"message": "Impossible de retirer le dernier administrateur actif."},
        )

    if activation_implicite:
        repo.activate(target, role_apres, acting_admin.id)
    else:
        if body.role is not None:
            repo.set_role(target, body.role)
        if body.status is not None:
            repo.set_status(target, body.status)

    return _user_to_admin_response(target)


def _user_to_admin_response(user: object) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at.isoformat() if user.created_at else "",
        email_confirmed_at=user.email_confirmed_at.isoformat() if user.email_confirmed_at else None,
        activated_at=user.activated_at.isoformat() if user.activated_at else None,
    )


def startup() -> None:
    oublis = _verifier_couverture_auth()
    if oublis:
        raise RuntimeError(
            "Endpoint(s) sans protection d'authentification : "
            + ", ".join(oublis)
            + ". Ajoutez le préfixe à `_PROTECTED_PREFIXES`, ou le chemin à "
            "`_PUBLIC_PATHS` si l'accès public est VOULU."
        )

    state = get_state()
    state.config_dir = CONFIG_DIR
    state.groups = load_groups(CONFIG_DIR)
    # Salles du bâtiment + celles ajoutées depuis l'interface (volume
    # persistant, cf. `api/custom_rooms.py`).
    state.rooms = custom_rooms.merge_into(load_rooms(CONFIG_DIR))
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
        # Séances ajoutées depuis l'interface (volume persistant, cf.
        # `api/custom_sessions.py`) — une ré-ingestion écrase `state.sessions`
        # entièrement, elles disparaîtraient sinon jusqu'au prochain ajout.
        state.sessions, state.sessions_by_id = custom_sessions.merge_into(
            state.sessions, state.sessions_by_id
        )
        session_overrides.apply_to(state.sessions_by_id)

        current = repo.db.query(CurrentPlacement).filter_by(run_id=run.id).all()
        # Un placement dont la séance n'existe PLUS après ré-ingestion est un
        # fantôme : séance annulée (`seances_annulees.yaml`) ou disparue de la
        # maquette. Le garder l'afficherait sans groupe ni enseignant, il
        # occuperait une salle dans les contrôles de conflit, et il
        # reviendrait à chaque redémarrage. On le retire de la base au
        # passage, sinon la ligne morte survit indéfiniment.
        orphelins = [c for c in current if c.session_id not in state.sessions_by_id]
        if orphelins:
            for c in orphelins:
                repo.remove_current_placement(c.session_id)
            current = [c for c in current if c.session_id in state.sessions_by_id]
        if current:
            state.timetable = [
                PlacedSessionWithRoom(
                    session_id=c.session_id,
                    week=c.week,
                    day=c.day,
                    slot=c.slot,
                    course_code=c.course_code,
                    group_ids=state.sessions_by_id[c.session_id].group_ids,
                    teacher_codes=state.sessions_by_id[c.session_id].teacher_codes,
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


# Clés du payload retirées pour une requête NON authentifiée (lien personnel
# public). Deux natures :
#   - données personnelles : adresses mail des enseignants, et leurs
#     contraintes déclarées en texte libre (« mercredi toute la journée »,
#     « possible lundi si besoin »...) — 32 adresses et une trentaine de
#     contraintes se retrouvaient sur une URL publique, alors qu'un lien
#     perso n'a besoin QUE d'afficher un planning ;
#   - données d'administration : inventaire des séances non placées,
#     vérifications de règles, exceptions — jamais affichées en lecture
#     seule, aucune raison d'être envoyées.
# Le nom des enseignants (`teacherLabels`) reste, lui : il s'affiche sur les
# séances de n'importe quel emploi du temps, c'est l'objet même de l'outil.
_CLES_PRIVEES_PAYLOAD = ("teacherEmails", "teachers", "seancesNonPlacees", "ruleChecks", "exceptions")


@app.get("/app-state")
def app_state(request: Request) -> dict[str, object]:
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

    payload = build_payload(
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

    # Session de compte (n'importe quel rôle actif) = payload complet. Lien
    # personnel public = version expurgée (cf. `_CLES_PRIVEES_PAYLOAD`).
    # Filtré ICI, à la sortie, plutôt qu'en amont dans `build_payload` : une
    # seule liste à relire pour savoir ce qui sort, et `/legacy` (page
    # admin) continue d'utiliser le calcul complet sans condition.
    if accounts.get_current_user(request, optional=True) is not None:
        return payload
    vide: dict[str, object] = {"teacherEmails": {}}
    return {k: (vide.get(k, []) if k in _CLES_PRIVEES_PAYLOAD else v) for k, v in payload.items()}


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


@app.post("/ingest", dependencies=[Depends(accounts.require_role("edit"))])
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
    state.sessions, state.sessions_by_id = custom_sessions.merge_into(
        state.sessions, state.sessions_by_id
    )
    session_overrides.apply_to(state.sessions_by_id)
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


@app.post("/solve", response_model=TimetableResponse, dependencies=[Depends(accounts.require_role("edit"))])
def solve(body: SolveRequest) -> TimetableResponse:
    return _solve_and_persist(body)


@app.post("/solve/async", dependencies=[Depends(accounts.require_role("edit"))])
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


@app.post("/regen/week", dependencies=[Depends(accounts.require_role("edit"))])
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


@app.post("/exceptions", response_model=ExceptionResponse, dependencies=[Depends(accounts.require_role("edit"))])
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


@app.delete("/exceptions/{exception_id}", dependencies=[Depends(accounts.require_role("edit"))])
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


@app.post("/feedback/apply", dependencies=[Depends(accounts.require_role("edit"))])
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


# Le contenu est déjà recalculé EN DIRECT sur `state.timetable` à chaque
# requête (rien n'est mis en cache côté serveur) — la seule staleness
# possible vient d'un intermédiaire HTTP (proxy, CDN) qui garderait une
# vieille réponse. `no-store` empêche ça explicitement. Retour utilisateur
# 04/09/2026 : « en temps réel ou 1h max » — ce qu'on contrôle vraiment
# (le serveur) est donc déjà à jour à chaque fois ; ce qu'on ne contrôle
# PAS, c'est la fréquence à laquelle Google/Outlook/Apple repollent une URL
# .ics abonnée (souvent plusieurs heures, parfois ~24h pour Google — aucun
# en-tête ne force ça depuis le serveur).
_ICS_CACHE_HEADERS = {"Cache-Control": "no-store, max-age=0"}


def _ics_items_for_placements(state: object, placements: list) -> list:
    """`IcsItem` par placement — date calculée depuis le SEMESTRE PROPRE à
    chaque séance (pas un semestre de référence unique, cf. `ics_feed.py`
    pour pourquoi c'est important pour un flux personnel)."""
    from cal_iut.api.ics_feed import IcsItem
    from cal_iut.export.formatter import SLOT_TIMES as _ICS_SLOT_TIMES

    items = []
    # Dates de dernière modification, lues en UNE fois : une requête par
    # séance ferait des centaines d'allers-retours pour un flux d'agenda
    # re-téléchargé toutes les six heures par chaque abonné.
    modifie_le = _ics_placements_updated_at(state)

    for p in placements:
        session = state.sessions_by_id.get(p.session_id)
        semestre = getattr(session, "semestre", None) or _export_semestre(state)
        # `duration_slots` (ex. 2 = bloc de 3h, "2×1h30 collées" —
        # `double_sessions.yaml`) N'ÉTAIT PAS lu ici : la fin d'un bloc de 3h
        # se calculait sur le SEUL créneau de départ (`_ICS_SLOT_TIMES[p.slot]`),
        # tronquant silencieusement la seconde moitié — la Vue Promo affichait
        # bien les 2 créneaux (WSA501D 9h30-12h30, 4/09/2026), le flux .ics
        # s'arrêtait à 11h. Retour utilisateur (04/09/2026, capture d'écran à
        # l'appui) : "j'ai bien une séance à 11h to 12h30". Fin = fin du
        # DERNIER créneau occupé, pas du premier.
        duree = max(1, getattr(session, "duration_slots", None) or 1)
        slot_fin = p.slot + duree - 1
        start = _ICS_SLOT_TIMES[p.slot][0] if 0 <= p.slot < len(_ICS_SLOT_TIMES) else ""
        end = _ICS_SLOT_TIMES[slot_fin][1] if 0 <= slot_fin < len(_ICS_SLOT_TIMES) else start
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
            # Alimente `SEQUENCE`/`LAST-MODIFIED` : sans elle, un agenda déjà
            # abonné ne voit pas qu'une séance a bougé (retour de David
            # Annebicque, 29/08/2026).
            updated_at=modifie_le.get(p.session_id),
        ))
    return items


def _ics_placements_updated_at(state: object) -> dict[str, object]:
    """`session_id -> updated_at`, lu en UNE fois — même source que
    `_ics_items_for_placements` (`CurrentPlacement`), factorisé ici pour
    être réutilisé par `/ics/version` sans dupliquer la requête DB."""
    if not state.current_run_id:
        return {}
    try:
        from cal_iut.db.models import CurrentPlacement

        return {
            row.session_id: row.updated_at
            for row in get_repo().db.query(CurrentPlacement).filter_by(run_id=state.current_run_id).all()
        }
    except Exception:  # noqa: BLE001 — pas d'horodatage vaut mieux qu'un crash
        return {}


def _ics_versions(state: object) -> dict[str, list[dict[str, object]]]:
    """Pour CHAQUE groupe et CHAQUE enseignant : la date de dernière
    modification et le lien `.ics` à réinterroger si elle a avancé.

    Retour utilisateur (04/09/2026) : un collègue qui développe sa propre
    appli EDT repolle les flux `.ics` en boucle serrée pour détecter un
    changement — « ça fait des requêtes de fou ». Ici il peut sonder CET
    endpoint (petit JSON, pas cher) et n'aller rechercher le `.ics` complet
    que pour les groupes/enseignants dont `derniere_modification` a bougé
    depuis son dernier sondage — pas de nouvelle infra (webhook, SSE),
    juste une manière économique de savoir QUOI rafraîchir.
    """
    from cal_iut.models.group_scope import expand_group_filter

    modifie_le = _ics_placements_updated_at(state)

    # Index UNE fois : session_ids par group_id "brut" (avant fusion de
    # cohorte) et par code enseignant — évite de reparcourir tout
    # `state.timetable` pour chacun des ~80 groupes/enseignants.
    par_groupe_brut: dict[str, list[str]] = {}
    par_enseignant: dict[str, list[str]] = {}
    for p in state.timetable:
        for gid in p.group_ids or []:
            par_groupe_brut.setdefault(gid, []).append(p.session_id)
        for code in p.teacher_codes or []:
            par_enseignant.setdefault(code, []).append(p.session_id)

    def _plus_recent(session_ids: list[str]) -> str | None:
        horodatages = [modifie_le[sid] for sid in session_ids if modifie_le.get(sid) is not None]
        if not horodatages:
            return None
        recent = max(horodatages)
        return recent.isoformat() if hasattr(recent, "isoformat") else str(recent)

    groupes = []
    for g in state.groups:
        cohort = expand_group_filter(g.id, state.groups)
        ids = [sid for cid in cohort for sid in par_groupe_brut.get(cid, [])]
        groupes.append({
            "id": g.id, "label": g.label,
            "derniere_modification": _plus_recent(ids),
            "lien": f"/ics/groupe/{g.id}.ics",
        })

    noms = _noms_enseignants(state)
    enseignants = []
    for code in sorted(par_enseignant):
        enseignants.append({
            "code": code, "label": noms.get(code, code),
            "derniere_modification": _plus_recent(par_enseignant[code]),
            "lien": f"/ics/prof/{code}.ics",
        })

    return {"groupes": groupes, "enseignants": enseignants}


@app.get("/ics/version")
def ics_version() -> Response:
    """Petit JSON — dernière modification par groupe/enseignant, et le lien
    `.ics` à réinterroger si elle a avancé (cf. `_ics_versions`). Pensé
    pour être sondé BEAUCOUP plus souvent que les flux `.ics` complets
    (aucun calcul de calendrier, juste des horodatages)."""
    state = get_state()
    import json as _json

    contenu = _json.dumps(_ics_versions(state), ensure_ascii=False)
    return Response(
        content=contenu, media_type="application/json; charset=utf-8",
        headers=dict(_ICS_CACHE_HEADERS),
    )


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
        headers={
            "Content-Disposition": f'inline; filename="planning-{code}.ics"',
            **_ICS_CACHE_HEADERS,
        },
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
        headers={
            "Content-Disposition": f'inline; filename="planning-{group_id}.ics"',
            **_ICS_CACHE_HEADERS,
        },
    )


def _check_move_editable(
    state: object, session_id: str, source_week: int, dest_week: int, *, force: bool = False
) -> None:
    """
    Rejette un déplacement (manuel, glisser-déposer) touchant une semaine
    passée ou en cours — que ce soit la semaine SOURCE ou DESTINATION. Ce
    contrôle n'existait pas jusqu'ici sur l'endpoint unitaire (`PATCH
    /placements/{id}`), seule la régénération par lot (`/regen/week`) le
    faisait — retrofit nécessaire : un simple glisser-déposer aurait pu
    déplacer une séance déjà passée sans qu'aucun garde-fou ne l'empêche.

    CONTOURNABLE via `force` depuis le 29/08/2026 (retour utilisateur :
    « il faut que les séances soient modifiables à tout moment pour
    l'instant en forçant, on est en train de tester donc on va unlock cela,
    mais ce sera sûrement à remettre par la suite »). Le cas qui l'a rendu
    nécessaire : un vacataire signale son indisponibilité le samedi pour la
    semaine qui commence le lundi — or le week-end bascule déjà sur cette
    semaine-là (`current_relative_week`), qui devient donc non modifiable
    au moment PRÉCIS où il faut la corriger.

    Le garde-fou reste actif par défaut : forcer est un geste explicite,
    jamais le comportement normal.
    """
    motifs = _semaines_non_modifiables(state, session_id, source_week, dest_week, force=force)
    if motifs:
        raise HTTPException(409, motifs[0])


def _semaines_non_modifiables(
    state: object, session_id: str, source_week: int, dest_week: int, *, force: bool = False
) -> list[str]:
    """Les motifs de `_check_move_editable`, RENDUS au lieu d'être levés.

    Existe pour la vérification à blanc (`validate_placement`), qui doit
    DÉCRIRE un obstacle et non le refuser : côté navigateur, une erreur HTTP
    sur la validation sort par le `catch` de `performMove` et n'atteint
    jamais la modale « Forcer le déplacement ». Le glisser-déposer de la Vue
    Promo ne faisait donc plus rien du tout sur la semaine EN COURS, sans
    même dire pourquoi (retour utilisateur 29/08/2026). Un motif rendu ici
    devient un `hard_conflict` ordinaire, donc forçable — ce que le verrou de
    semaine est explicitement censé être.
    """
    if force:
        return []
    session = state.sessions_by_id.get(session_id)
    semestre = session.semestre if session else resolve_semestre(state)
    return [
        f"Semaine {w + 1} non modifiable (statut : {status})"
        for w in sorted({source_week, dest_week})
        if (status := week_status(state.calendar, semestre, w)) != "future"
    ]


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

    # Jours FÉRIÉS et fermetures (vacances, journées bloquées). Le solveur
    # les respecte depuis toujours (`constraints.py::
    # add_blocked_calendar_constraints`), mais ce chemin MANUEL ne les
    # regardait pas : un glisser-déposer pouvait poser un cours le 11
    # novembre, et c'est exactement ce qui est arrivé — une seule séance de
    # tout le planning, repérée par Kyllian Bresson le 30/08/2026 alors
    # qu'elle était déjà en production.
    #
    # Même famille de défaut que celui du 26/08 (les règles
    # institutionnelles ne servaient qu'à filtrer les suggestions) : une
    # contrainte que le solveur honore, mais qu'une porte manuelle
    # contourne sans que rien ne l'arrête.
    for week in range(n_weeks):
        for jour in range(5):
            jour_reel = state.calendar.week_day_to_date(week_offset + week, jour)
            if jour_reel is None:
                continue
            if jour_reel in state.calendar.holidays or jour_reel in state.calendar.blocked_dates:
                for slot in range(6):
                    extra_blocked.add((week, jour, slot))

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

    # Une SAE (WS*) ne sanctuarise PAS son propre jour : ce jour n'est bloqué
    # que pour les ressources classiques (WR/WRA), exactement comme le
    # solveur (`solver/constraints.py::add_sae_sanctuarization_constraints`,
    # `if session.is_unplaced_sae: continue`) — les enseignants planifient
    # eux-mêmes leurs séances SAE (`docs/DATA.md` §8.2/§15.1), donc placer une
    # séance WS un jour de SAE, potentiellement CE jour-là, doit rester
    # possible. Manquait ici (retour utilisateur 03/09/2026 : "on ne peut pas
    # placer des cours de SAE dans les SAE") — le déplacement manuel n'avait
    # jamais reçu cette exemption, contrairement au solveur.
    if not getattr(session, "is_unplaced_sae", False):
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


def _libelle_jour_ferme(state: object, semestre: str, week: int, day: int) -> str | None:
    """« férié (11/11/2026) » plutôt qu'un motif générique — sans la date, la
    personne qui lit le refus ne sait pas quoi vérifier."""
    try:
        offset = semester_week_offset(state.calendar, semestre)
        jour = state.calendar.week_day_to_date(offset + week, day)
    except Exception:  # noqa: BLE001
        return None
    if jour is None:
        return None
    if jour in state.calendar.holidays:
        return f"Jour férié ({jour.strftime('%d/%m/%Y')}) : l'IUT est fermé."
    if jour in state.calendar.blocked_dates:
        return f"Journée fermée ({jour.strftime('%d/%m/%Y')}) : vacances ou fermeture déclarée."
    return None


def _institutional_violations(
    week: int, day: int, slot: int,
    extra_blocked: set[tuple[int, int, int]],
    libelle_calendrier: str | None = None,
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
        # Le motif NOMME la cause quand on la connaît : « Jour férié
        # (11/11/2026) » se vérifie d'un coup d'œil, « créneau
        # institutionnellement bloqué » laisse chercher.
        violations.append(
            libelle_calendrier
            or (
                "Créneau institutionnellement bloqué (jeudi après-midi PAC, fin de semestre, "
                "journée SAE sanctuarisée pour les cours classiques WR*, événement du planning "
                "officiel à cet horaire précis, ou présence IUT d'un alternant) — non modifiable, "
                "même en forçant. Exception : une séance SAE (code WS*) peut être placée un jour de SAE."
            )
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
    augmenté une fois au démarrage, cf. `startup()`). Signalée systématiquement
    (retour utilisateur 11/08/2026 : "vérifie bien toutes les contraintes
    avant que ça s'effectue" — avant ce correctif, ces indisponibilités ne
    servaient qu'à FILTRER les suggestions via `_teacher_free_at`, déjà
    appelé par `_suggestions_for` ; un glisser-déposer direct sur une case
    arbitraire, hors suggestion, pouvait les violer sans aucun garde-fou
    serveur).

    Contournable via `force` depuis le 03/09/2026 (retour Kyllian Bresson :
    « des fois ils acceptent de faire cours quand même haha ») — même
    traitement que l'ordre pédagogique (28/08/2026), à la différence du
    verrou PAC/SAE (`_institutional_violations`), qui lui reste
    définitivement non contournable : un humain peut avoir une bonne raison
    ponctuelle de placer un cours chez un enseignant indisponible sur le
    papier (accord donné à l'oral), jamais de casser un jeudi PAC.
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
        "un placement manuel avec « Forcer » peut débloquer, si l'enseignant a "
        "accepté malgré tout."
    ]


def _conflits_deplacement(
    state: object, session: object, week: int, day: int, slot: int
) -> tuple[list[str], list[str]]:
    """Point d'entrée UNIQUE pour « qu'est-ce qui bloque ce créneau ? »,
    utilisé par `validate_placement`, `move_session`, `placer_seance`,
    `_controler_echange` ET le côté MCP (`mcp/tools.py::_evaluer_move`).

    Avant ce regroupement (03/09/2026), les cinq appelants recopiaient les
    mêmes quatre lignes — `_hard_constraint_context` puis
    `_institutional_violations`/`_pedagogical_order_violations`/
    `_teacher_availability_violations` assemblées à la main. Le risque
    concret : le 03/09/2026, rendre l'indisponibilité enseignant
    force-able a d'abord été fait sur les 4 appelants de `main.py` SEULEMENT
    — la copie MCP, oubliée dans le même geste, a fait échouer un test
    avant d'être retrouvée. Un seul point d'entrée empêche ce genre de
    divergence silencieuse entre les deux surfaces (HTTP et MCP).

    Rend `(institutional, forceable)` :
    - `institutional` — verrous JAMAIS contournables via `force` (PAC, SAE,
      fin de semestre, événement du planning officiel).
    - `forceable` — ordre pédagogique + indisponibilité enseignant
      déclarée : signalés systématiquement, mais `force=True` les lève.
    """
    extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
    institutional = _institutional_violations(
        week, day, slot, extra_blocked,
        _libelle_jour_ferme(state, session.semestre, week, day),
    )
    forceable = _pedagogical_order_violations(week, day, slot, extra_blocked_pedago, allowed_weeks)
    forceable += _teacher_availability_violations(state, session, week, day, slot)
    return institutional, forceable


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


@app.post("/placements/{session_id}/validate", response_model=ValidationResponse, dependencies=[Depends(accounts.require_role("edit"))])
def validate_placement(session_id: str, body: MoveSessionRequest) -> ValidationResponse:
    state = get_state()
    match = _find_placement(state, session_id)
    session = state.sessions_by_id.get(session_id)
    # RENDU, jamais levé : cet endpoint est un dry-run (cf.
    # `_semaines_non_modifiables`). Un 409 ici casse le glisser-déposer au
    # lieu de proposer le forçage.
    verrou_semaine = _semaines_non_modifiables(state, session_id, match.week, body.week, force=body.force)

    # Règles institutionnelles/pédagogiques : contrôlées ICI, sur le
    # déplacement réellement demandé — pas seulement utilisées pour filtrer
    # les suggestions (retour utilisateur : "vérifie bien toutes les
    # contraintes avant que ça s'effectue"). Jamais contournables.
    if session and _is_duo_synced(session, state.teacher_duos):
        return ValidationResponse(valid=False, hard_conflicts=verrou_semaine + [_DUO_SYNC_NOTE], soft_warnings=[], blocking_conflicts=[], suggestions=[], suggestions_note=_DUO_SYNC_NOTE)

    institutional: list[str] = []
    pedago: list[str] = []
    if session:
        # Toujours calculer les deux familles, puis les ressources : l'UI doit
        # afficher TOUTES les contraintes d'un coup (brief 03/09/2026), pas
        # seulement le premier verrou institutionnel.
        institutional, pedago = _conflits_deplacement(state, session, body.week, body.day, body.slot)

    # Même résolution de salle que `move_session` — sinon un dry-run
    # pourrait signaler un conflit que le déplacement réel n'aurait pas
    # (puisque celui-ci recalcule la salle automatiquement).
    target_room_id = body.room_id or getattr(match, "room_id", None)
    if not body.room_id and session and target_room_id:
        resolved_room = _resolve_room(state, session, body.week, body.day, body.slot, target_room_id)
        if resolved_room is not None:
            target_room_id = resolved_room.id

    # `sessions_by_id`/`groups` OBLIGATOIRES ici, exactement comme dans
    # `move_session` : sans eux, `validate_move` ignore la DURÉE des séances
    # (un bloc de 3h n'est vu que sur son premier créneau) et la COHORTE
    # étudiante. Bug réel trouvé le 29/08/2026 : cet endroit — la
    # vérification À BLANC, celle qui prévient AVANT un glisser-déposer —
    # les avait perdus alors que le déplacement réel les passait déjà. Une
    # séance de 3h posée sur une autre était donc annoncée « valide », puis
    # refusée (ou forcée en créant un vrai conflit) au moment de l'appliquer.
    # Concrètement : deux cours du même groupe FC se sont retrouvés à 14h00,
    # et cette vérification a répondu « aucun conflit ».
    result = validate_move(
        session_id, body.week, body.day, body.slot, _as_placed(state.timetable), match.group_ids, match.teacher_codes,
        target_room_id,
        sessions_by_id=state.sessions_by_id,
        groups=state.groups,
        conflicting_room_ids=_build_conflict_map(state.rooms).get(target_room_id, set()) if target_room_id else None,
    )
    # `blocking_conflicts` DOIT rester un sous-ensemble de `hard_conflicts`
    # (cf. schemas.ValidationResponse.blocking_conflicts) : un message
    # institutionnel doit donc apparaître dans les deux, pas seulement dans
    # `blocking`. Régression du 03/09/2026 repérée par la CI le 04/09/2026 —
    # `institutional` manquait ici, si bien qu'un motif "férié"/hors
    # présence n'apparaissait plus du tout dans `hard_conflicts`.
    hard = verrou_semaine + institutional + pedago + result.hard_conflicts
    blocking = list(institutional)
    soft = list(result.soft_warnings)
    valide = not blocking and not hard
    suggestions, note = ([], None) if valide else _suggestions_for(state, session_id, match)
    return ValidationResponse(
        valid=valide,
        hard_conflicts=hard,
        soft_warnings=soft,
        blocking_conflicts=blocking,
        suggestions=suggestions,
        suggestions_note=note,
    )


@app.patch("/placements/{session_id}", dependencies=[Depends(accounts.require_role("edit"))])
def move_session(session_id: str, body: MoveSessionRequest) -> PlacementResponse:
    state = get_state()
    match = _find_placement(state, session_id)
    session = state.sessions_by_id.get(session_id)

    if session and session.locked and not body.lock:
        raise HTTPException(409, "Session is locked")

    _check_move_editable(state, session_id, match.week, body.week, force=body.force)

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
        # Institutionnel : jamais contournable, vérifié et refusé AVANT
        # tout le reste. Ordre pédagogique + indisponibilité enseignant :
        # contournables via `force` depuis le 28/08 et le 03/09/2026 (cf.
        # `_conflits_deplacement`) — calculés même si `force` est déjà vrai,
        # `forced_pending.sync_after_move` (plus bas, UNE FOIS le
        # déplacement réellement effectué) en a besoin pour savoir si CE
        # déplacement doit rester suivi.
        institutional, pedago = _conflits_deplacement(state, session, body.week, body.day, body.slot)
        if institutional:
            raise HTTPException(409, detail={
                "message": "Déplacement impossible",
                # `blocking_conflicts` est un sous-ensemble de `hard_conflicts`
                # (cf. schemas.ValidationResponse) : institutional y est donc
                # aussi, en plus des forçables listés pour que l'UI affiche
                # tout (brief 03/09/2026).
                "hard_conflicts": institutional + pedago,
                "blocking_conflicts": institutional,
                "soft_warnings": [], "suggestions": [], "suggestions_note": None,
            })
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

    _notifier("deplacement", f"{match.course_code} → {_ou(match)}")
    resultat = _to_placement(match, state.sessions_by_id)
    _apres_ecriture_planning(session_id, "update")
    return resultat


@app.patch(
    "/placements/{session_id}/seance",
    response_model=PlacementResponse,
    dependencies=[Depends(accounts.require_role("edit"))],
)
def patch_seance_maquette(session_id: str, body: PatchSeanceRequest) -> PlacementResponse:
    """Overlay enseignant / type / durée sur une séance de maquette."""
    from cal_iut.api.session_patch import appliquer_patch_seance

    resultat = appliquer_patch_seance(
        session_id,
        teacher_codes=body.teacher_codes,
        session_type=body.session_type,
        duration_slots=body.duration_slots,
        week=body.week,
        day=body.day,
        slot=body.slot,
        room_id=body.room_id,
        is_eval=body.is_eval,
        force=body.force,
    )
    _apres_ecriture_planning(session_id, "update")
    return resultat


@app.post("/placements/{session_id}/deposer", dependencies=[Depends(accounts.require_role("edit"))])
def deposer_placement(session_id: str) -> dict[str, object]:
    """Retire la séance du planning, la laisse dans le catalogue (À placer)."""
    from cal_iut.api.deposer import deposer_seance
    from cal_iut.celcat.ops import noter_placement_retire

    state = get_state()
    actuel = next((p for p in state.timetable if p.session_id == session_id), None)
    if actuel is not None:
        noter_placement_retire(actuel)
    resultat = deposer_seance(session_id)
    _apres_ecriture_planning(session_id, "delete")
    return resultat


@app.post("/placements/echanger", response_model=EchangeResponse, dependencies=[Depends(accounts.require_role("edit"))])
def echanger_placements(body: EchangeRequest) -> EchangeResponse:
    """Échange la place de deux séances, en une seule décision.

    Retour utilisateur 29/08/2026 : « si l'on fait un glisser-déposer d'un
    cours sur un autre, cela nous propose un échange de cours tout en
    vérifiant pareil ». Faire cet échange par DEUX appels à
    `PATCH /placements/{id}` serait faux : le premier déplacement pose
    forcément la séance sur une case encore occupée par l'autre, donc il
    faudrait forcer — et le forçage sauterait justement les vérifications
    qu'on veut garder. Ici les deux positions finales sont jugées ENSEMBLE,
    chacune sur la place libérée par l'autre (`ignore_session_ids`).

    Tout ou rien : si l'échange est refusé, les deux séances restent
    exactement où elles étaient. Un échange à moitié appliqué laisserait le
    planning dans un état que personne n'a demandé.
    """
    state = get_state()
    if body.session_a == body.session_b:
        raise HTTPException(400, "Une séance ne s'échange pas avec elle-même.")

    a = _find_placement(state, body.session_a)
    b = _find_placement(state, body.session_b)
    seance_a = state.sessions_by_id.get(body.session_a)
    seance_b = state.sessions_by_id.get(body.session_b)
    for identifiant, seance in ((body.session_a, seance_a), (body.session_b, seance_b)):
        if seance is not None and seance.locked:
            raise HTTPException(409, f"Séance {identifiant} verrouillée : la déverrouiller d'abord.")

    pos_a = (a.week, a.day, a.slot)
    pos_b = (b.week, b.day, b.slot)
    salle_a = getattr(a, "room_id", None)
    salle_b = getattr(b, "room_id", None)

    def _restaurer() -> None:
        a.week, a.day, a.slot = pos_a
        b.week, b.day, b.slot = pos_b

    # Positions échangées AVANT les contrôles : c'est l'état final qu'il faut
    # juger, pas un état intermédiaire qui n'existera jamais.
    a.week, a.day, a.slot = pos_b
    b.week, b.day, b.slot = pos_a
    ignorees = {body.session_a, body.session_b}
    try:
        durs, bloquants, doux = _controler_echange(state, [(a, seance_a, salle_a), (b, seance_b, salle_b)], ignorees, body.force)
    except Exception:
        _restaurer()
        raise

    if bloquants or (durs and not body.force):
        _restaurer()
        raise HTTPException(409, detail={
            "message": "Échange impossible" if bloquants else "Conflit",
            "hard_conflicts": durs,
            "blocking_conflicts": bloquants,
            "soft_warnings": doux,
            "suggestions": [],
            "suggestions_note": None,
        })

    # Salles recalculées une fois l'échange posé : `_resolve_room` lit
    # `state.timetable`, qui reflète désormais les positions finales — chaque
    # séance garde donc sa salle si elle y est encore libre, et en retrouve
    # une adaptée sinon (même règle que `move_session`).
    for placement, seance, salle_prefere in ((a, seance_a, salle_a), (b, seance_b, salle_b)):
        if seance is None or not salle_prefere:
            continue
        salle = _resolve_room(state, seance, placement.week, placement.day, placement.slot, salle_prefere)
        if salle is not None:
            placement.room_id, placement.room_label = salle.id, salle.label

    repo = get_repo() if state.current_run_id else None
    for placement, seance, ancienne in ((a, seance_a, pos_a), (b, seance_b, pos_b)):
        propose = {"week": ancienne[0], "day": ancienne[1], "slot": ancienne[2]}
        manuel = {"week": placement.week, "day": placement.day, "slot": placement.slot}
        if seance is not None:
            forced_pending.sync_after_move(placement.session_id, placement.week, placement.day, placement.slot, False)
        state.corrections.append({
            "session_id": placement.session_id, "proposed": propose,
            "manual": manuel, "locked": False, "forced": body.force,
        })
        if repo is not None:
            repo.save_correction(
                state.current_run_id, placement.session_id, propose, manuel, False, body.force,
                placement.course_code, placement.teacher_codes,
            )
            repo.update_current_placement(
                placement.session_id, placement.week, placement.day, placement.slot,
                getattr(placement, "room_id", None), getattr(placement, "room_label", None),
                seance.locked if seance else False,
                run_id=state.current_run_id, course_code=placement.course_code,
            )

    _notifier("echange", f"{a.course_code} ({_ou(a)}) ⇄ {b.course_code} ({_ou(b)})")
    _apres_ecriture_planning(body.session_a, "update")
    _apres_ecriture_planning(body.session_b, "update")
    return EchangeResponse(placements=[_to_placement(a, state.sessions_by_id), _to_placement(b, state.sessions_by_id)])


def _controler_echange(
    state: object, cibles: list, ignorees: set[str], force: bool
) -> tuple[list[str], list[str], list[str]]:
    """Tous les contrôles d'un déplacement, appliqués aux DEUX séances.

    Rend `(durs, bloquants, doux)` — `bloquants` est le sous-ensemble de
    `durs` que `force` ne lève pas (verrous institutionnels UNIQUEMENT,
    depuis le 03/09/2026 — l'indisponibilité enseignant déclarée est
    devenue contournable via `force`, comme l'ordre pédagogique), exactement
    la même distinction que `validate_placement`, pour que l'interface
    décide de la même façon des deux côtés.
    """
    durs: list[str] = []
    bloquants: list[str] = []
    doux: list[str] = []
    for placement, seance, salle in cibles:
        durs += _semaines_non_modifiables(state, placement.session_id, placement.week, placement.week, force=force)
        if seance is not None:
            institutionnels, forcable = _conflits_deplacement(
                state, seance, placement.week, placement.day, placement.slot
            )
            bloquants += institutionnels
            durs += institutionnels
            # Ordre pédagogique + indisponibilité enseignant : dans `durs`
            # (négociable via `force`), jamais dans `bloquants`.
            durs += forcable
        resultat = validate_move(
            placement.session_id, placement.week, placement.day, placement.slot,
            _as_placed(state.timetable), placement.group_ids, placement.teacher_codes, salle,
            sessions_by_id=state.sessions_by_id,
            groups=state.groups,
            conflicting_room_ids=_build_conflict_map(state.rooms).get(salle, set()) if salle else None,
            ignore_session_ids=ignorees,
        )
        durs += resultat.hard_conflicts
        doux += resultat.soft_warnings
    return durs, bloquants, doux


@app.patch("/placements/{session_id}/salle", response_model=PlacementResponse, dependencies=[Depends(accounts.require_role("edit"))])
def changer_salle(session_id: str, body: ChangeRoomRequest) -> PlacementResponse:
    """Change UNIQUEMENT la salle, à créneau inchangé — retour utilisateur
    28/08/2026 : « on va vouloir sur la vue promo modifier uniquement les
    salles ».

    Endpoint DISTINCT de `PATCH /placements/{id}` (qui sait déjà changer la
    salle au passage) parce que celui-ci refait tous les contrôles liés à la
    POSITION : ordre pédagogique, verrou PAC/SAE, synchro duo, disponibilité
    enseignant. Aucun ne peut changer de verdict quand le créneau ne bouge
    pas — mais tous peuvent REFUSER à tort une séance déjà posée à une
    position elle-même limite (typiquement une séance placée en forçant
    l'ordre pédagogique, cf. `forced_pending.py` : sa salle deviendrait
    impossible à corriger). Seul le conflit de SALLE est donc revérifié ici,
    le seul que ce changement peut réellement introduire.
    """
    state = get_state()
    match = _find_placement(state, session_id)
    session = state.sessions_by_id.get(session_id)

    # Verrou de semaine, en motifs plutôt qu'en exception. `_check_move_editable`
    # lève un 409 dont le `detail` est une simple CHAÎNE, que le frontend ne
    # sait pas relire : `detailConflit` attend la forme structurée, ne la
    # trouve pas, et le changement échouait en silence derrière un discret
    # message — retour utilisateur 31/08/2026 : « je clique sur une autre
    # salle et ça change pas, ça réaffiche la salle du début ». Le motif est
    # donc joint aux conflits de salle, dans le même format : l'utilisateur
    # voit ce qui bloque et peut confirmer.
    verrous = _semaines_non_modifiables(state, session_id, match.week, match.week, force=body.force)

    # Retrait de salle : `room_id` vide. Aucun conflit ni capacité à vérifier
    # — on n'occupe plus rien.
    if not body.room_id.strip():
        if verrous:
            raise HTTPException(409, detail={
                "message": "Semaine non modifiable",
                "hard_conflicts": verrous,
                "soft_warnings": [],
                "suggestions": [], "suggestions_note": None,
            })
        match.room_id, match.room_label = None, None
        if state.current_run_id:
            get_repo().update_current_placement(
                session_id, match.week, match.day, match.slot, None, None,
                session.locked if session else False,
                run_id=state.current_run_id, course_code=match.course_code,
            )
        resultat = _to_placement(match, state.sessions_by_id)
        _apres_ecriture_planning(session_id, "update")
        return resultat

    salle = next((r for r in state.rooms if r.id == body.room_id), None)
    if salle is None:
        raise HTTPException(404, f"Salle {body.room_id} inconnue")

    # Occupation de la salle calculée DIRECTEMENT plutôt qu'en filtrant les
    # messages de `validate_move` : celui-ci juge la position ENTIÈRE
    # (groupe/enseignant/salle), or à créneau inchangé les conflits groupe/
    # enseignant sont ceux qui existent DÉJÀ, indépendants de la salle
    # demandée — les laisser bloquer ferait échouer un simple changement de
    # salle pour une raison sans rapport. Trier ses messages par
    # sous-chaîne (« salle ») marcherait aujourd'hui mais casserait
    # silencieusement à la première reformulation du texte français.
    #
    # Salles combinées incluses (`_build_conflict_map`) : réserver H.007-008
    # doit voir H.007 et H.008 comme occupées, et réciproquement.
    conflits_ids = {salle.id} | _build_conflict_map(state.rooms).get(salle.id, set())
    duree = max(1, getattr(session, "duration_slots", 1) or 1) if session else 1
    creneaux_vises = {match.slot + k for k in range(duree)}
    occupants = []
    for p in state.timetable:
        if p.session_id == session_id or p.week != match.week or p.day != match.day:
            continue
        if getattr(p, "room_id", None) not in conflits_ids:
            continue
        autre = state.sessions_by_id.get(p.session_id)
        duree_autre = max(1, getattr(autre, "duration_slots", 1) or 1) if autre else 1
        if creneaux_vises & {p.slot + k for k in range(duree_autre)}:
            occupants.append(p.course_code)
    # Capacité : AVERTISSEMENT, jamais un refus sec — mettre 30 étudiants
    # dans une salle de 15 est presque toujours une erreur, mais pas
    # toujours (groupe partiellement absent, TP dédoublé...). Il faut donc
    # le dire clairement et laisser trancher, pas décider à la place de
    # l'utilisateur. Sans ça, changer une salle pour une trop petite passait
    # en silence — retour utilisateur 28/08/2026 : « il faut mettre un
    # warning quand l'on change de salle s'il y a un conflit ». Même calcul
    # d'effectif que le solveur (`rooms.py::_headcount_for_groups`), pour
    # que l'avertissement dise la même chose que l'affectation automatique.
    from cal_iut.solver.rooms import _headcount_for_groups

    avertissements: list[str] = []
    effectif = _headcount_for_groups(list(match.group_ids or []), state.groups)
    if salle.capacity < effectif:
        avertissements.append(
            f"Capacité insuffisante : {salle.label} a {salle.capacity} place(s) "
            f"pour un effectif de {effectif}."
        )

    if (occupants or avertissements or verrous) and not body.force:
        conflits = verrous + (
            [f"Conflit salle : {', '.join(sorted(set(occupants)))} occupe(nt) déjà {salle.label} à ce créneau."]
            if occupants else []
        )
        raise HTTPException(409, detail={
            "message": "Conflit",
            "hard_conflicts": conflits,
            "soft_warnings": avertissements,
            "suggestions": [], "suggestions_note": None,
        })

    match.room_id, match.room_label = salle.id, salle.label

    if state.current_run_id:
        persiste = get_repo().update_current_placement(
            session_id, match.week, match.day, match.slot,
            salle.id, salle.label,
            session.locked if session else False,
            run_id=state.current_run_id, course_code=match.course_code,
        )
        if not persiste:
            raise HTTPException(500, detail={
                "message": "Changement de salle non enregistré : aucun run en base.",
                "quoi_faire": "Relancer une génération avant de modifier le planning.",
            })

    if not getattr(match, "room_id", None):
        _notifier("sans_salle", f"{match.course_code} ({_ou(match)}) n'a plus de salle")
    resultat = _to_placement(match, state.sessions_by_id)
    _apres_ecriture_planning(session_id, "update")
    return resultat


@app.post("/rooms", response_model=RoomMeta, dependencies=[Depends(accounts.require_role("admin"))])
def creer_salle(body: CreateRoomRequest) -> RoomMeta:
    """Ajoute une salle hors bâtiment — retour utilisateur 28/08/2026 :
    « il se peut que l'on utilise des salles autres que dans le bâtiment,
    il faut donc laisser la possibilité de créer une salle ».

    Persistée dans le volume (`api/custom_rooms.py`), pas dans
    `data/config/rooms.yaml` qui est réécrit à chaque déploiement. Type
    `standard` imposé : ces salles ne portent aucune règle d'affectation,
    le solveur ne les choisira jamais seul — elles servent au choix MANUEL
    de salle (Vue Promo). Voulu : une salle exceptionnelle ne doit pas
    devenir une ressource que la génération automatique se met à utiliser.
    """
    from cal_iut.models.entities import Room, RoomType

    state = get_state()
    libelle = body.label.strip()
    if not libelle:
        raise HTTPException(400, "Le nom de la salle ne peut pas être vide.")

    # Identifiant dérivé du libellé : « Amphi Descartes » -> « amphi-descartes ».
    base = "".join(c.lower() if c.isalnum() else "-" for c in libelle).strip("-")
    base = "-".join(filter(None, base.split("-"))) or "salle"
    room_id = base
    n = 2
    existants = {r.id for r in state.rooms}
    while room_id in existants:
        room_id = f"{base}-{n}"
        n += 1

    if any(r.label.strip().lower() == libelle.lower() for r in state.rooms):
        raise HTTPException(409, f"Une salle nommée « {libelle} » existe déjà.")

    salle = Room(id=room_id, label=libelle, capacity=body.capacity, room_type=RoomType.STANDARD)
    custom_rooms.add_custom_room(salle)
    state.rooms = state.rooms + [salle]
    return RoomMeta(id=salle.id, label=salle.label, capacity=salle.capacity, room_type=salle.room_type.value)


def _apres_ecriture_planning(session_id: str, action: str) -> None:
    """File d'attente Celcat après un write planning. N'échoue jamais."""
    try:
        from cal_iut.celcat.ops import apres_ecriture_planning

        apres_ecriture_planning(session_id, action)
    except Exception:
        return


def _celcat_etat_public() -> CelcatEtatResponse:
    from cal_iut.celcat.etat import charger, semaines_celcat_passees
    from cal_iut.celcat.logs import tous

    doc = charger()
    compteurs = CelcatCompteurs()
    derniere_ecriture: str | None = None
    for item in tous():
        kind = item.get("kind")
        if kind == "created":
            compteurs.created += 1
        elif kind == "modified":
            compteurs.modified += 1
        elif kind == "deleted":
            compteurs.deleted += 1
        elif kind == "blocked":
            compteurs.blocked += 1
        # « created »/« modified »/« deleted » sont les SEULS kinds qui
        # correspondent à une écriture Celcat réellement réussie — « blocked »
        # n'a rien changé côté Celcat. Le journal est ajouté en ordre
        # chronologique (`celcat/logs.py::append`) : le dernier de ces trois
        # kinds rencontré en parcourant `tous()` est donc le plus récent.
        if kind in ("created", "modified", "deleted"):
            derniere_ecriture = item.get("at") or derniere_ecriture
    dernier = doc.get("dernier_job")
    return CelcatEtatResponse(
        saisie_active=bool(doc.get("saisie_active")),
        semaines_validees=list(doc.get("semaines_validees") or []),
        semaines_passees=semaines_celcat_passees(),
        semaines_lancees=list(doc.get("semaines_lancees") or []),
        semaines_completes=_semaines_celcat_completes(),
        valide_le=doc.get("valide_le"),
        dernier_job=dernier if isinstance(dernier, dict) else None,
        derniere_ecriture_celcat=derniere_ecriture,
        compteurs=compteurs,
        worker_ok=True,
    )


def _semaines_celcat_completes() -> list[int]:
    """Chips 1..30 (S1, cf. `celcat.etat.NB_SEMAINES_LOT`) dont plus aucune
    séance manquante ne pourrait encore atterrir — réutilise
    `_sessions_manquantes` (même filtre SAE, mêmes bornes d'ordre
    pédagogique que `/placements/manquantes`) plutôt qu'un nouveau calcul :
    une semaine « complète » l'est au même sens que « rien à placer »."""
    from cal_iut.celcat.etat import NB_SEMAINES_LOT

    state = get_state()
    semaines_visees: set[int] = set()
    for _session, semaines_ok, _provisoire, _actuel in _sessions_manquantes(state):
        semaines_visees |= semaines_ok
    return [n for n in range(1, NB_SEMAINES_LOT + 1) if (n - 1) not in semaines_visees]


def _entrees_celcat(state) -> list:
    """Traduit TOUT le planning courant en entrées Celcat (cf.
    `celcat/mapping.py`). Pure lecture : ne touche ni à Celcat, ni au
    journal de synchronisation."""
    from cal_iut.celcat.mapping import entree_pour_placement, load_celcat_config

    cfg = load_celcat_config(state.config_dir)
    libelle_groupe = {g.id: g.label for g in state.groups}
    entrees = []
    for p in state.timetable:
        session = state.sessions_by_id.get(p.session_id)
        semestre = getattr(session, "semestre", "") or ""
        entrees.append(entree_pour_placement(
            cfg,
            session_id=p.session_id,
            course_code=p.course_code,
            session_type=str(getattr(getattr(session, "session_type", None), "value", "")) if session else "",
            week=p.week, day=p.day, slot=p.slot,
            duration_slots=max(1, getattr(session, "duration_slots", 1) or 1) if session else 1,
            teacher_codes=list(p.teacher_codes or []),
            room_id=getattr(p, "room_id", None),
            groupe=", ".join(libelle_groupe.get(g, g) for g in (p.group_ids or [])),
            semestre=semestre,
            # Le LUNDI civil, pas l'index solveur : le sélecteur de semaines de
            # Celcat s'identifie par ses dates. `_date_iso` applique déjà le
            # décalage de semestre, que `p.week` seul n'intègre pas.
            lundi=_date_iso(state, semestre, p.week, 0) if semestre else "",
        ))
    return entrees


@app.get("/celcat/plan", response_model=CelcatPlanResponse, dependencies=[Depends(accounts.require_role("admin"))])
def celcat_plan(semaines: str = "", limite: int = 200) -> CelcatPlanResponse:
    """Ce qui serait saisi dans Celcat, sans rien y envoyer.

    `semaines` : indices solveur séparés par des virgules (ex. « 2,3,4 »).
    Vide = toutes les semaines du planning — utile pour voir l'état général,
    mais on saisit en pratique par lots (retour utilisateur : « ajuster le
    nombre de semaines que l'on met »).

    Réservé à la session admin : lance rien, mais expose le planning complet
    et l'état de la saisie, qui n'ont rien à faire derrière un lien public.
    """
    from cal_iut.celcat.driver import PilotePlaywright
    from cal_iut.celcat.formulaire import charger_carte
    from cal_iut.celcat.sync import construire_plan

    state = get_state()
    entrees = _entrees_celcat(state)
    if semaines.strip():
        try:
            voulues = {int(x) for x in semaines.split(",") if x.strip()}
        except ValueError:
            raise HTTPException(400, "Paramètre `semaines` invalide : indices séparés par des virgules.") from None
    else:
        voulues = {e.semaine for e in entrees}

    plan = construire_plan(entrees, voulues)

    motifs: dict[str, int] = {}
    for e in plan.bloquees:
        for b in e.bloquants:
            # Motif générique (sans le nom de la séance) : ce qu'on veut
            # montrer c'est « 95 CM sans code », pas 95 lignes distinctes.
            motifs[b] = motifs.get(b, 0) + 1

    action_par_id = {}
    for e in plan.a_creer:
        action_par_id[e.session_id] = "creer"
    for e in plan.a_modifier:
        action_par_id[e.session_id] = "modifier"
    for e in plan.inchangees:
        action_par_id[e.session_id] = "inchangee"
    for e in plan.bloquees:
        action_par_id[e.session_id] = "bloquee"

    # Les bloquées d'abord : c'est ce sur quoi il y a à agir.
    ordre = {"bloquee": 0, "creer": 1, "modifier": 2, "inchangee": 3}
    toutes = plan.bloquees + plan.a_creer + plan.a_modifier + plan.inchangees
    toutes.sort(key=lambda e: (ordre[action_par_id[e.session_id]], e.semaine, e.jour, e.heure_debut))

    pret, message = PilotePlaywright.disponible()
    carte = charger_carte(state.config_dir)
    return CelcatPlanResponse(
        formulaire_releve=carte.confirmee,
        formulaire_manques=carte.manques(),
        semaines=sorted(voulues),
        a_creer=len(plan.a_creer), a_modifier=len(plan.a_modifier),
        a_supprimer=len(plan.a_supprimer), inchangees=len(plan.inchangees),
        bloquees=len(plan.bloquees),
        resume=plan.resume(),
        motifs_blocage=dict(sorted(motifs.items(), key=lambda kv: -kv[1])),
        entrees=[
            CelcatEntreeResponse(
                session_id=e.session_id, course_code=e.course_code, semaine=e.semaine,
                jour=e.jour, heure_debut=e.heure_debut, heure_fin=e.heure_fin,
                salle=e.salle, groupe=e.groupe,
                action=action_par_id[e.session_id], bloquants=e.bloquants,
            )
            for e in toutes[:max(0, limite)]
        ],
        pilote_pret=pret, pilote_message=message,
    )


@app.post("/celcat/saisie", response_model=CelcatSaisieResponse,
          dependencies=[Depends(accounts.require_role("admin"))])
def celcat_saisie(body: CelcatSaisieRequest) -> CelcatSaisieResponse:
    """Lance la saisie des semaines demandées. SIMULATION par défaut.

    Trois refus AVANT d'ouvrir quoi que ce soit, parce qu'échouer à la
    trentième séance laisse un Celcat à moitié rempli :

    1. une séance non saisissable dans le lot -> rien ne part ;
    2. Celcat injoignable (VPN) -> rien ne part ;
    3. formulaire de création non relevé -> rien ne part, et le message dit
       lesquels des libellés manquent.

    Le journal de synchronisation n'est alimenté qu'en saisie RÉELLE : une
    répétition qui marquerait les séances « déjà saisies » les ferait
    disparaître du prochain plan sans qu'elles existent dans Celcat.
    """
    import os

    from cal_iut.celcat.etat import charger as charger_celcat

    # Forme du paramètre validée AVANT l'interrupteur `saisie_active` : une
    # erreur de saisie (400, business) doit rester visible même verrou
    # désactivé — sinon un admin qui teste un paramètre voit toujours 409
    # "désactivée" sans jamais apprendre que sa valeur est invalide.
    try:
        voulues = {int(x) for x in body.semaines.split(",") if x.strip()}
    except ValueError:
        raise HTTPException(400, "Paramètre `semaines` invalide : indices séparés par des virgules.") from None
    if not voulues:
        raise HTTPException(400, "Aucune semaine demandée.")

    if not charger_celcat().get("saisie_active"):
        raise HTTPException(409, "Saisie Celcat désactivée")

    from cal_iut.celcat import navigateur as nav
    from cal_iut.celcat import reseau, sync
    from cal_iut.celcat.driver import PiloteSimule, PilotePlaywright, Rythme, SaisieCelcat
    from cal_iut.celcat.formulaire import charger_carte

    state = get_state()
    plan = sync.construire_plan(_entrees_celcat(state), voulues)
    if plan.bloquees and not body.ignorer_bloquees:
        raise HTTPException(409, plan.resume())
    if plan.total_actions == 0:
        return CelcatSaisieResponse(simulee=body.simuler, resume="Rien à saisir : tout est à jour.")

    rythme = Rythme()
    if body.simuler:
        pilote = PiloteSimule()
        base = "(simulation)"
        journaliser = None
    else:
        pret, message = PilotePlaywright.disponible()
        if not pret:
            raise HTTPException(503, message)
        carte = charger_carte(state.config_dir)
        if not carte.confirmee:
            raise HTTPException(
                409,
                "Le formulaire de création Celcat n'a pas été relevé ("
                + ", ".join(carte.manques())
                + "). Voir data/config/celcat_formulaire.yaml. Rien n'a été envoyé.",
            )
        identifiant = os.environ.get("CELCAT_UTILISATEUR", "")
        motdepasse = os.environ.get("CELCAT_MOT_DE_PASSE", "")
        if not identifiant or not motdepasse:
            raise HTTPException(
                503, "CELCAT_UTILISATEUR / CELCAT_MOT_DE_PASSE absents de l'environnement (.env)."
            )
        try:
            reseau.exiger_acces(PilotePlaywright.URL_CONNEXION, monter_le_vpn=body.monter_le_vpn)
        except reseau.AccesIndisponible as exc:
            raise HTTPException(503, str(exc)) from None
        base = nav.BASE_PRODUCTION if body.production else nav.BASE_ENTRAINEMENT
        pilote = PilotePlaywright(rythme, base=base, carte=carte, config_dir=state.config_dir)
        journaliser = sync.marquer_saisi

    saisie = SaisieCelcat(
        pilote, rythme, journaliser=journaliser,
        verifier_acces=None if body.simuler else (
            lambda: bool(reseau.verifier(PilotePlaywright.URL_CONNEXION))
        ),
    )
    identifiants = ("(simulation)", "") if body.simuler else (identifiant, motdepasse)
    resultat = saisie.executer(
        plan, *identifiants, ignorer_bloquees=body.ignorer_bloquees,
    )

    return CelcatSaisieResponse(
        simulee=body.simuler, base=base,
        creees=resultat.creees, modifiees=resultat.modifiees, supprimees=resultat.supprimees,
        echecs=resultat.echecs, interrompu=resultat.interrompu,
        acces_perdu=resultat.acces_perdu, resume=resultat.resume(),
        actions=list(getattr(pilote, "actions", [])),
    )


@app.get("/celcat/etat", response_model=CelcatEtatResponse, dependencies=[Depends(accounts.require_role("admin"))])
def celcat_etat() -> CelcatEtatResponse:
    return _celcat_etat_public()


@app.patch("/celcat/saisie", response_model=CelcatEtatResponse, dependencies=[Depends(accounts.require_role("admin"))])
def celcat_saisie_active(body: CelcatSaisieActiveRequest) -> CelcatEtatResponse:
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    doc["saisie_active"] = body.active
    sauver(doc)
    if not body.active:
        from cal_iut.celcat.file_attente import vider

        vider()
    return _celcat_etat_public()


@app.post("/celcat/valider", response_model=CelcatEtatResponse, dependencies=[Depends(accounts.require_role("admin"))])
def celcat_valider(body: CelcatValiderRequest) -> CelcatEtatResponse:
    from datetime import datetime, timezone

    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    doc["semaines_validees"] = [int(s) for s in body.semaines]
    doc["valide_le"] = datetime.now(timezone.utc).isoformat()
    sauver(doc)
    return _celcat_etat_public()


@app.post("/celcat/lancer-nuit", response_model=CelcatEtatResponse, dependencies=[Depends(accounts.require_role("admin"))])
def celcat_lancer_nuit() -> CelcatEtatResponse:
    from cal_iut.celcat.etat import charger
    from cal_iut.celcat.nuit import executer_job_nuit

    if not charger().get("saisie_active"):
        raise HTTPException(409, "Saisie Celcat désactivée")
    executer_job_nuit()
    return _celcat_etat_public()


@app.get("/celcat/logs", dependencies=[Depends(accounts.require_role("admin"))])
def celcat_logs(limit: int = 50, cursor: str | None = None) -> dict[str, object]:
    from cal_iut.celcat.logs import paginer

    items, suivant = paginer(limit, cursor)
    return {"items": items, "cursor": suivant}


@app.get("/celcat/extras", dependencies=[Depends(accounts.require_role("admin"))])
def celcat_extras(statut: str | None = None) -> dict[str, object]:
    from cal_iut.celcat.extras import lister

    return {"extras": lister(statut)}


@app.post("/celcat/extras/{extra_id}/ignorer", dependencies=[Depends(accounts.require_role("admin"))])
def celcat_extra_ignorer(extra_id: str) -> dict[str, str]:
    from cal_iut.celcat.etat import charger, sauver
    from cal_iut.celcat.extras import enregistrer, trouver

    extra = trouver(extra_id)
    if extra is None:
        extra = {"id": extra_id}
    extra["statut"] = "ignore"
    enregistrer(extra)
    doc = charger()
    ignores = dict(doc.get("ignores") or {})
    ignores[extra_id] = True
    if extra.get("event_id") is not None:
        ignores[str(extra["event_id"])] = True
    doc["ignores"] = ignores
    sauver(doc)
    return {"statut": "ignore"}


@app.post(
    "/celcat/extras/{extra_id}/ajouter",
    response_model=CelcatExtraActionResponse,
    dependencies=[Depends(accounts.require_role("admin"))],
)
def celcat_extra_ajouter(extra_id: str) -> CelcatExtraActionResponse:
    from cal_iut.celcat.extras import enregistrer, trouver
    from cal_iut.celcat.mapping import SLOT_TIMES, load_celcat_config

    extra = trouver(extra_id)
    if extra is None:
        raise HTTPException(404, f"Extra {extra_id} introuvable")

    state = get_state()
    code = str(extra.get("course_code") or "").strip()
    cfg = load_celcat_config(state.config_dir)
    if not cfg.modules.get(code.upper()):
        raise HTTPException(409, f"{code} sans code Celcat")

    manques: list[str] = []
    jour_brut = extra.get("jour")
    try:
        jour = int(jour_brut) if jour_brut is not None else None
    except (TypeError, ValueError):
        jour = None
    if jour is None:
        manques.append("jour")
    heure = str(extra.get("heure_debut") or "").strip()
    if not heure:
        manques.append("heure_debut")
    try:
        week = int(extra["semaine"]) if extra.get("semaine") is not None else None
    except (TypeError, ValueError):
        week = None
    if week is None:
        manques.append("semaine")
    group_ids = extra.get("group_ids")
    if not isinstance(group_ids, list) or not group_ids:
        manques.append("group_ids")
    teacher_codes = extra.get("teacher_codes")
    if not isinstance(teacher_codes, list) or not teacher_codes:
        manques.append("teacher_codes")
    if manques:
        raise HTTPException(
            409,
            f"Extra {extra_id} incomplet ({', '.join(manques)}) — rien n'a été inventé.",
        )

    day = jour - 1 if jour >= 1 else 0
    day = max(0, min(4, day))
    slot = 0
    for i, (debut, _fin) in enumerate(SLOT_TIMES):
        if debut == heure:
            slot = i
            break
    session_type = str(extra.get("session_type") or "TD")

    placement = creer_seance_personnalisee(
        CreerSeanceRequest(
            course_code=code,
            session_type=session_type,
            group_ids=[str(g) for g in group_ids],
            teacher_codes=[str(t) for t in teacher_codes],
            week=week,
            day=day,
            slot=slot,
            force=False,
        )
    )
    extra["statut"] = "ajoute"
    extra["session_id"] = placement.session_id
    enregistrer(extra)
    return CelcatExtraActionResponse(statut="ajoute", session_id=placement.session_id)


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


def _sessions_manquantes(state: object) -> list[tuple[object, set[int], bool, object | None]]:
    """`[(session, semaines_possibles, placée_provisoirement, placement_actuel)]`
    pour toute séance absente du planning (ou placée en forçant l'ordre
    pédagogique, pas encore validée) — le CŒUR de `/placements/manquantes`,
    extrait ici pour être réutilisé par `_celcat_etat_public` (semaines
    complètes) sans dupliquer le filtre SAE/le calcul de bornes.

    Exclut les SAE (WS*) jamais placées par le solveur (`is_unplaced_sae`) :
    retour utilisateur 04/09/2026, verbatim « toutes les séance de sae ws se
    retrouve dans a placer, il faut les retirer » — inverse le choix du
    03/09/2026 (`test_should_list_unplaced_ws_sae_in_manquantes`, qui les
    voulait ICI justement) : les lister dans « À placer » les rendait certes
    manuellement plaçables, mais noyait la liste sous des dizaines d'entrées
    SAE qui ne sont d'ailleurs pas vraiment « manquantes » au même sens
    qu'une TD/CM classique. `POST /placements/personnalisees` (« + Nouvelle
    séance ») reste le chemin dédié pour en créer une — même filet
    `is_unplaced_sae` côté SAE-day-block (`_hard_constraint_context`), donc
    toujours plaçable sur son propre jour de SAE, juste plus via cette
    liste-ci."""
    places = {p.session_id for p in state.timetable}
    placement_by_id = {p.session_id: p for p in state.timetable}
    en_attente = forced_pending.all_pending()

    from cal_iut.solver.decomposed import _build_sequence_neighbors, _movable_bounds

    voisins = _build_sequence_neighbors(state.sessions, state.groups)
    semaine_par_seance = {p.session_id: p.week for p in state.timetable}
    n_semaines = max((p.week for p in state.timetable), default=-1) + 1

    resultat: list[tuple[object, set[int], bool, object | None]] = []
    for session in state.sessions:
        if getattr(session, "is_unplaced_sae", False):
            continue
        provisoire = session.id in en_attente
        if session.id in places and not provisoire:
            continue
        lo, hi = _movable_bounds(session.id, voisins, semaine_par_seance, n_semaines)
        semaines_ok = set(range(lo, hi + 1))
        actuel = placement_by_id.get(session.id) if provisoire else None
        resultat.append((session, semaines_ok, provisoire, actuel))
    return resultat


@app.get("/placements/manquantes", response_model=SeancesAPlacerResponse)
def seances_manquantes() -> SeancesAPlacerResponse:
    """Inventaire des séances absentes du planning.

    Calculé par DIFFÉRENCE — séances à placer moins séances placées — plutôt
    que lu dans un champ du solveur : l'inventaire reste ainsi juste même si
    une séance disparaît par un autre chemin (reprise d'un run partiel,
    régénération de semaine interrompue, correction manuelle).
    """
    state = get_state()
    noms = _noms_enseignants(state)
    libelle_groupe = {g.id: g.label for g in state.groups}

    # Les bornes d'ordre pédagogique sont calculées ICI, une fois pour toutes
    # (`_sessions_manquantes`), au lieu de passer par `_hard_constraint_context`
    # séance par séance : celui-ci relit le planning officiel sur disque et
    # reparcourt les 3101 séances à chaque appel. Mesuré sur un run très
    # incomplet (795 séances manquantes) : 13,6 s pour dresser l'inventaire,
    # contre une fraction de seconde ici. Le résultat est identique —
    # `allowed_weeks` n'y vient que de `_movable_bounds`. Exclut aussi les SAE
    # non planifiées par le solveur (préfixe "WS", sauf `solver_scheduled_sae`,
    # ex. WSA501D) — même filtre que l'audit (`resultat.seances_non_placees`)
    # et `scripts/solve_until_ok.py::score_run`. Bug réel trouvé le 27/08/2026
    # (retour utilisateur : « j'ai 1121 à placer pas 426 ») : cet inventaire —
    # l'onglet « À placer » réel de l'appli — comptait encore les 695 séances
    # SAE dont la semaine vient du calendrier réel, jamais du solveur, jamais
    # censées être placées à la main.
    n_semaines = max((p.week for p in state.timetable), default=-1) + 1

    manquantes: list[SeanceAPlacerResponse] = []
    par_parcours: dict[str, int] = {}
    for session, semaines_ok, provisoire, actuel in _sessions_manquantes(state):
        par_parcours[session.parcours] = par_parcours.get(session.parcours, 0) + 1
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
        total_placees=len(state.timetable),
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


@app.post("/placements/{session_id}/placer", response_model=PlacementResponse, dependencies=[Depends(accounts.require_role("edit"))])
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

    # Même verrou que le déplacement, et même contournement par `force`
    # (cf. `_check_move_editable`) : poser une séance manquante dans la
    # semaine en cours doit rester possible quand on corrige à chaud.
    statut = week_status(state.calendar, session.semestre, body.week)
    if statut != "future" and not body.force:
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

    # Institutionnel : jamais contournable. Ordre pédagogique + indisponibilité
    # enseignant : contournables via `force` depuis le 28/08 et le 03/09/2026
    # (cf. `_conflits_deplacement`) — calculés même si `force` est déjà vrai,
    # `forced_pending.sync_after_move` (plus bas, UNE FOIS le placement
    # réellement effectué) en a besoin pour savoir si CE placement doit
    # rester suivi.
    institutional, pedago = _conflits_deplacement(state, session, body.week, body.day, body.slot)
    if institutional:
        raise HTTPException(409, detail={
            "message": "Placement impossible",
            # `blocking_conflicts` est un sous-ensemble de `hard_conflicts`
            # (cf. schemas.ValidationResponse) : institutional y est donc
            # aussi.
            "hard_conflicts": institutional + pedago,
            # Non contournables, meme avec `force` : l'interface ne doit donc
            # pas proposer « Forcer » ici (cf. `ValidationResponse.
            # blocking_conflicts`, meme distinction).
            "blocking_conflicts": institutional,
            "soft_warnings": [], "suggestions": [], "suggestions_note": None,
        })
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

    _notifier("placement", f"{place.course_code} posée {_ou(place)}")
    resultat = _to_placement(place, state.sessions_by_id)
    _apres_ecriture_planning(session_id, "create")
    return resultat


def _reference_cours(state: object, course_code: str, group_ids: list[str]) -> object:
    """Retrouve une matière déjà connue par son code — jamais n'en invente
    une. `group_ids` sert à choisir le bon `parcours` quand un même code
    couvre plusieurs parcours (rare, mais `Course` est fusionnée par
    parcours) : on prend celui du premier groupe demandé."""
    code = course_code.strip().upper()
    candidats = [c for c in state.courses if c.code.upper() == code]
    if not candidats:
        raise HTTPException(
            404,
            f"Aucune matière « {code} » connue — impossible d'y ajouter une séance "
            "(ce système ajoute une séance à une matière existante, il n'en crée pas).",
        )
    if len(candidats) == 1:
        return candidats[0]
    parcours_du_groupe = next(
        (g.parcours for g in state.groups if g.id == (group_ids[0] if group_ids else None)), None
    )
    return next((c for c in candidats if c.parcours == parcours_du_groupe), candidats[0])


def _id_seance_personnalisee(course_code: str, semestre: str, session_type: str, group_ids: list[str]) -> str:
    """Identifiant lisible et JAMAIS confondu avec une séance de maquette —
    `CUSTOM<n>` là où la maquette écrit un numéro de séquence nu
    (`WRA508C-S5-TD-11-...`) : les heuristiques d'ordre pédagogique qui
    lisent `-TD-(\\d+)-` ailleurs dans le code ne doivent jamais confondre
    une séance ajoutée à la main avec la Nième séance d'une progression
    qu'elle ne suit pas."""
    suffixe = "-".join(sorted(group_ids))
    base = f"{course_code}-{semestre}-{session_type}-CUSTOM"
    n = 1
    state = get_state()
    existants = set(state.sessions_by_id)
    while f"{base}{n}-{suffixe}" in existants:
        n += 1
    return f"{base}{n}-{suffixe}"


@app.post("/placements/personnalisees", response_model=PlacementResponse, dependencies=[Depends(accounts.require_role("edit"))])
def creer_seance_personnalisee(body: CreerSeanceRequest) -> PlacementResponse:
    """Ajoute une séance à une matière existante et la place — retour
    utilisateur 31/08/2026 (cf. `CreerSeanceRequest`). Délègue entièrement
    à `placer_seance` pour le placement : mêmes contrôles institutionnels,
    même ordre pédagogique, même résolution de salle, même persistance —
    aucune règle dupliquée. Persiste la MÉTADONNÉE de la séance
    (`api/custom_sessions.py`) seulement après un placement réussi : une
    séance dont le placement échoue ne doit laisser AUCUNE trace, ni en
    mémoire ni sur disque.
    """
    state = get_state()
    try:
        type_seance = SessionType(body.session_type.strip().upper())
    except ValueError:
        raise HTTPException(400, f"Type de séance inconnu : {body.session_type!r} (CM, TD, TP ou PTUT).") from None

    inconnus = [g for g in body.group_ids if g not in {gr.id for gr in state.groups}]
    if inconnus:
        raise HTTPException(400, f"Groupe(s) inconnu(s) : {', '.join(inconnus)}")

    reference = _reference_cours(state, body.course_code, body.group_ids)
    session_id = _id_seance_personnalisee(reference.code, reference.semestre, type_seance.value, body.group_ids)

    seance = SessionToPlace(
        id=session_id,
        course_code=reference.code,
        course_name=reference.name,
        semestre=reference.semestre,
        parcours=reference.parcours,
        annee=reference.annee,
        session_type=type_seance,
        group_ids=list(body.group_ids),
        teacher_codes=[t.strip().upper() for t in body.teacher_codes if t.strip()],
        duration_slots=body.duration_slots,
        is_eval=body.is_eval,
        metadata={"custom_session": True, "note": (body.note or "").strip()},
    )
    state.sessions.append(seance)
    state.sessions_by_id[session_id] = seance

    try:
        resultat = placer_seance(
            session_id,
            MoveSessionRequest(
                week=body.week, day=body.day, slot=body.slot,
                room_id=body.room_id, lock=False, force=body.force,
            ),
        )
    except HTTPException:
        # Rien ne doit rester d'une séance dont le placement échoue — ni en
        # mémoire, ni a fortiori sur disque (jamais tenté à ce stade).
        state.sessions.remove(seance)
        del state.sessions_by_id[session_id]
        raise

    custom_sessions.add_custom_session(seance)
    return resultat


@app.patch("/placements/personnalisees/{session_id}", response_model=PlacementResponse, dependencies=[Depends(accounts.require_role("edit"))])
def modifier_seance_personnalisee(session_id: str, body: ModifierSeancePersonnaliseeRequest) -> PlacementResponse:
    """Modifie une séance créée par ce système — jamais une séance de la
    maquette (rejeté avec un message explicite : `seances_annulees.yaml` +
    `sae_corrections.yaml` sont les outils prévus pour celles-là, une
    correction s'y annonce plutôt que de disparaître en silence)."""
    state = get_state()
    seance = state.sessions_by_id.get(session_id)
    if seance is None or not seance.metadata.get("custom_session"):
        raise HTTPException(
            404,
            f"Aucune séance personnalisée « {session_id} » — seules les séances créées "
            "par ce système peuvent être modifiées ici.",
        )

    if body.session_type is not None:
        try:
            seance.session_type = SessionType(body.session_type.strip().upper())
        except ValueError:
            raise HTTPException(400, f"Type de séance inconnu : {body.session_type!r}.") from None
    if body.group_ids is not None:
        inconnus = [g for g in body.group_ids if g not in {gr.id for gr in state.groups}]
        if inconnus:
            raise HTTPException(400, f"Groupe(s) inconnu(s) : {', '.join(inconnus)}")
        seance.group_ids = list(body.group_ids)
    if body.teacher_codes is not None:
        seance.teacher_codes = [t.strip().upper() for t in body.teacher_codes if t.strip()]
    if body.duration_slots is not None:
        seance.duration_slots = body.duration_slots
    if body.is_eval is not None:
        seance.is_eval = body.is_eval
    if body.note is not None:
        seance.metadata["note"] = body.note.strip()

    repositionne = body.week is not None and body.day is not None and body.slot is not None
    if repositionne:
        resultat = move_session(
            session_id,
            MoveSessionRequest(
                week=body.week, day=body.day, slot=body.slot,
                room_id=body.room_id, lock=False, force=body.force,
            ),
        )
    else:
        match = _find_placement(state, session_id)
        resultat = _to_placement(match, state.sessions_by_id)

    custom_sessions.update_custom_session(seance)
    return resultat


@app.delete("/placements/personnalisees/{session_id}", dependencies=[Depends(accounts.require_role("edit"))])
def supprimer_seance_personnalisee(session_id: str) -> dict[str, bool]:
    """Retire entièrement une séance créée par ce système — métadonnée,
    placement courant et ligne en base. Jamais une séance de la maquette :
    `seances_annulees.yaml` est l'outil prévu pour celle-là, avec sa
    traçabilité (qui l'a demandé, quand) — une séance personnalisée n'a pas
    besoin de cette indirection puisqu'elle n'existe QUE parce que quelqu'un
    l'a créée ici."""
    state = get_state()
    seance = state.sessions_by_id.get(session_id)
    if seance is None or not seance.metadata.get("custom_session"):
        raise HTTPException(
            404,
            f"Aucune séance personnalisée « {session_id} » — seules les séances créées "
            "par ce système peuvent être supprimées ici.",
        )

    actuel = next((p for p in state.timetable if p.session_id == session_id), None)
    if actuel is not None:
        from cal_iut.celcat.ops import noter_placement_retire

        noter_placement_retire(actuel)
    state.timetable = [p for p in state.timetable if p.session_id != session_id]
    state.sessions = [s for s in state.sessions if s.id != session_id]
    del state.sessions_by_id[session_id]
    if state.current_run_id:
        get_repo().remove_current_placement(session_id)
    custom_sessions.remove_custom_session(session_id)
    _apres_ecriture_planning(session_id, "delete")
    return {"supprimee": True}


@app.post("/placements/{session_id}/valider", response_model=ForcagePedagogiqueResponse, dependencies=[Depends(accounts.require_role("edit"))])
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


@app.delete("/placements/{session_id}", response_model=ForcagePedagogiqueResponse, dependencies=[Depends(accounts.require_role("edit"))])
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


@app.post("/placements/completer", response_model=CompletionResponse, dependencies=[Depends(accounts.require_role("edit"))])
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
    Aligné sur l'inventaire réel (y compris WS*)."""
    placees = {p.session_id for p in state.timetable}
    for s in state.sessions:
        if s.id in placees:
            continue
        if code not in (s.teacher_codes or []):
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
    # Pixel de suivi d'ouverture (retour utilisateur 28/08/2026) — présent
    # UNIQUEMENT dans la version HTML : la version texte brut ne peut pas
    # porter d'image, et y coller une URL nue serait à la fois inutile et
    # visible. Absent si l'URL publique n'est pas configurée : mieux vaut
    # aucun suivi qu'une balise pointant vers une adresse invalide dans un
    # mail réel.
    try:
        pixel_html = (
            f'<img src="{e(mailer.public_base_url())}/mail/pixel/{e(code)}.gif" '
            'width="1" height="1" alt="" style="display:none">'
        )
    except mailer.MailerNotConfigured:
        pixel_html = ""
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
        f"{pixel_html}"
        "</div>"
    )
    return "Votre emploi du temps MMI", texte, html_body


@app.get("/notifications", response_model=NotificationConfigResponse,
         dependencies=[Depends(accounts.require_role("admin"))])
def lire_notifications() -> NotificationConfigResponse:
    """Réglage des notifications. Admin seulement : la liste des
    destinataires est une donnée personnelle, elle n'a rien à faire dans un
    lien public (cf. `_CLES_PRIVEES_PAYLOAD`, même principe)."""
    from cal_iut.api import mailer, notifications

    cfg = notifications.config()
    return NotificationConfigResponse(
        destinataires=cfg["destinataires"],
        evenements=cfg["evenements"],
        delai_minutes=cfg["delai_minutes"],
        libelles=dict(notifications.EVENEMENTS),
        en_attente=notifications.en_attente(),
        mail_configure=mailer.is_configured(),
        mail_a_la_clef_api=mailer.has_api_key(),
        mail_a_url_publique=mailer.has_public_url(),
    )


@app.put("/notifications", response_model=NotificationConfigResponse,
         dependencies=[Depends(accounts.require_role("admin"))])
def ecrire_notifications(body: NotificationConfigRequest) -> NotificationConfigResponse:
    from cal_iut.api import notifications

    try:
        notifications.enregistrer_config(body.model_dump(exclude_none=True))
    except ValueError as exc:
        # 400 et pas 500 : c'est une saisie à corriger, et le message dit
        # laquelle (adresse invalide, événement inconnu).
        raise HTTPException(400, str(exc)) from exc
    return lire_notifications()


@app.post("/notifications/test", dependencies=[Depends(accounts.require_role("admin"))])
def tester_notifications() -> dict[str, object]:
    """Envoie un résumé de test aux destinataires enregistrés — le seul moyen
    de vérifier que la configuration marche sans attendre qu'un vrai
    changement se produise."""
    from cal_iut.api import notifications

    cfg = notifications.config()
    if not cfg["destinataires"]:
        raise HTTPException(400, "Aucun destinataire enregistré.")
    actifs = [c for c, ok in cfg["evenements"].items() if ok]
    if not actifs:
        raise HTTPException(400, "Aucun événement suivi : rien ne partirait.")
    # On passe par la file normale pour tester le chemin réel, pas un raccourci.
    with_evenement = actifs[0]
    notifications._file.append(("test", with_evenement, "Message de test — la configuration fonctionne."))
    envoye = notifications.vider_file()
    if not envoye:
        raise HTTPException(502, "L'envoi a échoué (RESEND_API_KEY manquante ou service indisponible).")
    return {"envoye_a": cfg["destinataires"]}


@app.get("/mail/pixel/{code}.gif")
def mail_pixel(code: str) -> Response:
    """Pixel de suivi d'ouverture — appelé par le client mail de
    l'enseignant, donc OBLIGATOIREMENT accessible sans authentification
    (cf. `_PUBLIC_PATHS`) : aucun client mail ne peut se connecter.
    N'expose rien en retour (une image vide de 43 octets) et n'enregistre
    que la PREMIÈRE ouverture d'un envoi déjà journalisé.

    Répond toujours 200 avec l'image, même pour un code inconnu : renvoyer
    une erreur afficherait une icône d'image cassée dans le mail d'un
    enseignant, pour un problème qui ne le concerne pas."""
    mailer.record_opened(code)
    return Response(
        content=mailer.PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/mail/teacher-links/apercu/{code}", dependencies=[Depends(accounts.require_role("admin"))])
def mail_teacher_link_apercu(code: str) -> dict[str, str]:
    """Le mail EXACT tel qu'il partira, pour ce destinataire (retour
    utilisateur 28/08/2026 : pouvoir relire avant d'envoyer à 32 personnes).
    Rendu par la même fonction que l'envoi réel (`_teacher_mail_text`) —
    un aperçu calculé autrement finirait tôt ou tard par diverger de ce qui
    part vraiment, ce qui est pire que pas d'aperçu du tout."""
    state = get_state()
    noms = _noms_enseignants(state)
    try:
        lien = mailer.personal_link(code)
    except mailer.MailerNotConfigured:
        # Aperçu utile même sans URL publique configurée : on montre la
        # forme du lien, en disant clairement qu'elle n'est pas définitive.
        lien = f"(CAL_IUT_PUBLIC_URL non configurée)/#vue=prof&prof={code}&mode=prof&t={code}"
    sujet, texte, html_body = _teacher_mail_text(state, code, noms.get(code, code), lien)
    return {"subject": sujet, "text": texte, "html": html_body}


@app.get("/mail/teacher-links", response_model=TeacherMailPreviewListResponse, dependencies=[Depends(accounts.require_role("admin"))])
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
        a_la_clef_api=mailer.has_api_key(),
        a_url_publique=mailer.has_public_url(),
        teachers=[
            TeacherMailPreviewResponse(
                code=code,
                name=noms.get(code, code),
                email=contacts.get(code),
                sent_at=log.get(code, {}).get("sent_at"),
                opened_at=log.get(code, {}).get("opened_at"),
            )
            for code in codes
        ],
    )


@app.post("/mail/teacher-links/send", response_model=SendTeacherMailsResponse, dependencies=[Depends(accounts.require_role("admin"))])
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


def _notifier(evenement: str, texte: str) -> None:
    """Signale une modification du planning, sans jamais faire échouer
    l'appelant : une notification est un à-côté, le déplacement de séance
    qui l'a déclenchée doit aboutir même si le mail casse."""
    try:
        from cal_iut.api import notifications

        notifications.signaler(evenement, texte)
        notifications.envoyer_si_temps_ecoule()
    except Exception:  # noqa: BLE001
        pass


def _ou(placement: object) -> str:
    jours = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")
    heures = ("8h", "9h30", "11h", "14h", "15h30", "17h")
    jour = jours[placement.day] if 0 <= placement.day < 5 else "?"
    heure = heures[placement.slot] if 0 <= placement.slot < 6 else "?"
    return f"S{placement.week + 1} {jour} {heure}"


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


from cal_iut.mcp.http_rpc import handle_mcp_post
from cal_iut.mcp.server import MCP_ASGI


@app.post("/mcp", include_in_schema=False)
async def mcp_jsonrpc(request: Request):
    """JSON-RPC MCP (initialize / tools) — Bearer via middleware, pas le cookie."""
    return await handle_mcp_post(request)


class _McpSlashFix:
    """Starlette Mount('/mcp') laisse path='' pour POST/GET /mcp sans slash."""

    def __init__(self, app: object) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope.get("type") == "http" and not scope.get("path"):
            scope = {**scope, "path": "/"}
        await self.app(scope, receive, send)


app.mount("/mcp", _McpSlashFix(MCP_ASGI))

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
