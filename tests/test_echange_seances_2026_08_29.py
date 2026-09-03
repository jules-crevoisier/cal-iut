"""Échanger deux séances de place, et savoir ce qui est forçable.

Deux demandes du 29/08/2026, liées :

1. « si l'on fait un glisser-déposer d'un cours sur un autre, cela nous
   propose un échange de cours tout en vérifiant pareil » — d'où
   `POST /placements/echanger`.
2. « on veut bien afficher les contraintes enseignantes si cela les
   enfreint » — d'où la distinction entre conflits FORÇABLES et conflits
   BLOQUANTS dans la réponse de validation.

Le point 2 n'est pas cosmétique. Un verrou institutionnel (PAC/SAE/fin de
semestre) n'est PAS contournable par forçage (`move_session` le refuse même
avec `force=True`) — il faut donc que la validation dise LESQUELS des
conflits sont définitifs, pas seulement qu'il y en a. L'indisponibilité
enseignant déclarée, elle, est devenue contournable via `force` depuis le
03/09/2026 (retour Kyllian Bresson : « des fois ils acceptent de faire
cours quand même ») — même traitement que l'ordre pédagogique.

Sur l'échange, le piège central est l'état intermédiaire : pendant qu'on
échange A et B, chacun doit être jugé sur la position LIBÉRÉE par l'autre.
Une vérification naïve verrait systématiquement les deux séances en conflit
l'une avec l'autre et refuserait tout échange, y compris parfaitement
valide.
"""

from __future__ import annotations

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

SEMAINE = 10  # librement modifiable dans le calendrier 2026-2027


def _seance(sid, groupe="but1-td-ab", prof="MRI", duree=1, code="WR101") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="Cours", semestre="S1", parcours="BUT1",
        annee="BUT1", session_type=SessionType.TD, sequence_order=1,
        group_ids=[groupe], teacher_codes=[prof], duration_slots=duree,
    )


def _place(s: SessionToPlace, day: int, slot: int, week: int = SEMAINE) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
    )


@pytest.fixture
def monter(db_isole):
    """Rend une fonction qui monte un état applicatif à partir de séances déjà
    placées, pour que chaque test décrive exactement la situation qu'il teste."""
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "teacher_duos", "corrections",
            "courses", "config_dir",
        )
    }
    clients: list[TestClient] = []

    def _monter(paires):
        etat.sessions = [s for s, _ in paires]
        etat.sessions_by_id = {s.id: s for s, _ in paires}
        etat.timetable = [p for _, p in paires]
        etat.groups = GROUPES
        etat.rooms = []
        etat.calendar = build_default_calendar_2026_2027()
        etat.current_run_id = None
        etat.teacher_availability = []
        etat.teacher_duos = []
        etat.corrections = []
        etat.courses = []
        etat.config_dir = ROOT / "data" / "config"
        c = TestClient(app)
        creer_compte_actif_et_connecter(c)
        clients.append(c)
        return c

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _deux_seances_du_meme_groupe():
    """A lundi 8h, B mardi 14h — même groupe, même enseignant : l'échange le
    plus courant, et celui qu'une vérification naïve refuserait."""
    a, b = _seance("a", code="WR101"), _seance("b", code="WR106")
    return [(a, _place(a, 0, 0)), (b, _place(b, 1, 3))]


# --------------------------------------------------------------------------
# L'échange
# --------------------------------------------------------------------------


def test_deux_seances_echangent_bien_leurs_places(monter) -> None:
    client = monter(_deux_seances_du_meme_groupe())
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    assert reponse.status_code == 200, reponse.text
    par_id = {p["session_id"]: p for p in reponse.json()["placements"]}
    assert (par_id["a"]["day"], par_id["a"]["slot"]) == (1, 3)
    assert (par_id["b"]["day"], par_id["b"]["slot"]) == (0, 0)


def test_l_echange_n_est_pas_refuse_a_cause_des_deux_seances_elles_memes(monter) -> None:
    """LE piège : chacune doit être jugée sur la place LIBÉRÉE par l'autre.
    Sans cela, tout échange entre deux séances du même groupe est impossible,
    puisque chacune voit l'autre à la place qu'elle vise."""
    client = monter(_deux_seances_du_meme_groupe())
    assert client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"}).status_code == 200


