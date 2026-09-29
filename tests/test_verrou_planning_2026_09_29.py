"""Verrou d'écriture du planning (audit 29/09/2026, P1-4).

- toute route qui modifie le planning tourne sous le même verrou réentrant ;
- une écriture attend qu'une autre soit finie (« valider puis écrire » est
  atomique) ;
- le lissage et le MCP `apply` tiennent le verrou sur tout leur lot ;
- la régénération calcule sans le verrou et abandonne, sans rien écrire, si
  sa portée a bougé pendant le calcul ;
- solve, régénération et lissage ne tournent jamais en même temps.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from cal_iut.api import main
from cal_iut.api.regen import RegenError, fusionner, positions_portee
from cal_iut.api.verrou import ecriture_planning, verrou_planning
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROUTES_ECRITURE = {
    ("PATCH", "/placements/{session_id}"),
    ("PATCH", "/placements/{session_id}/seance"),
    ("POST", "/placements/{session_id}/deposer"),
    ("POST", "/placements/echanger"),
    ("PATCH", "/placements/{session_id}/salle"),
    ("POST", "/placements/{session_id}/placer"),
    ("POST", "/placements/personnalisees"),
    ("POST", "/placements/evenements"),
    ("PATCH", "/placements/personnalisees/{session_id}"),
    ("DELETE", "/placements/personnalisees/{session_id}"),
    ("POST", "/placements/{session_id}/valider"),
    ("DELETE", "/placements/{session_id}"),
    ("POST", "/placements/lissage/{job_id}/appliquer"),
    ("POST", "/placements/completer"),
    ("POST", "/ingest"),
}

_CODE_VERROU = ecriture_planning(lambda: None).__code__


def _pl(sid: str, week: int, day: int, slot: int, room: str | None = "h101") -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=sid, week=week, day=day, slot=slot, course_code="WR" + sid,
        group_ids=["g"], teacher_codes=["ABC"], room_id=room, room_label=room,
    )


def test_toutes_les_routes_d_ecriture_du_planning_prennent_le_verrou():
    trouvees = set()
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for methode in route.methods:
            if (methode, route.path) in ROUTES_ECRITURE:
                assert route.endpoint.__code__ is _CODE_VERROU, f"{methode} {route.path} sans verrou"
                trouvees.add((methode, route.path))
    assert trouvees == ROUTES_ECRITURE


def test_une_ecriture_attend_la_fin_de_la_precedente():
    tenu = threading.Event()
    relacher = threading.Event()
    fini = threading.Event()

    def premiere() -> None:
        with verrou_planning:
            tenu.set()
            relacher.wait(5)

    @ecriture_planning
    def seconde() -> None:
        fini.set()

    a = threading.Thread(target=premiere)
    a.start()
    assert tenu.wait(5)
    b = threading.Thread(target=seconde)
    b.start()
    assert not fini.wait(0.2), "la seconde écriture n'a pas attendu la première"
    relacher.set()
    assert fini.wait(5)
    a.join(5)
    b.join(5)


def test_le_verrou_est_reentrant():
    """`creer_seance_personnalisee` appelle `placer_seance`, le lissage
    appelle `move_session` : le même thread doit reprendre le verrou."""
    resultat: list[str] = []

    @ecriture_planning
    def interne() -> str:
        return "ok"

    @ecriture_planning
    def externe() -> None:
        resultat.append(interne())

    t = threading.Thread(target=externe)
    t.start()
    t.join(5)
    assert resultat == ["ok"]


def test_le_lissage_tient_le_verrou_pendant_tous_ses_deplacements(monkeypatch):
    from cal_iut.api import lissage

    vus: list[bool] = []

    def faux_move(session_id, body):
        vus.append(verrou_planning._is_owned())

    monkeypatch.setattr(main, "move_session", faux_move)
    etat = SimpleNamespace(
        groups=[SimpleNamespace(id="g", parcours="P")],
        timetable=[_pl("A", 5, 0, 1), _pl("B", 5, 0, 2)],
        sessions_by_id={},
    )
    proposition = lissage.Proposition(
        parcours="P", statut="OPTIMAL", message="", semaines=[5], avant=[], apres=[],
        duree_s=0.0, poids=lissage.PoidsLissage(),
        deplacements=[
            lissage.Deplacement(session_id="A", course_code="WRA", enseignants=[], de=(5, 0, 1), vers=(5, 1, 1)),
            lissage.Deplacement(session_id="B", course_code="WRB", enseignants=[], de=(5, 0, 2), vers=(5, 1, 2)),
        ],
    )
    resultat = lissage.appliquer(etat, proposition)
    assert resultat.echec is None
    assert vus == [True, True]


def test_le_mcp_apply_tient_le_verrou_sur_tout_le_lot(monkeypatch):
    from cal_iut.mcp import tools

    vus: list[bool] = []
    monkeypatch.setattr(tools, "_executer_item", lambda item: vus.append(verrou_planning._is_owned()))
    monkeypatch.setattr(tools.mcp_journal, "append", lambda entree: None)
    ops = [{"op": "move", "session_id": "A"}, {"op": "move", "session_id": "B"}]
    assert tools.apply(confirm=True, ops=ops)["ok"] is True
    assert vus == [True, True]


# ── Régénération : calcul hors verrou, fusion sous verrou ──────────────────


class _RepoFactice:
    def __init__(self) -> None:
        self.ecrits: list = []

    def upsert_current_placements(self, run_id, rows) -> None:
        self.ecrits.append(rows)

    def save_correction(self, *args) -> None:
        self.ecrits.append(args)


def test_la_regeneration_abandonne_si_sa_portee_a_bouge_pendant_le_calcul():
    etat = SimpleNamespace(timetable=[_pl("A", 5, 0, 1), _pl("B", 5, 0, 2), _pl("Z", 6, 0, 0)], current_run_id=1)
    depart = positions_portee(etat.timetable, [5])
    # Pendant le calcul, quelqu'un déplace B à la main (même semaine).
    etat.timetable = [_pl("A", 5, 0, 1), _pl("B", 5, 3, 4), _pl("Z", 6, 0, 0)]
    avant = list(etat.timetable)
    repo = _RepoFactice()
    with pytest.raises(RegenError, match="modifié pendant le calcul"):
        fusionner(etat, repo, [5], depart, [_pl("A", 5, 2, 2), _pl("B", 5, 2, 3)])
    assert etat.timetable == avant
    assert repo.ecrits == []


def test_la_regeneration_abandonne_si_une_seance_a_ete_posee_dans_la_portee():
    etat = SimpleNamespace(timetable=[_pl("A", 5, 0, 1)], current_run_id=None)
    depart = positions_portee(etat.timetable, [5])
    etat.timetable = [*etat.timetable, _pl("N", 5, 4, 0)]
    with pytest.raises(RegenError):
        fusionner(etat, _RepoFactice(), [5], depart, [_pl("A", 5, 2, 2)])


def test_la_regeneration_ecrit_si_rien_n_a_bouge_et_rend_les_seances_deplacees():
    etat = SimpleNamespace(timetable=[_pl("A", 5, 0, 1), _pl("B", 5, 0, 2), _pl("Z", 6, 0, 0)], current_run_id=1)
    depart = positions_portee(etat.timetable, [5])
    # Une écriture HORS portée pendant le calcul ne gêne pas.
    etat.timetable = [_pl("A", 5, 0, 1), _pl("B", 5, 0, 2), _pl("Z", 6, 1, 1)]
    repo = _RepoFactice()
    deplacees = fusionner(etat, repo, [5], depart, [_pl("A", 5, 0, 1), _pl("B", 5, 2, 3)])
    assert deplacees == ["B"]
    assert {p.session_id: (p.week, p.day, p.slot) for p in etat.timetable} == {
        "A": (5, 0, 1), "B": (5, 2, 3), "Z": (6, 1, 1),
    }
    assert repo.ecrits


# ── Exclusion mutuelle solve / régénération / lissage ──────────────────────


@pytest.fixture
def jobs_propres(monkeypatch):
    monkeypatch.setattr(main, "_current_job", None)
    monkeypatch.setattr(main, "_current_regen_job", None)
    monkeypatch.setattr(main, "_current_lissage_job", None)
    monkeypatch.setattr(main, "get_state", lambda: SimpleNamespace(sessions=[object()], timetable=[object()]))


@pytest.mark.parametrize("en_cours", ["regen", "lissage"])
def test_solve_refuse_pendant_une_regeneration_ou_un_lissage(jobs_propres, monkeypatch, en_cours):
    if en_cours == "regen":
        monkeypatch.setattr(main, "_current_regen_job", main.RegenJob(job_id="r", status="running"))
    else:
        monkeypatch.setattr(main, "_current_lissage_job", main.LissageJob(job_id="l", status="running", parcours="P"))
    for route in (main.solve, main.solve_async):
        with pytest.raises(HTTPException) as exc:
            route(main.SolveRequest())
        assert exc.value.status_code == 409


def test_regeneration_et_lissage_refuses_pendant_un_solve(jobs_propres, monkeypatch):
    from cal_iut.api.schemas import LissageRequest, RegenRequest

    monkeypatch.setattr(main, "_current_job", main.SolveJob(job_id="s", status="running"))
    with pytest.raises(HTTPException) as exc:
        main.regen_week(RegenRequest(week=10))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        main.lancer_lissage(LissageRequest())
    assert exc.value.status_code == 409


def test_un_solve_synchrone_bloque_la_regeneration_pendant_son_calcul(jobs_propres, monkeypatch):
    from cal_iut.api.schemas import RegenRequest

    refus: list[int] = []

    def faux_solve(body):
        try:
            main.regen_week(RegenRequest(week=10))
        except HTTPException as exc:
            refus.append(exc.status_code)
        return "resultat"

    monkeypatch.setattr(main, "_solve_and_persist", faux_solve)
    assert main.solve(main.SolveRequest()) == "resultat"
    assert refus == [409]
    assert main._current_job.status == "done"
