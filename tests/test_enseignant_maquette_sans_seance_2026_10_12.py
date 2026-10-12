"""Un intervenant de la maquette sans séance doit apparaître dans la liste.

Signalement du 12/10/2026 : « j'ai voulu créer le vacataire Sébastien
Loizon, mais il me dit qu'il existe déjà en SLO » — et SLO n'était pas dans
« Enseignants & vacataires ». Il n'est que dans la maquette (WS501D, TP et
PTUT) : pas de séance, pas de ligne dans la feuille des contraintes. Le code
était donc « pris » sans que sa fiche soit visible.
"""

from __future__ import annotations

from test_auth_2026_08_28 import (  # type: ignore[import-not-found]
    _login_admin,
    _sans_session,  # noqa: F401 — base de comptes isolée par test (autouse)
    client,
    etat_avec_seance,  # noqa: F401 — fixture réutilisée
)

from cal_iut.api.main import get_state
from cal_iut.models.entities import Course, Teacher, TeacherBlock


def _ws501d() -> Course:
    slo = Teacher(code="SLO", nom="LOIZON", prenom="Sébastien")
    return Course(
        code="WS501D", name="SAE", semestre="S5", parcours="BUT3-DEV-FI", annee="BUT3",
        lead=Teacher(code="FME", nom="", prenom=""),
        profs=[TeacherBlock(teacher=slo, block="block1", tp=6)],
        volumes={}, groupes_td=0, groupes_tp=1, progression_defined=False,
        seance_sequence=[], ordonnancement=[],
    )


def test_slo_apparait_dans_la_liste_et_l_annuaire(etat_avec_seance) -> None:  # noqa: F811
    get_state().courses = [_ws501d()]
    _login_admin()
    libelles = client.get("/app-state").json()["teacherLabels"]
    assert libelles.get("SLO") == "Sébastien LOIZON", libelles
    assert libelles.get("KBR"), "les enseignants des séances restent"
    lignes = client.get("/reference/enseignants").json()["lignes"]
    assert "SLO" in {l["code"] for l in lignes}