def test_l_echange_traverse_les_semaines(monter) -> None:
    a, b = _seance("a"), _seance("b", code="WR106")
    client = monter([(a, _place(a, 0, 0, week=SEMAINE)), (b, _place(b, 2, 4, week=SEMAINE + 3))])
    par_id = {
        p["session_id"]: p
        for p in client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"}).json()["placements"]
    }
    assert (par_id["a"]["week"], par_id["a"]["day"], par_id["a"]["slot"]) == (SEMAINE + 3, 2, 4)
    assert (par_id["b"]["week"], par_id["b"]["day"], par_id["b"]["slot"]) == (SEMAINE, 0, 0)


def test_un_echange_qui_creerait_un_conflit_avec_un_TIERS_est_refuse(monter) -> None:
    """Le vrai risque : A et B s'échangent proprement, mais la place d'arrivée
    de A est déjà occupée par C pour le même groupe."""
    a, b = _seance("a"), _seance("b", code="WR106")
    c = _seance("c", code="WR108")
    client = monter([
        (a, _place(a, 0, 0)),
        (b, _place(b, 1, 3)),
        (c, _place(c, 0, 0)),  # C occupe déjà la place que B recevrait
    ])
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    assert reponse.status_code == 409
    assert any("WR108" in m for m in reponse.json()["detail"]["hard_conflicts"])


def test_un_conflit_de_ressource_reste_forcable(monter) -> None:
    a, b = _seance("a"), _seance("b", code="WR106")
    c = _seance("c", code="WR108")
    client = monter([(a, _place(a, 0, 0)), (b, _place(b, 1, 3)), (c, _place(c, 0, 0))])
    forcee = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b", "force": True})
    assert forcee.status_code == 200, forcee.text


def test_echanger_une_seance_avec_elle_meme_est_refuse(monter) -> None:
    """Sinon l'appel « réussit » sans rien faire, ce qui masque un bug côté
    interface (mauvaise cible de dépôt) au lieu de le signaler."""
    client = monter(_deux_seances_du_meme_groupe())
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "a"})
    assert reponse.status_code == 400


def test_echanger_avec_une_seance_inconnue_donne_un_404(monter) -> None:
    client = monter(_deux_seances_du_meme_groupe())
    assert client.post("/placements/echanger", json={"session_a": "a", "session_b": "zz"}).status_code == 404


def test_une_seance_verrouillee_ne_s_echange_pas(monter) -> None:
    paires = _deux_seances_du_meme_groupe()
    paires[1][0].locked = True
    client = monter(paires)
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    assert reponse.status_code == 409
    assert "verrouill" in reponse.text.lower()


def test_les_durees_differentes_sont_prises_en_compte(monter) -> None:
    """Un bloc de 3h qui prend la place d'une séance d'1h30 déborde sur le
    créneau suivant : si ce créneau est occupé pour le même groupe, l'échange
    doit être refusé — c'est exactement le défaut trouvé le 29/08 sur la
    validation simple."""
    a = _seance("a", duree=2, code="WR101")   # 3h, lundi 8h -> occupe 0 et 1
    b = _seance("b", code="WR106")            # 1h30, mardi 14h
    voisine = _seance("voisine", code="WR108")
    client = monter([
        (a, _place(a, 0, 0)),
        (b, _place(b, 1, 3)),
        (voisine, _place(voisine, 1, 4)),  # juste après la place que A recevrait
    ])
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    assert reponse.status_code == 409
    assert any("WR108" in m for m in reponse.json()["detail"]["hard_conflicts"])


def test_l_echange_est_journalise_comme_deux_corrections(monter) -> None:
    """La boucle de réapprentissage des poids lit ces corrections : un échange
    non journalisé serait deux décisions humaines perdues."""
    client = monter(_deux_seances_du_meme_groupe())
    client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    corrections = get_state().corrections
    assert {c["session_id"] for c in corrections} == {"a", "b"}


