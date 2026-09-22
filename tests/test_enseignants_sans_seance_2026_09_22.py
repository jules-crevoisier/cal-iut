"""Un enseignant qui n'a encore AUCUNE séance doit pouvoir être choisi.

Demande du 22/09/2026 : « Pour l'instant le plus urgent est de me créer Marc
Nino qui intervient jeudi & vendredi. »

Marc Nino (MNI) était déjà déclaré — feuille officielle des contraintes, code
Celcat 37429 — mais « Nouvelle séance » ne proposait que les enseignants
présents dans les séances DÉJÀ PLACÉES (`teacherLabels`). Impossible, donc,
de lui créer sa première séance.

Même demande : Alexia Petit-Halajko, trigramme APH (APE est déjà Anne-Laure
Perrone), code Celcat 40584.
"""

from __future__ import annotations

from pathlib import Path

from test_auth_2026_08_28 import (  # type: ignore[import-not-found]
    _login_admin,
    _sans_session,  # noqa: F401 — base de comptes isolée par test (autouse)
    client,
    etat_avec_seance,  # noqa: F401 — fixture réutilisée
)

from cal_iut.celcat.mapping import load_celcat_config
from cal_iut.ingestion.enseignants import enseignants_declares

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


def test_marc_nino_est_proposable_sans_aucune_seance(etat_avec_seance) -> None:  # noqa: F811
    """LE test de la demande : l'état ne contient qu'une séance, de KBR."""
    _login_admin()
    libelles = client.get("/app-state").json()["teacherLabels"]
    assert libelles.get("MNI") == "Marc Nino", libelles


def test_alexia_petit_halajko_est_aph_et_ne_prend_pas_la_place_d_ape(etat_avec_seance) -> None:  # noqa: F811
    _login_admin()
    libelles = client.get("/app-state").json()["teacherLabels"]
    assert libelles.get("APH") == "Alexia Petit-Halajko", libelles
    assert libelles.get("APE") != "Alexia Petit-Halajko"


def test_le_nom_tire_des_seances_reste_prioritaire(etat_avec_seance) -> None:  # noqa: F811
    """On complète la liste, on ne renomme personne : KBR garde le libellé que
    tout le reste de l'écran affiche déjà."""
    _login_admin()
    corps = client.get("/app-state").json()
    assert "KBR" in corps["teacherLabels"]


def test_les_codes_celcat_sont_connus() -> None:
    """Sans code Celcat, leurs séances resteraient bloquées à la recopie."""
    enseignants = load_celcat_config(CONFIG).enseignants
    assert enseignants.get("MNI") == "37429"
    assert enseignants.get("APH") == "40584"
    assert enseignants.get("APE") == "39386", "Anne-Laure Perrone garde son code"


def test_la_feuille_officielle_a_le_dernier_mot(tmp_path) -> None:
    """Un supplément comble un absent, il ne renomme pas quelqu'un que la
    feuille connaît."""
    config = tmp_path / "data" / "config"
    config.mkdir(parents=True)
    (tmp_path / "contraintes").mkdir()
    (tmp_path / "contraintes" / "05_enseignants_contraintes.json").write_text(
        '[{"trigramme": "MNI", "nom_complet": "Marc Nino"}]', encoding="utf-8"
    )
    (config / "enseignants_supplementaires.yaml").write_text(
        'MNI:\n  nom: "Autre nom"\nAPH:\n  nom: "Alexia Petit-Halajko"\n', encoding="utf-8"
    )
    assert enseignants_declares(config) == {"MNI": "Marc Nino", "APH": "Alexia Petit-Halajko"}


def test_sources_absentes_ou_illisibles_ne_font_rien_tomber(tmp_path) -> None:
    config = tmp_path / "data" / "config"
    config.mkdir(parents=True)
    (tmp_path / "contraintes").mkdir()
    (tmp_path / "contraintes" / "05_enseignants_contraintes.json").write_text("{pas du json", encoding="utf-8")
    assert enseignants_declares(config) == {}


def test_une_seance_creee_ne_remplace_pas_le_nom_par_le_code(etat_avec_seance) -> None:  # noqa: F811
    """22/09/2026 : dès sa première séance (créée depuis l'interface, donc sans
    prénom ni nom), Alexia s'affichait « APH »."""
    from cal_iut.api.state import get_state
    from cal_iut.models.entities import SessionType
    from cal_iut.models.session import SessionToPlace
    from cal_iut.solver.rooms import PlacedSessionWithRoom

    etat = get_state()
    seance = SessionToPlace(
        id="c1", course_code="WS103", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TP,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["APH"],
    )
    etat.sessions = [*etat.sessions, seance]
    etat.sessions_by_id = {**etat.sessions_by_id, "c1": seance}
    etat.timetable = [
        *etat.timetable,
        PlacedSessionWithRoom(session_id="c1", week=0, day=1, slot=0,
                               course_code="WS103", group_ids=["but1-td-ab"], teacher_codes=["APH"]),
    ]
    _login_admin()
    assert client.get("/app-state").json()["teacherLabels"]["APH"] == "Alexia Petit-Halajko"
