"""Sauvegardes JSON datées — item B du contrat verrouillé (22/09/2026).

Todo : « Avoir un fichier JSON backup des semaines et séances placées à une
date précise ». Deux volets testés séparément :

1. Le MODULE (`api/sauvegardes.py`) en isolation — contenu de l'instantané,
   une sauvegarde par jour calendaire (jamais deux, jamais aucune erreur
   remontée), purge à 90 jours, validation stricte du nom de fichier.
2. Les ENDPOINTS (`api/main.py`) — rôle admin requis, téléchargement,
   404 propre sur une date absente ou invalide (jamais de traversée de
   chemin).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import custom_sessions, sauvegardes, session_overrides
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

# Date CALENDAIRE réelle (jamais un horodatage UTC) : un fichier par JOUR au
# sens du calendrier académique — calculée une fois, réutilisée partout ici
# plutôt que `date.today()` répété (même exception que `sauvegardes.
# _aujourdhui`, pour la même raison).
AUJOURDHUI = date.today()  # noqa: DTZ011


def _seance(sid: str = "s1") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["MRI"], duration_slots=1,
    )


def _place(s: SessionToPlace, week: int = 3, day: int = 1, slot: int = 2) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
        room_id="H.007", room_label="H.007",
    )


class _EtatFictif:
    """Juste assez de `state` pour `instantane()` — pas un vrai `AppState`
    (pas de base de données, pas de groupes) : `instantane` ne lit QUE
    `calendar`, `timetable`, `sessions_by_id`, `current_run_id`."""

    def __init__(self) -> None:
        self.calendar = build_default_calendar_2026_2027()
        self.timetable: list[PlacedSessionWithRoom] = []
        self.sessions_by_id: dict[str, SessionToPlace] = {}
        self.current_run_id: int | None = 42


@pytest.fixture
def etat_fictif() -> _EtatFictif:
    return _EtatFictif()


# `conftest.py::_fichiers_etat_isoles` (autouse) redirige déjà `sauvegardes.
# SAUVEGARDES_DIR`, `custom_sessions._path` et `session_overrides._path` vers
# un `tmp_path` — jamais le vrai `data/state/` ici, sans rien à refaire.


# --------------------------------------------------------------------------
# Le module — contenu de l'instantané
# --------------------------------------------------------------------------


def test_instantane_porte_le_format_et_les_placements(etat_fictif) -> None:
    s = _seance()
    etat_fictif.sessions_by_id[s.id] = s
    etat_fictif.timetable.append(_place(s, week=3, day=1, slot=2))

    corps = sauvegardes.instantane(etat_fictif)

    assert corps["format"] == "cal-iut-sauvegarde/1"
    assert corps["run_id"] == 42
    assert corps["genere_le"]  # ISO, non vide
    assert len(corps["placements"]) == 1
    p = corps["placements"][0]
    assert p == {
        "session_id": "s1", "course_code": "WR101", "session_type": "TD",
        "group_ids": ["but1-td-ab"], "teacher_codes": ["MRI"],
        "week": 3, "day": 1, "slot": 2, "duration_slots": 1,
        "room_id": "H.007", "room_label": "H.007", "locked": False,
    }


def test_instantane_liste_les_semaines_depuis_le_calendrier(etat_fictif) -> None:
    corps = sauvegardes.instantane(etat_fictif)
    assert corps["semaines"], "aucune semaine dans l'instantané"
    premiere = corps["semaines"][0]
    assert premiere["weekIndex"] == 0
    assert premiere["monday"] == etat_fictif.calendar.teaching_mondays[0].isoformat()
    assert "Semaine" in premiere["label"]


def test_instantane_inclut_les_seances_personnalisees_et_les_retouches(etat_fictif) -> None:
    perso = _seance("perso")
    perso.metadata["custom_session"] = True
    custom_sessions.add_custom_session(perso)
    session_overrides.upsert_overlay("s1", {"teacher_codes": ["JSA"]})

    corps = sauvegardes.instantane(etat_fictif)

    assert len(corps["seances_personnalisees"]) == 1
    assert corps["seances_personnalisees"][0]["id"] == "perso"
    assert corps["retouches"] == {"s1": {"teacher_codes": ["JSA"]}}


def test_instantane_ne_modifie_rien_sur_le_disque(etat_fictif) -> None:
    """Lecture seule — un backup ne doit jamais avoir d'effet de bord."""
    assert not custom_sessions._path().exists()
    sauvegardes.instantane(etat_fictif)
    assert not custom_sessions._path().exists()


