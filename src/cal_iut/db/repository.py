"""Couche d'accès données."""

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from cal_iut.db.models import (
    Correction,
    CurrentPlacement,
    ObjectiveWeights,
    PlanningRun,
    ScheduleException,
    SolverPlacement,
    TeacherPreference,
)


@dataclass
class DiffEntry:
    session_id: str
    course_code: str
    solver_week: int
    solver_day: int
    solver_slot: int
    current_week: int
    current_day: int
    current_slot: int
    changed: bool
    locked: bool


class PlanningRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create_weights(self) -> ObjectiveWeights:
        row = self.db.query(ObjectiveWeights).order_by(ObjectiveWeights.id.desc()).first()
        if row:
            return row
        row = ObjectiveWeights(reason="default")
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def save_weights(self, weights: dict[str, int], reason: str) -> ObjectiveWeights:
        row = ObjectiveWeights(
            gap_penalty=weights.get("gap_penalty", 100),
            day_balance=weights.get("day_balance", 20),
            isolated_day=weights.get("isolated_day", 50),
            eval_clustering=weights.get("eval_clustering", 30),
            room_change=weights.get("room_change", 15),
            pedagogical_order=weights.get("pedagogical_order", 10),
            teacher_preference=weights.get("teacher_preference", 25),
            afternoon_preference=weights.get("afternoon_preference", 0),
            reason=reason,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def weights_as_dict(self) -> dict[str, int]:
        w = self.get_or_create_weights()
        return {
            "gap_penalty": w.gap_penalty,
            "day_balance": w.day_balance,
            "isolated_day": w.isolated_day,
            "eval_clustering": w.eval_clustering,
            "room_change": w.room_change,
            "pedagogical_order": w.pedagogical_order,
            "teacher_preference": w.teacher_preference,
            "afternoon_preference": w.afternoon_preference,
        }

    def save_run(
        self,
        parcours: str,
        semestre: str,
        status: str,
        objective_value: int | None,
        gap_penalty: int,
        weeks: int,
        solver_placements: list[dict[str, object]],
        current_placements: list[dict[str, object]],
    ) -> PlanningRun:
        run = PlanningRun(
            parcours=parcours,
            semestre=semestre,
            status=status,
            objective_value=objective_value,
            gap_penalty=gap_penalty,
            weeks=weeks,
        )
        self.db.add(run)
        self.db.flush()

        for p in solver_placements:
            self.db.add(
                SolverPlacement(
                    run_id=run.id,
                    session_id=str(p["session_id"]),
                    week=int(p["week"]),
                    day=int(p["day"]),
                    slot=int(p["slot"]),
                    course_code=str(p["course_code"]),
                    room_id=p.get("room_id"),
                )
            )

        self.db.query(CurrentPlacement).delete()
        for p in current_placements:
            self.db.add(
                CurrentPlacement(
                    run_id=run.id,
                    session_id=str(p["session_id"]),
                    week=int(p["week"]),
                    day=int(p["day"]),
                    slot=int(p["slot"]),
                    course_code=str(p["course_code"]),
                    room_id=p.get("room_id"),
                    room_label=p.get("room_label"),
                    locked=bool(p.get("locked", False)),
                )
            )

        self.db.commit()
        self.db.refresh(run)
        return run

    def get_latest_run(self, parcours: str | None = None, semestre: str | None = None) -> PlanningRun | None:
        q = self.db.query(PlanningRun).order_by(PlanningRun.id.desc())
        if parcours:
            q = q.filter(PlanningRun.parcours == parcours)
        if semestre:
            q = q.filter(PlanningRun.semestre == semestre)
        return q.first()

    def save_correction(
        self,
        run_id: int,
        session_id: str,
        proposed: dict[str, int],
        manual: dict[str, int],
        locked: bool,
        forced: bool,
        course_code: str | None,
        teacher_codes: list[str],
    ) -> Correction:
        row = Correction(
            run_id=run_id,
            session_id=session_id,
            proposed_week=proposed["week"],
            proposed_day=proposed["day"],
            proposed_slot=proposed["slot"],
            manual_week=manual["week"],
            manual_day=manual["day"],
            manual_slot=manual["slot"],
            locked=locked,
            forced=forced,
            course_code=course_code,
            teacher_codes=",".join(teacher_codes),
        )
        self.db.add(row)
        self.db.commit()
        return row

    def update_current_placement(
        self,
        session_id: str,
        week: int,
        day: int,
        slot: int,
        room_id: str | None,
        room_label: str | None,
        locked: bool,
        run_id: int | None = None,
        course_code: str | None = None,
    ) -> bool:
        """Retourne `False` si le placement n'a PAS pu être enregistré."""
        row = self.db.get(CurrentPlacement, session_id)
        if row is None:
            # Créer plutôt qu'ignorer en silence. L'ancienne version ne faisait
            # RIEN quand la ligne n'existait pas : le déplacement restait visible
            # à l'écran (il vit dans `state.timetable`) mais n'était jamais
            # persisté — il disparaissait au redémarrage du serveur, sans le
            # moindre message. Le cas survient dès qu'une séance est déplacée
            # alors qu'elle n'était pas dans le dernier run enregistré
            # (régénération partielle, run interrompu, base recréée).
            if run_id is None:
                latest = self.get_latest_run()
                run_id = latest.id if latest else None
            if run_id is None:
                # Aucun run enregistré : il n'y a rien à quoi rattacher ce
                # placement. On le signale à l'appelant au lieu de faire
                # semblant d'avoir enregistré.
                return False
            row = CurrentPlacement(
                session_id=session_id, run_id=run_id, course_code=course_code or ""
            )
            self.db.add(row)
        row.week = week
        row.day = day
        row.slot = slot
        row.room_id = room_id
        row.room_label = room_label
        row.locked = locked
        if course_code:
            row.course_code = course_code
        self.db.commit()
        return True

    def upsert_current_placements(self, run_id: int, placements: list[dict[str, object]]) -> None:
        """
        Écriture ciblée pour une régénération partielle (1-2 semaines) :
        get-or-insert par `session_id`, SANS le `.delete()` global que fait
        `save_run` — celui-ci raserait tout `CurrentPlacement`, y compris les
        séances hors de la portée régénérée. Sécurité centrale du chantier
        "régénération ciblée" (cf. plan) : ne jamais toucher ce qui n'a pas
        été explicitement recalculé.
        """
        for p in placements:
            row = self.db.get(CurrentPlacement, str(p["session_id"]))
            if row is None:
                row = CurrentPlacement(run_id=run_id, session_id=str(p["session_id"]))
                self.db.add(row)
            row.week = int(p["week"])
            row.day = int(p["day"])
            row.slot = int(p["slot"])
            row.course_code = str(p["course_code"])
            row.room_id = p.get("room_id")
            row.room_label = p.get("room_label")
            row.locked = bool(p.get("locked", False))
        self.db.commit()

    def create_exception(
        self,
        kind: str,
        exception_date: date,
        teacher_code: str | None = None,
        room_id: str | None = None,
        slots: list[int] | None = None,
        reason: str | None = None,
    ) -> ScheduleException:
        row = ScheduleException(
            kind=kind,
            exception_date=exception_date,
            teacher_code=teacher_code,
            room_id=room_id,
            slots=",".join(str(s) for s in sorted(slots)) if slots else None,
            reason=reason,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_exceptions(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        teacher_code: str | None = None,
        active_only: bool = True,
    ) -> list[ScheduleException]:
        q = self.db.query(ScheduleException).order_by(ScheduleException.exception_date)
        if active_only:
            q = q.filter(ScheduleException.active.is_(True))
        if date_from:
            q = q.filter(ScheduleException.exception_date >= date_from)
        if date_to:
            q = q.filter(ScheduleException.exception_date <= date_to)
        if teacher_code:
            q = q.filter(ScheduleException.teacher_code == teacher_code)
        return q.all()

    def deactivate_exception(self, exception_id: int) -> bool:
        row = self.db.get(ScheduleException, exception_id)
        if row is None:
            return False
        row.active = False
        self.db.commit()
        return True

    def list_corrections(self, run_id: int | None = None) -> list[Correction]:
        q = self.db.query(Correction).order_by(Correction.id.desc())
        if run_id:
            q = q.filter(Correction.run_id == run_id)
        return q.all()

    def get_diff(self, run_id: int | None = None) -> list[DiffEntry]:
        run = self.db.get(PlanningRun, run_id) if run_id else self.get_latest_run()
        if not run:
            return []

        solver = {
            s.session_id: s
            for s in self.db.query(SolverPlacement).filter(SolverPlacement.run_id == run.id)
        }
        current = {
            c.session_id: c
            for c in self.db.query(CurrentPlacement).filter(CurrentPlacement.run_id == run.id)
        }

        diff: list[DiffEntry] = []
        for sid, cur in current.items():
            sol = solver.get(sid)
            if not sol:
                continue
            changed = (sol.week, sol.day, sol.slot) != (cur.week, cur.day, cur.slot)
            diff.append(
                DiffEntry(
                    session_id=sid,
                    course_code=cur.course_code,
                    solver_week=sol.week,
                    solver_day=sol.day,
                    solver_slot=sol.slot,
                    current_week=cur.week,
                    current_day=cur.day,
                    current_slot=cur.slot,
                    changed=changed,
                    locked=cur.locked,
                )
            )
        return diff

    def upsert_teacher_preference(
        self,
        teacher_code: str | None,
        course_code: str | None,
        preferred_slots: list[int],
        preferred_days: list[int],
    ) -> None:
        row = (
            self.db.query(TeacherPreference)
            .filter(
                TeacherPreference.teacher_code == teacher_code,
                TeacherPreference.course_code == course_code,
            )
            .first()
        )
        if not row:
            row = TeacherPreference(teacher_code=teacher_code, course_code=course_code)
            self.db.add(row)
        row.preferred_slots = ",".join(str(s) for s in sorted(set(preferred_slots)))
        row.preferred_days = ",".join(str(d) for d in sorted(set(preferred_days)))
        row.sample_count += 1
        row.weight = min(3.0, 1.0 + row.sample_count * 0.1)
        self.db.commit()

    def list_teacher_preferences(self) -> list[TeacherPreference]:
        return self.db.query(TeacherPreference).all()

    def export_placements_json(self, run_id: int | None = None) -> str:
        run = self.db.get(PlanningRun, run_id) if run_id else self.get_latest_run()
        if not run:
            return "[]"
        rows = self.db.query(CurrentPlacement).filter(CurrentPlacement.run_id == run.id).all()
        return json.dumps(
            [
                {
                    "session_id": r.session_id,
                    "course_code": r.course_code,
                    "week": r.week,
                    "day": r.day,
                    "slot": r.slot,
                    "room_id": r.room_id,
                    "room_label": r.room_label,
                    "locked": r.locked,
                }
                for r in rows
            ],
            ensure_ascii=False,
            indent=2,
        )
