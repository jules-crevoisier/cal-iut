"""`GET /celcat/comparaison` — la vue « Celcat vs cal-iut », côté serveur.

L'endpoint fait trois choses que l'écran ne doit pas avoir à refaire :

1. il convertit l'indice de semaine cal-iut en indice `weeks` Celcat (les
   deux ne coïncident pas : la semaine 1 du planning est l'indice 3 chez
   Celcat). `comparaison.comparer` EXIGE les deux justement pour que cette
   conversion soit faite par qui détient le calendrier ;

2. il rapproche les séances avec les règles déjà testées
   (`ops.correspond_live`, `lecture.meme_creneau`) plutôt qu'une
   réimplémentation en TypeScript qui divergerait ;

3. il dit d'OÙ vient la comparaison — l'âge du relevé. Comparer contre un
   instantané de trois heures en le présentant comme l'état courant serait
   la même faute que celles réparées cette semaine : une information qui a
   l'air fraîche sans l'être.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import instantane
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

from conftest import creer_compte_actif_et_connecter

client = TestClient(app)

SEMAINE = 1  # lundi 2026-09-07 -> indice `weeks` 3 côté Celcat


def _ev(**kw):
    base = {
        "event_id": 1931709,
        "groupe": "BUT MMI S1 CM",
        "jour": 1,
        "heure_debut": "15:20",  # ce que Celcat stocke pour notre 15:30
        "heure_fin": "16:50",
        "salle": "Amphi 3 MMI",
        "categorie": "[CM]",
        "enseignant": "HUEZ Regis",
        "module": "WR116 Traitement Info",
        "semaine": 3,
        "protected": "N",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _etat(db_isole):
    creer_compte_actif_et_connecter(client, role="admin")
    etat = get_state()
    ancien = {
        k: getattr(etat, k)
        for k in ("sessions", "sessions_by_id", "timetable", "calendar", "current_run_id")
    }
    s = SessionToPlace(
        id="WR116-S1-CM-1", course_code="WR116", course_name="Traitement Info",
        semestre="S1", parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
        sequence_order=1, group_ids=[], teacher_codes=["RHU"],
    )
    etat.sessions = [s]
    etat.sessions_by_id = {s.id: s}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="WR116-S1-CM-1", week=SEMAINE, day=1, slot=4,
            course_code="WR116", group_ids=[], teacher_codes=["RHU"],
            room_id="amphi3", room_label="Amphi 3 MMI",
        )
    ]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_une_seance_avec_un_vrai_groupe_est_reconnue(_etat) -> None:
    """Le test « synchronisée » d'origine utilisait un placement SANS groupe :
    le critère de groupe ne s'appliquait donc pas, et il est resté vert
    pendant que la comparaison réelle rendait zéro « identique » sur toute
    une semaine (08/09/2026).

    Le nom Celcat d'un groupe s'écrit « BUT MMI S1 CM » : le semestre vient
    de la SÉANCE, pas du `Group` — qui n'a pas cet attribut. Le construire
    depuis le groupe donnait « BUT MMI  CM », qui ne correspond à rien.
    """
    from cal_iut.models.entities import Group

    etat = get_state()
    etat.groups = [
        Group(id="but1-promo", label="Promo BUT1", parcours="BUT1", annee="BUT1", kind="promo")
    ]
    etat.sessions_by_id["WR116-S1-CM-1"].group_ids = ["but1-promo"]
    etat.timetable[0].group_ids = ["but1-promo"]
    instantane.enregistrer([_ev(groupe="BUT MMI S1 CM")], groupes=["BUT MMI S1 CM"])

    lignes = client.get(f"/celcat/comparaison?semaine={SEMAINE}").json()["lignes"]
    assert [l["statut"] for l in lignes] == ["identique"], lignes


def test_refuse_un_anonyme() -> None:
    client.cookies.clear()
    assert client.get(f"/celcat/comparaison?semaine={SEMAINE}").status_code in (401, 403)


def test_une_seance_synchronisee_ressort_identique() -> None:
    """Le décalage de 9'21" ne doit pas peindre toutes les lignes en rouge."""
    instantane.enregistrer([_ev()], groupes=["BUT MMI S1 CM"])

    corps = client.get(f"/celcat/comparaison?semaine={SEMAINE}").json()
    assert [l["statut"] for l in corps["lignes"]] == ["identique"]


def test_un_ecart_d_heure_est_signale_avec_l_event_id() -> None:
    """Le cas du CM de Huez — et l'`event_id` est ce qui permet d'aller le
    corriger sans le chercher à la main dans Celcat."""
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=[])

    ligne = client.get(f"/celcat/comparaison?semaine={SEMAINE}").json()["lignes"][0]
    assert ligne["statut"] == "ecart"
    assert "heure" in ligne["ecarts"]
    assert ligne["celcat"]["event_id"] == 1931709
    assert ligne["caliut"]["heure"] == "15:30"
    assert ligne["celcat"]["heure"] == "13:50"


def test_la_comparaison_dit_l_age_du_releve() -> None:
    """Comparer contre un instantané périmé en le présentant comme l'état
    courant serait la faute même qu'on répare depuis trois jours."""
    instantane.enregistrer([_ev()], groupes=[])

    corps = client.get(f"/celcat/comparaison?semaine={SEMAINE}").json()
    assert corps["releve_le"] is not None
    assert corps["age_secondes"] is not None
    assert corps["perime"] is False


def test_sans_releve_la_comparaison_refuse_de_conclure() -> None:
    """Sans instantané, TOUTES les séances paraîtraient absentes de Celcat —
    un écran qui hurlerait au désastre alors qu'on n'a simplement rien lu."""
    corps = client.get(f"/celcat/comparaison?semaine={SEMAINE}").json()

    assert corps["releve_le"] is None
    assert corps["lignes"] == []
    assert corps["perime"] is True