# --------------------------------------------------------------------------
# Une sauvegarde par jour, jamais d'exception remontée
# --------------------------------------------------------------------------


def test_prendre_maintenant_ecrit_le_fichier_du_jour(etat_fictif) -> None:
    cible = sauvegardes.prendre_maintenant(etat_fictif)
    assert cible.exists()
    assert cible.name == f"cal-iut-{AUJOURDHUI.isoformat()}.json"
    contenu = json.loads(cible.read_text(encoding="utf-8"))
    assert contenu["format"] == "cal-iut-sauvegarde/1"


def test_snapshot_si_necessaire_ne_prend_qu_un_instantane_par_jour(etat_fictif) -> None:
    sauvegardes.snapshot_si_necessaire(etat_fictif)
    assert sauvegardes.deja_pris_aujourdhui() is True
    premier = sauvegardes.chemin(AUJOURDHUI.isoformat()).read_text(encoding="utf-8")

    # L'état change ENTRE les deux appels : si un second instantané était
    # pris, le contenu sur disque changerait.
    s = _seance("nouvelle")
    etat_fictif.sessions_by_id[s.id] = s
    etat_fictif.timetable.append(_place(s))
    sauvegardes.snapshot_si_necessaire(etat_fictif)

    second = sauvegardes.chemin(AUJOURDHUI.isoformat()).read_text(encoding="utf-8")
    assert second == premier, "un deuxième écrit le même jour n'aurait pas dû reprendre l'instantané"


def test_prendre_maintenant_explicite_ecrase_meme_le_meme_jour(etat_fictif) -> None:
    sauvegardes.prendre_maintenant(etat_fictif)
    s = _seance("nouvelle")
    etat_fictif.sessions_by_id[s.id] = s
    etat_fictif.timetable.append(_place(s))
    sauvegardes.prendre_maintenant(etat_fictif)

    contenu = json.loads(sauvegardes.chemin(AUJOURDHUI.isoformat()).read_text(encoding="utf-8"))
    assert len(contenu["placements"]) == 1
    assert contenu["placements"][0]["session_id"] == "nouvelle"


def test_snapshot_si_necessaire_ne_leve_jamais(etat_fictif, monkeypatch) -> None:
    def _casse(state: object) -> Path:
        raise RuntimeError("disque plein")

    monkeypatch.setattr(sauvegardes, "prendre_maintenant", _casse)
    sauvegardes.snapshot_si_necessaire(etat_fictif)  # ne doit pas lever
    assert sauvegardes.deja_pris_aujourdhui() is False


# --------------------------------------------------------------------------
# Rétention 90 jours
# --------------------------------------------------------------------------


def _ecrire_jour(jour: date, placements: int = 0) -> None:
    sauvegardes.SAUVEGARDES_DIR.mkdir(parents=True, exist_ok=True)
    contenu = {
        "format": "cal-iut-sauvegarde/1", "genere_le": "2026-01-01T00:00:00+00:00", "run_id": None,
        "semaines": [], "placements": [{}] * placements, "seances_personnalisees": [], "retouches": {},
    }
    sauvegardes.chemin(jour.isoformat()).write_text(json.dumps(contenu), encoding="utf-8")


def test_purger_anciennes_supprime_ce_qui_depasse_90_jours() -> None:
    aujourdhui = date(2026, 9, 22)
    recent = aujourdhui - timedelta(days=10)
    limite = aujourdhui - timedelta(days=90)
    trop_vieux = aujourdhui - timedelta(days=91)
    for j in (recent, limite, trop_vieux):
        _ecrire_jour(j)

    supprimes = sauvegardes.purger_anciennes(reference=aujourdhui)

    assert supprimes == [trop_vieux.isoformat()]
    assert sauvegardes.chemin(recent.isoformat()).exists()
    assert sauvegardes.chemin(limite.isoformat()).exists()
    assert not sauvegardes.chemin(trop_vieux.isoformat()).exists()


