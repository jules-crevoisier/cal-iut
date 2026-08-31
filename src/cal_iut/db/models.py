"""Modèles SQLAlchemy — persistance SQLite."""

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class PlanningRun(Base):
    __tablename__ = "planning_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parcours: Mapped[str] = mapped_column(String(64), index=True)
    semestre: Mapped[str] = mapped_column(String(8), index=True)
    status: Mapped[str] = mapped_column(String(32))
    objective_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gap_penalty: Mapped[int] = mapped_column(Integer, default=0)
    weeks: Mapped[int] = mapped_column(Integer, default=16)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    solver_placements: Mapped[list["SolverPlacement"]] = relationship(back_populates="run")
    corrections: Mapped[list["Correction"]] = relationship(back_populates="run")


class SolverPlacement(Base):
    """Snapshot solveur au moment de la génération (pour diff)."""

    __tablename__ = "solver_placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    week: Mapped[int] = mapped_column(Integer)
    day: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)
    course_code: Mapped[str] = mapped_column(String(32))
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    run: Mapped["PlanningRun"] = relationship(back_populates="solver_placements")


class CurrentPlacement(Base):
    """État courant du planning (après modifications manuelles)."""

    __tablename__ = "current_placements"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), index=True)
    week: Mapped[int] = mapped_column(Integer)
    day: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)
    course_code: Mapped[str] = mapped_column(String(32))
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    proposed_week: Mapped[int] = mapped_column(Integer)
    proposed_day: Mapped[int] = mapped_column(Integer)
    proposed_slot: Mapped[int] = mapped_column(Integer)
    manual_week: Mapped[int] = mapped_column(Integer)
    manual_day: Mapped[int] = mapped_column(Integer)
    manual_slot: Mapped[int] = mapped_column(Integer)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    course_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    teacher_codes: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    run: Mapped["PlanningRun"] = relationship(back_populates="corrections")


class ScheduleException(Base):
    """
    Exception ponctuelle déclarée par l'utilisateur (ex. "prof absent le
    12/11") — distincte des indisponibilités récurrentes (`TeacherAvailability`
    en YAML/CSV, hebdomadaires) : une seule table polymorphe couvre les
    différents `kind` plutôt qu'une table par type, même esprit que
    `Correction`. Soft-delete (`active`) pour garder l'historique, jamais de
    suppression physique.
    """

    __tablename__ = "schedule_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # "teacher_absence" | "room_unavailable"
    exception_date: Mapped[date] = mapped_column(Date, index=True)
    slots: Mapped[str | None] = mapped_column(String(32), nullable=True)  # CSV "0,1,2" ; null = journée entière
    teacher_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ObjectiveWeights(Base):
    __tablename__ = "objective_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gap_penalty: Mapped[int] = mapped_column(Integer, default=100)
    day_balance: Mapped[int] = mapped_column(Integer, default=20)
    isolated_day: Mapped[int] = mapped_column(Integer, default=50)
    eval_clustering: Mapped[int] = mapped_column(Integer, default=30)
    room_change: Mapped[int] = mapped_column(Integer, default=15)
    pedagogical_order: Mapped[int] = mapped_column(Integer, default=10)
    teacher_preference: Mapped[int] = mapped_column(Integer, default=25)
    afternoon_preference: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base):
    """Compte utilisateur (email + mot de passe) — remplace le mot de passe
    unique partagé (`CAL_IUT_PASSWORD`, `api/auth.py`). `role`/`status` sont
    relus depuis cette table à CHAQUE requête (jamais mis en cache dans le
    cookie de session) : un changement de rôle ou une désactivation prend
    effet dès la requête suivante de l'utilisateur concerné."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="read_only")
    status: Mapped[str] = mapped_column(String(32), default="pending_email")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    tokens: Mapped[list["EmailToken"]] = relationship(back_populates="user", foreign_keys="EmailToken.user_id")
    mcp_keys: Mapped[list["McpKey"]] = relationship(back_populates="user")


class EmailToken(Base):
    """Jeton à usage unique (confirmation d'email ou réinitialisation de mot
    de passe) — seul le hash SHA-256 est stocké, jamais la valeur brute
    envoyée par mail (même logique qu'un mot de passe, cf. `password_hash`)."""

    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="tokens", foreign_keys=[user_id])


class McpKey(Base):
    """Clé Bearer MCP d'un compte — seul le hash SHA-256 est stocké, jamais
    la valeur brute (affichée une seule fois à la génération). `prefix` est
    le début visible dans l'UI pour reconnaître une clé sans la révéler."""

    __tablename__ = "mcp_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="mcp_keys")


class TeacherPreference(Base):
    """Préférences apprises par enseignant/matière."""

    __tablename__ = "teacher_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    teacher_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    course_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    preferred_slots: Mapped[str] = mapped_column(String(64), default="")
    preferred_days: Mapped[str] = mapped_column(String(32), default="")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