def test_rien_n_est_applique_quand_l_echange_est_refuse(monter) -> None:
    """Un échange à moitié appliqué laisserait le planning dans un état que
    personne n'a demandé — pire que le refus."""
    a, b = _seance("a"), _seance("b", code="WR106")
    c = _seance("c", code="WR108")
    client = monter([(a, _place(a, 0, 0)), (b, _place(b, 1, 3)), (c, _place(c, 0, 0))])
    client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    positions = {p.session_id: (p.day, p.slot) for p in get_state().timetable}
    assert positions["a"] == (0, 0) and positions["b"] == (1, 3)


# --------------------------------------------------------------------------
# Forçable ou non : ce que l'interface a besoin de savoir
# --------------------------------------------------------------------------


def _avec_indisponibilite(monter, jour: int, creneau: int):
    from cal_iut.models.entities import TeacherAvailability

    client = monter(_deux_seances_du_meme_groupe())
    get_state().teacher_availability = [
        TeacherAvailability(teacher_code="MRI", forbidden_slots=[(jour, creneau)])
    ]
    return client


def test_une_indispo_enseignant_est_signalee_mais_forcable(monter) -> None:
    """Depuis le 03/09/2026 (retour Kyllian Bresson), une indisponibilité
    enseignant déclarée n'est plus dans `blocking_conflicts` : l'interface
    peut proposer « Forcer », le serveur l'acceptera (cf.
    `test_forcer_un_echange_sur_indisponibilite_enseignant_reussit`)."""
    client = _avec_indisponibilite(monter, jour=2, creneau=0)
    corps = client.post("/placements/a/validate", json={"week": SEMAINE, "day": 2, "slot": 0}).json()
    assert corps["valid"] is False
    assert corps["blocking_conflicts"] == []
    # Toujours présent dans la liste générale : rien ne disparaît de l'affichage.
    assert any("indisponible" in m for m in corps["hard_conflicts"])


def test_un_simple_conflit_de_ressource_n_est_PAS_bloquant(monter) -> None:
    """La distinction doit rester fine : un conflit de groupe ou de salle a
    parfois une bonne raison ponctuelle d'être forcé."""
    client = monter(_deux_seances_du_meme_groupe())
    corps = client.post("/placements/a/validate", json={"week": SEMAINE, "day": 1, "slot": 3}).json()
    assert corps["valid"] is False
    assert corps["hard_conflicts"], "le conflit avec B doit bien être signalé"
    assert corps["blocking_conflicts"] == []


def test_le_verrou_de_semaine_n_est_pas_bloquant(monter) -> None:
    """Il a été rendu contournable le 29/08 : l'interface doit donc continuer
    à proposer le forçage."""
    client = monter(_deux_seances_du_meme_groupe())
    corps = client.post("/placements/a/validate", json={"week": 0, "day": 1, "slot": 1}).json()
    assert any("non modifiable" in m for m in corps["hard_conflicts"])
    assert corps["blocking_conflicts"] == []


def test_un_deplacement_valide_n_a_aucun_conflit_bloquant(monter) -> None:
    client = monter(_deux_seances_du_meme_groupe())
    corps = client.post("/placements/a/validate", json={"week": SEMAINE, "day": 3, "slot": 0}).json()
    assert corps["valid"] is True
    assert corps["blocking_conflicts"] == []


def test_l_echange_refuse_dit_que_l_indispo_n_est_pas_bloquante(monter) -> None:
    """Même information des deux côtés : l'interface décide d'offrir « Forcer »
    de la même façon, qu'il s'agisse d'un déplacement ou d'un échange."""
    client = _avec_indisponibilite(monter, jour=1, creneau=3)
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b"})
    assert reponse.status_code == 409
    detail = reponse.json()["detail"]
    assert any("indisponible" in m for m in detail["hard_conflicts"])
    assert detail["blocking_conflicts"] == []


def test_forcer_un_echange_sur_indisponibilite_enseignant_reussit(monter) -> None:
    """Retour Kyllian Bresson (03/09/2026) : « des fois ils acceptent de faire
    cours quand même » — `force=True` doit donc débloquer, à la différence
    d'un verrou institutionnel (PAC/SAE), qui lui reste refusé même forcé."""
    client = _avec_indisponibilite(monter, jour=1, creneau=3)
    reponse = client.post("/placements/echanger", json={"session_a": "a", "session_b": "b", "force": True})
    assert reponse.status_code == 200, reponse.text
