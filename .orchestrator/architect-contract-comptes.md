# Architect contract — comptes utilisateurs

goal: Replace the single shared-password login (CAL_IUT_PASSWORD) with real
individual accounts (email + password, roles read_only/edit/admin, email
confirmation, admin activation, forgot-password) across
src/cal_iut/api/*, src/cal_iut/db/*, while leaving the public `?t=...`
personal links (teacher/group/promo) completely untouched.

## Locked decisions (user, after architect risks were raised)
- A re-signup on an email already `pending_email` does NOT 409 — it
  re-issues a fresh confirm_email token (invalidating prior unused ones)
  and resends the email. Anti mail-scanner-prefetch recovery.
- CLI (`cal-iut prod diff/push`) needs a real account: `CAL_IUT_EMAIL` /
  `CAL_IUT_PROD_EMAIL` env vars, using crevoisier.ju@gmail.com (admin,
  auto-promoted on signup).

## Approach

Two new SQLAlchemy tables (`User`, `EmailToken`) picked up by the existing
ad-hoc `Base.metadata.create_all()` bootstrap (no real Alembic env exists
despite the dependency — `src/cal_iut/db/session.py::init_db` is the only
migration mechanism in this repo). Auth stays a signed HMAC cookie (reusing
`auth.get_secret()`) rather than a session table or JWT, but the cookie now
carries only `user_id` + expiry — role/status are re-read from the `users`
row on every request, so a disable/role-change takes effect on that user's
very next request, not at cookie expiry. `auth.py` keeps only the HMAC
secret and `verify_personal_link_param` (untouched, out of scope);
everything shared-password-specific moves to a new `src/cal_iut/api/accounts.py`.
This is a hard, one-shot cutover: `CAL_IUT_PASSWORD`-handling code is
deleted outright, no dual-mode flag.

## Data model (src/cal_iut/db/models.py)

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int]                       # PK, autoincrement
    email: Mapped[str]                    # String(255), unique=True, index=True
                                           # ALWAYS stored lowercased+stripped
    password_hash: Mapped[str]            # String(255)
    role: Mapped[str]                     # String(16): "read_only"|"edit"|"admin", default "read_only"
    status: Mapped[str]                   # String(32): "pending_email"|"pending_admin_activation"|"active"|"disabled", default "pending_email"
    created_at: Mapped[datetime]          # default=_utcnow (reuse helper already in models.py)
    email_confirmed_at: Mapped[datetime | None]   # nullable
    activated_at: Mapped[datetime | None]         # nullable
    activated_by: Mapped[int | None]      # ForeignKey("users.id"), nullable
    tokens: Mapped[list["EmailToken"]] = relationship(back_populates="user")

class EmailToken(Base):
    __tablename__ = "email_tokens"
    id: Mapped[int]                       # PK, autoincrement
    user_id: Mapped[int]                  # ForeignKey("users.id"), index=True
    token_hash: Mapped[str]               # String(64), unique=True, index=True — sha256 hex of RAW token; raw never stored
    purpose: Mapped[str]                  # String(32): "confirm_email"|"reset_password"
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]      # nullable; set once, never cleared
    created_at: Mapped[datetime]          # default=_utcnow
    user: Mapped["User"] = relationship(back_populates="tokens")
```

## Password hashing

Add `argon2-cffi>=23.1` to `pyproject.toml` `[project].dependencies`. In
`src/cal_iut/api/accounts.py`:
```python
_ph: argon2.PasswordHasher                          # module-level instance
def hash_password(raw: str) -> str                  # _ph.hash(raw)
def verify_password(raw: str, hashed: str) -> bool  # catches VerifyMismatchError -> False
```

## Session mechanism (src/cal_iut/api/accounts.py, new module)

Reuses `auth.get_secret()` for the HMAC key (no second secret file):
```python
ACCOUNT_SESSION_COOKIE = "cal_iut_account_session"   # deliberately NOT "cal_iut_session"
                                                      # (old shared-password cookie must never
                                                      # be misread as a user id)
ACCOUNT_SESSION_MAX_AGE_S = 30 * 24 * 3600           # 30 days

def make_account_session_token(user_id: int) -> str  # f"{user_id}.{expiry}.{sig}"
def verify_account_session_token(token: str | None) -> int | None
    # returns user_id if signature+expiry valid, else None. Does NOT check DB.

ROLE_ORDER: dict[str, int]     # {"read_only": 0, "edit": 1, "admin": 2}

def get_current_user(request: Request, repo: AccountRepository = Depends(...)) -> User
    # 401 if no/invalid cookie OR user row missing.

def require_role(minimum: str) -> Callable[[Request], User]
    # Depends(require_role("edit")) etc.
    # 401 if not logged in, 403 if status != "active", 403 if ROLE_ORDER[user.role] < ROLE_ORDER[minimum]

ADMIN_EMAILS: frozenset[str] = {"crevoisier.ju@gmail.com", "kyllian.bresson@univ-reims.fr"}
    # compared lowercased against normalized signup email

def build_confirm_token() -> tuple[str, str]   # (raw, sha256_hex); raw = secrets.token_urlsafe(32)
def build_reset_token() -> tuple[str, str]     # same shape, separate purpose
CONFIRM_TOKEN_TTL_S = 48 * 3600
RESET_TOKEN_TTL_S = 1 * 3600
```

`src/cal_iut/api/auth.py` is trimmed: keeps `get_secret()`/`_secret_path()`
and `verify_personal_link_param()` only; `get_password()`, `_PASSWORD_ENV`,
`SESSION_COOKIE`, `SESSION_MAX_AGE_S`, `make_session_token`,
`verify_session_token` are DELETED (superseded by the above).

## Repository (src/cal_iut/db/accounts_repository.py, new — mirrors PlanningRepository in src/cal_iut/db/repository.py)

```python
class AccountRepository:
    def __init__(self, db: Session) -> None
    def get_by_email(self, email: str) -> User | None       # email pre-normalized by caller
    def get_by_id(self, user_id: int) -> User | None
    def create_pending_user(self, email: str, password_hash: str) -> User
    def mark_email_confirmed(self, user: User) -> None
        # sets email_confirmed_at; sets role="admin", status="active", activated_at=now
        # if email in ADMIN_EMAILS, else status="pending_admin_activation"
    def activate(self, user: User, role: str, activated_by: int) -> None
    def set_role(self, user: User, role: str) -> None
    def set_status(self, user: User, status: str) -> None
    def count_active_admins(self) -> int
    def list_users(self, status: str | None = None) -> list[User]
    def create_token(self, user_id: int, token_hash: str, purpose: str, expires_at: datetime) -> EmailToken
    def get_valid_token(self, token_hash: str, purpose: str) -> EmailToken | None
        # used_at is None AND expires_at > now
    def consume_token(self, token: EmailToken) -> None       # used_at = now
    def invalidate_outstanding_tokens(self, user_id: int, purpose: str) -> None
        # used_at = now for every unused token of that purpose/user
```

## Endpoints (src/cal_iut/api/main.py — house style: HTTPException with detail={"message": ...} dict, matching existing 409s)

- `POST /auth/signup` — body `SignupRequest{email: str, password: str}` (password min_length=10).
  Checks `mailer.is_configured()` FIRST → 503 `{"message": "Envoi d'email non configuré (RESEND_API_KEY/CAL_IUT_PUBLIC_URL absent)."}` before touching the DB (never create an orphan account nobody can confirm).
  Normalizes email. 409 `{"message": "Un compte existe déjà pour cet email."}` if an existing user is NOT status=="pending_email".
  **If an existing user IS status=="pending_email": do not 409 — invalidate prior unused confirm_email tokens for that user, issue+email a fresh one, return 201 same as fresh signup** (locked user decision, anti mail-scanner).
  On success (new or resent): creates/reuses pending_email user, creates confirm_email EmailToken, mailer.send_email(..., accounts.confirmation_link(raw_token)). Returns 201 `{"status": "pending_email"}`.
- `GET /auth/confirm-email?token=...` — hash token, look up valid confirm_email EmailToken. Invalid/expired/used → 302 redirect to `f"{mailer.public_base_url()}/#compte=confirme&statut=erreur"`. Valid → consume token, mark_email_confirmed, 302 redirect to `f"{mailer.public_base_url()}/#compte=confirme&statut=ok"`.
- `POST /auth/login` — `LoginRequest` REPLACED (breaking, intentional) from `{password}` to `{email: str, password: str}`. Unknown email or wrong password → identical 401 `{"detail": "Email ou mot de passe incorrect."}` (no user enumeration). status=="pending_email" → 403 `{"detail": "Confirmez votre email avant de vous connecter."}`. status=="disabled" → 403 `{"detail": "Compte désactivé."}`. status in ("pending_admin_activation","active") → sets ACCOUNT_SESSION_COOKIE, 200 `{"role": ..., "status": ...}` (a pending user CAN log in — needed so the frontend can show the "waiting on admin" gate via GET /auth/me).
- `POST /auth/logout` — deletes ACCOUNT_SESSION_COOKIE.
- `POST /auth/forgot-password` — body `{email: str}`. ALWAYS 200 `{"ok": true}`. Internally: if user exists and status=="active", invalidate_outstanding_tokens(user.id, "reset_password"), create fresh one, email accounts.reset_password_link(raw_token). Any other case (unknown, pending, disabled) — silently does nothing (but log server-side, never fully silent).
- `POST /auth/reset-password` — body `{token: str, new_password: str}` (min_length=10). Invalid/expired/used token → 400 `{"detail": "Lien de réinitialisation invalide ou expiré."}`. status=="disabled" → 403 `{"detail": "Compte désactivé."}`. Else: sets new password_hash, consumes this token AND invalidate_outstanding_tokens(user.id, "reset_password") (kills every other outstanding reset link), 200 `{"ok": true}`. Does not auto-login.
- `GET /auth/me` — requires only a valid account-session cookie (regardless of status). No cookie → 401. Returns `{"id", "email", "role", "status"}`.
- `GET /admin/users` — Depends(require_role("admin")). Optional `?status=` filter. Returns `{"users": [{"id","email","role","status","created_at","email_confirmed_at","activated_at"}]}`. Not paginated (bounded headcount).
- `PATCH /admin/users/{id}` — Depends(require_role("admin")). Body `AdminUserUpdateRequest{role: Literal["read_only","edit","admin"] | None = None, status: Literal["active","disabled"] | None = None}`, at least one field required else 400. Unknown id → 404. If `role` is set on a pending_admin_activation user and no explicit status given, also sets status="active", activated_at=now, activated_by=<acting admin id> (this IS activation). Guard: reject any change that would leave count_active_admins() == 0 → 409 `{"message": "Impossible de retirer le dernier administrateur actif."}`. Returns the updated user row.

## Permission gating rule

Floor for every route under `_PROTECTED_PREFIXES`: `Depends(require_role("read_only"))`.
Mutating routes: `Depends(require_role("edit"))`.
`/admin/*` and the former `require_admin_session` group (POST /rooms, GET /celcat/plan, POST /notifications/test, GET /mail/teacher-links*, POST /mail/teacher-links/send): `Depends(require_role("admin"))` — 1:1 replacement, same tightness as today.
Untouched: `/ics/prof/{code}.ics`, `/ics/groupe/{group_id}.ics`, and every route reached via `?t=...` — personal-link bypass (`auth.verify_personal_link_param`) still short-circuits BEFORE any require_role dependency runs, exactly as today.

`require_auth` middleware (main.py, replacing the `password = auth.get_password()` branch): personal-link bypass first (unchanged) → else read ACCOUNT_SESSION_COOKIE, resolve user; no/invalid cookie → 401; valid cookie but status != "active" → 403 `{"detail": "Compte en attente d'activation.", "status": user.status}`; status=="active" → attach user to `request.state.user`, continue.
`_PUBLIC_PATHS` gains `/auth/signup`, `/auth/confirm-email`, `/auth/forgot-password`, `/auth/reset-password`, `/auth/me` (alongside existing `/auth/login`, `/auth/logout`, `/auth/status`, `/health`). `_PROTECTED_PREFIXES` gains `"/admin"`. `_verifier_couverture_auth` needs no logic change, just the two lists.

`GET /app-state` inline check (~line 536): `if auth.verify_session_token(...)` becomes `if accounts.get_current_user(request, optional=True) is not None:` (any active account role → full payload incl. teacher emails; personal-link-only → redacted, same as today).

## Cutover

No env flag, no dual mode: `CAL_IUT_PASSWORD`-reading code (`auth.get_password`, old `/auth/login` handler, 503-if-unconfigured branch) deleted in the same change. Safety net: signup is public to any email, and the two hardcoded admin emails skip pending_admin_activation entirely on email confirmation. No pre-seeded row.

## CLI / prod-sync (src/cal_iut/sync/prod.py, src/cal_iut/cli.py)

`sync/prod.py::Instance` needs `email: str` alongside `mot_de_passe: str`, posting `{"email": self.email, "password": self.mot_de_passe}` to /auth/login. `prod_depuis_env()` reads new `CAL_IUT_PROD_EMAIL` alongside existing `CAL_IUT_PROD_PASSWORD`. `cli.py` reads new `CAL_IUT_EMAIL` alongside `CAL_IUT_PASSWORD` for the local `Instance`. The account used needs role>=edit (calls mutating endpoints).

## Files

- `src/cal_iut/db/models.py` — edit — add `User`, `EmailToken`.
- `src/cal_iut/db/accounts_repository.py` — create — `AccountRepository`.
- `src/cal_iut/api/accounts.py` — create — hashing, tokens, cookie, require_role/get_current_user, ADMIN_EMAILS, confirmation_link/reset_password_link builders (or these two land in mailer.py instead — pick one, not both; mailer.py already has a `personal_link()` builder to mirror).
- `src/cal_iut/api/mailer.py` — edit — add `confirmation_link(token)` / `reset_password_link(token)` if not placed in accounts.py.
- `src/cal_iut/api/auth.py` — edit — strip to `get_secret()` + `verify_personal_link_param()` only.
- `src/cal_iut/api/schemas.py` — edit — extend `LoginRequest`; add `SignupRequest`, `SignupResponse`, `ForgotPasswordRequest`, `ResetPasswordRequest`, `MeResponse`, `AdminUserResponse`, `AdminUserListResponse`, `AdminUserUpdateRequest`.
- `src/cal_iut/api/main.py` — edit — remove shared-password login/middleware branch and require_admin_session; add the /auth/*, /admin/* routes; apply Depends(require_role(...)) per mapping; update _PUBLIC_PATHS/_PROTECTED_PREFIXES; fix GET /app-state inline check.
- `src/cal_iut/sync/prod.py` — edit — Instance.email field, /auth/login payload, prod_depuis_env() reads CAL_IUT_PROD_EMAIL.
- `src/cal_iut/cli.py` — edit — cmd_prod reads CAL_IUT_EMAIL for local Instance.
- `pyproject.toml` — edit — add `argon2-cffi>=23.1`.

Frontend is OUT OF SCOPE for this build pass (backend only — no UI implemented yet, per orchestrator decision to ship the backend contract + TDD first).

## Acceptance (= the TDD spec already written to tests/test_comptes_utilisateurs.py — 45 tests, currently RED on ImportError)

See tests/test_comptes_utilisateurs.py. Make every one of those 45 tests pass. Do not rewrite the tests to fit the code — if a test seems to conflict with this contract, flag it, don't silently change it.

Also required (from the risks section, now locked):
- CAL_IUT_PASSWORD must not authenticate anything anywhere in src/cal_iut/api/* after this change.
- Personal `?t=...` links keep working with zero cookie/account.
- `cal-iut prod diff` must still be able to authenticate once CAL_IUT_EMAIL/CAL_IUT_PROD_EMAIL are set to a real account.
