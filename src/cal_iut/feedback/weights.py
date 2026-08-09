"""Apprentissage simple des poids objectif depuis les corrections."""

from collections import Counter, defaultdict

from cal_iut.db.models import Correction
from cal_iut.db.repository import PlanningRepository


def analyze_corrections(corrections: list[Correction]) -> dict[str, object]:
    """Analyse les déplacements manuels pour détecter des patterns."""
    if not corrections:
        return {
            "patterns": [],
            "suggestions": {},
            "top_courses": [],
            "top_teachers": [],
            "total_corrections": 0,
        }

    slot_shifts: Counter[int] = Counter()
    afternoon_moves = 0
    morning_moves = 0
    by_course: dict[str, list[int]] = defaultdict(list)
    by_teacher: dict[str, list[int]] = defaultdict(list)

    for c in corrections:
        delta_slot = c.manual_slot - c.proposed_slot
        if delta_slot != 0:
            slot_shifts[delta_slot] += 1
        if c.manual_slot >= 3 and c.proposed_slot < 3:
            afternoon_moves += 1
        if c.manual_slot < 3 and c.proposed_slot >= 3:
            morning_moves += 1
        if c.course_code:
            by_course[c.course_code].append(c.manual_slot)
        if c.teacher_codes:
            for t in c.teacher_codes.split(","):
                if t:
                    by_teacher[t.strip()].append(c.manual_slot)

    suggestions: dict[str, int] = {}
    if afternoon_moves > morning_moves and afternoon_moves >= 3:
        suggestions["afternoon_preference"] = min(50, afternoon_moves * 5)
        suggestions["teacher_preference"] = 30

    if len(corrections) >= 5:
        suggestions["gap_penalty"] = min(150, 100 + len(corrections) // 2)

    patterns = []
    if afternoon_moves > 0:
        patterns.append(f"{afternoon_moves} déplacement(s) vers l'après-midi")
    if morning_moves > 0:
        patterns.append(f"{morning_moves} déplacement(s) vers le matin")

    top_courses = sorted(by_course.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    top_teachers = sorted(by_teacher.items(), key=lambda x: len(x[1]), reverse=True)[:5]

    return {
        "patterns": patterns,
        "suggestions": suggestions,
        "top_courses": [{"course": k, "moves": len(v)} for k, v in top_courses],
        "top_teachers": [{"teacher": k, "moves": len(v)} for k, v in top_teachers],
        "total_corrections": len(corrections),
    }


def apply_learned_weights(repo: PlanningRepository) -> dict[str, object]:
    """Réinjecte les poids appris depuis l'historique des corrections."""
    corrections = repo.list_corrections()
    analysis = analyze_corrections(corrections)
    current = repo.weights_as_dict()
    suggestions = analysis.get("suggestions", {})

    if not suggestions:
        return {"applied": False, "analysis": analysis, "weights": current}

    merged = {**current, **suggestions}
    repo.save_weights(merged, reason=f"auto-learn from {len(corrections)} corrections")

    for c in corrections:
        if c.manual_slot == c.proposed_slot:
            continue
        teachers = [t.strip() for t in (c.teacher_codes or "").split(",") if t.strip()]
        for t in teachers:
            repo.upsert_teacher_preference(t, None, [c.manual_slot], [c.manual_day])
        if c.course_code:
            repo.upsert_teacher_preference(None, c.course_code, [c.manual_slot], [c.manual_day])

    return {"applied": True, "analysis": analysis, "weights": merged}