def test_nom_fichier_valide_refuse_toute_traversee() -> None:
    assert sauvegardes.nom_fichier_valide("2026-09-22") is True
    assert sauvegardes.nom_fichier_valide("../../etc/passwd") is False
    assert sauvegardes.nom_fichier_valide("..") is False
    assert sauvegardes.nom_fichier_valide("2026-13-99") is False
    assert sauvegardes.nom_fichier_valide("") is False


def test_lister_trie_du_plus_recent_et_compte_les_placements() -> None:
    _ecrire_jour(date(2026, 9, 20), placements=2)
    _ecrire_jour(date(2026, 9, 22), placements=5)
    _ecrire_jour(date(2026, 9, 21), placements=0)

    corps = sauvegardes.lister()

    assert [e["date"] for e in corps] == ["2026-09-22", "2026-09-21", "2026-09-20"]
    assert corps[0]["nb_placements"] == 5
    assert corps[2]["nb_placements"] == 2
    assert all(e["taille_octets"] > 0 for e in corps)


def test_lister_est_vide_sans_aucune_sauvegarde() -> None:
    assert sauvegardes.lister() == []


# --------------------------------------------------------------------------
# Les endpoints
# --------------------------------------------------------------------------


client = TestClient(app)


@pytest.fixture
def etat_reel_minimal():
    """Un `AppState` réel minimal, pour les endpoints (qui appellent
    `get_state()` en interne, pas `etat_fictif`)."""
    etat = get_state()
    ancien = {"timetable": etat.timetable, "sessions_by_id": etat.sessions_by_id, "calendar": etat.calendar}
    etat.timetable = []
    etat.sessions_by_id = {}
    etat.calendar = build_default_calendar_2026_2027()
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_endpoints_refusent_un_anonyme(db_isole, etat_reel_minimal) -> None:
    client.cookies.clear()
    assert client.get("/sauvegardes").status_code in (401, 403)
    assert client.post("/sauvegardes").status_code in (401, 403)
    assert client.get("/sauvegardes/2026-09-22").status_code in (401, 403)


def test_endpoints_refusent_un_role_edit(db_isole, etat_reel_minimal) -> None:
    creer_compte_actif_et_connecter(client, role="edit")
    assert client.get("/sauvegardes").status_code == 403
    client.cookies.clear()


def test_get_sauvegardes_liste_pour_un_admin(db_isole, etat_reel_minimal) -> None:
    creer_compte_actif_et_connecter(client, role="admin")
    _ecrire_jour(date(2026, 9, 22), placements=1)

    corps = client.get("/sauvegardes").json()

    assert corps["sauvegardes"][0]["date"] == "2026-09-22"
    assert corps["sauvegardes"][0]["nb_placements"] == 1
    client.cookies.clear()


def test_post_sauvegardes_cree_celle_du_jour(db_isole, etat_reel_minimal) -> None:
    creer_compte_actif_et_connecter(client, role="admin")
    s = _seance()
    etat_reel_minimal.sessions_by_id[s.id] = s
    etat_reel_minimal.timetable.append(_place(s))

    reponse = client.post("/sauvegardes")

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["date"] == AUJOURDHUI.isoformat()
    assert corps["nb_placements"] == 1
    client.cookies.clear()


def test_get_sauvegarde_par_date_telecharge_le_fichier(db_isole, etat_reel_minimal) -> None:
    creer_compte_actif_et_connecter(client, role="admin")
    _ecrire_jour(date(2026, 9, 22), placements=3)

    reponse = client.get("/sauvegardes/2026-09-22")

    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"].startswith("application/json")
    assert "attachment" in reponse.headers["content-disposition"]
    assert reponse.json()["format"] == "cal-iut-sauvegarde/1"
    client.cookies.clear()


def test_get_sauvegarde_par_date_404_si_absente(db_isole, etat_reel_minimal) -> None:
    creer_compte_actif_et_connecter(client, role="admin")
    assert client.get("/sauvegardes/2026-01-01").status_code == 404
    client.cookies.clear()


def test_get_sauvegarde_refuse_un_format_invalide_sans_toucher_le_disque(db_isole, etat_reel_minimal) -> None:
    creer_compte_actif_et_connecter(client, role="admin")
    for cible in ("..", "pas-une-date", "2026-13-99"):
        assert client.get(f"/sauvegardes/{cible}").status_code == 404
    client.cookies.clear()
