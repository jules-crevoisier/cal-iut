"""Modèles SQLAlchemy — persistance SQLite."""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
