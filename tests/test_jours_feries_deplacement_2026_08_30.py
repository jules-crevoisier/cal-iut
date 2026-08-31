"""Un déplacement manuel ne doit jamais poser un cours un jour férié.

Bug réel, trouvé par Kyllian Bresson le 30/08/2026 : « l'outil parle du 11
novembre qui est un jour férié ». Un CM de WR104 avait été déplacé au
mercredi 11 novembre 2026, jour de l'Armistice — et c'était la SEULE séance
du planning posée ce jour-là, tout le reste le respectait.

Le solveur, lui, connaît les fériés (`constraints.py::
add_blocked_calendar_constraints`) et n'y place rien. Mais la validation d'un
déplacement MANUEL (`POST /placements/{id}/validate`, puis `PATCH
/placements/{id}`) ne les regardait pas : elle vérifiait les conflits de
ressource, le verrou PAC, les journées SAE, les événements du planning
officiel, l'ordre pédagogique et les indisponibilités enseignant — mais pas
le calendrier lui-même.

C'est la même famille de défaut que celui du 26/08 (les règles
institutionnelles ne servaient qu'à filtrer les suggestions) : une contrainte
respectée par le solveur, mais qu'une porte manuelle pouvait violer sans que
rien ne l'empêche.

Le férié est NON CONTOURNABLE : il ne s'agit pas d'un arbitrage
pédagogique qu'un humain pourrait trancher, l'IUT est fermé.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

ARMISTICE = date(2026, 11, 11)  # mercredi


def _semaine_jour_du(cible: date, calendrier, semestre: str = "S1") -> tuple[int, int]:
    """Position solveur (semaine, jour) d'une date réelle."""
    from cal_iut.calendar.academic import semester_week_offset

    offset = semester_week_offset(calendrier, semestre)
    for w in range(30):
        for d in range(5):
            if calendrier.week_day_to_date(offset + w, d) == cible:
                return w, d
    raise AssertionError(f"{cible} introuvable dans le calendrier")



@pytest.fixture
def client(db_isole):
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "teacher_duos", "corrections",
            "courses", "config_dir",
        )
    }
    seance = SessionToPlace(
        id="seance", course_code="WR104", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
        sequence_order=1, group_ids=["but1-promo"], teacher_codes=["MMA"], duration_slots=1,
    )
    calendrier = build_default_calendar_2026_2027()
    # La séance est posée le LUNDI DE LA SEMAINE DU FÉRIÉ : viser le mercredi
    # ne change alors que le jour, pas la semaine — sinon l'ordre pédagogique
    # refuse d'abord et masque le contrôle qu'on veut éprouver.
    semaine_ferie, _ = _semaine_jour_du(ARMISTICE, calendrier)
    etat.sessions = [seance]
    etat.sessions_by_id = {seance.id: seance}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="seance", week=semaine_ferie, day=0, slot=0, course_code="WR104",
            group_ids=["but1-promo"], teacher_codes=["MMA"],
        )
    ]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = calendrier
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.config_dir = ROOT / "data" / "config"

    c = TestClient(app)
    creer_compte_actif_et_connecter(c)
    yield c

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


# --------------------------------------------------------------------------


def test_le_calendrier_connait_bien_l_armistice() -> None:
    """Prérequis : si le férié n'était pas déclaré, le reste n'aurait pas de
    sens — et le vrai problème serait dans les données."""
    assert ARMISTICE in build_default_calendar_2026_2027().holidays


def test_la_verification_refuse_un_jour_ferie(client) -> None:
    """LE test du bug : ce déplacement était accepté sans un mot."""
    etat = get_state()
    semaine, jour = _semaine_jour_du(ARMISTICE, etat.calendar)
    corps = client.post(
        "/placements/seance/validate", json={"week": semaine, "day": jour, "slot": 0}
    ).json()
    assert corps["valid"] is False
    assert any("férié" in m.lower() for m in corps["hard_conflicts"]), corps["hard_conflicts"]


def test_un_jour_ferie_n_est_pas_negociable(client) -> None:
    """L'IUT est fermé : ce n'est pas un arbitrage pédagogique qu'un humain
    pourrait trancher, donc pas de bouton « Forcer »."""
    etat = get_state()
    semaine, jour = _semaine_jour_du(ARMISTICE, etat.calendar)
    corps = client.post(
        "/placements/seance/validate", json={"week": semaine, "day": jour, "slot": 0}
    ).json()
    assert any("férié" in m.lower() for m in corps["blocking_conflicts"]), corps["blocking_conflicts"]


def test_le_deplacement_reel_est_refuse_meme_en_forcant(client) -> None:
    etat = get_state()
    semaine, jour = _semaine_jour_du(ARMISTICE, etat.calendar)
    reponse = client.patch(
        "/placements/seance", json={"week": semaine, "day": jour, "slot": 0, "force": True}
    )
    assert reponse.status_code == 409
    assert "férié" in reponse.text.lower()


def test_le_motif_nomme_le_jour(client) -> None:
    """« Conflit » ne dit rien ; « Armistice » dit tout."""
    etat = get_state()
    semaine, jour = _semaine_jour_du(ARMISTICE, etat.calendar)
    corps = client.post(
        "/placements/seance/validate", json={"week": semaine, "day": jour, "slot": 0}
    ).json()
    motif = next(m for m in corps["hard_conflicts"] if "férié" in m.lower())
    assert "11/11/2026" in motif or "2026-11-11" in motif


def test_un_jour_ouvre_reste_accepte(client) -> None:
    """Le garde-fou ne doit pas fermer les jours ordinaires."""
    etat = get_state()
    semaine, jour = _semaine_jour_du(date(2026, 11, 10), etat.calendar)  # mardi de la même semaine
    corps = client.post(
        "/placements/seance/validate", json={"week": semaine, "day": jour, "slot": 0}
    ).json()
    assert not any("férié" in m.lower() for m in corps["hard_conflicts"]), corps["hard_conflicts"]


def test_le_planning_reel_ne_contient_aucun_cours_un_jour_ferie() -> None:
    """Contrôle sur les VRAIES données : c'est ce test qui aurait attrapé le
    11 novembre avant que Kyllian ne le voie."""
    import json

    from cal_iut.calendar.academic import semester_week_offset

    chemin = ROOT / "data" / "generated" / "timetable.json"
    if not chemin.exists():
        pytest.skip("pas de planning généré")
    calendrier = build_default_calendar_2026_2027()
    offset = semester_week_offset(calendrier, "S1")
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    placements = donnees if isinstance(donnees, list) else donnees.get("placements", [])
    fautifs = []
    for p in placements:
        d = calendrier.week_day_to_date(offset + p["week"], p["day"])
        if d in calendrier.holidays:
            fautifs.append((p["session_id"], d))
    assert not fautifs, f"cours posés un jour férié : {fautifs[:5]}"
