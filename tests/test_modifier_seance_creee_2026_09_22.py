"""Une séance CRÉÉE doit rester modifiable — semaine en cours comprise.

Signalement du 22/09/2026, après la création des séances de Marc Nino sur la
semaine en cours : « je ne peux pas encore modifier la séance une fois
créée ».

L'écran renvoie toujours semaine/jour/créneau. `PATCH /placements/
personnalisees/{id}` rejouait donc un déplacement même pour changer
seulement l'enseignant, et butait sur le verrou de la semaine en cours. Les
champs étaient en outre modifiés avant le contrôle, jamais restaurés en cas de
refus, et l'enseignant n'était pas reporté sur le placement affiché.
"""

from __future__ import annotations

from test_forcer_semaine_en_cours_2026_09_21 import (  # type: ignore[import-not-found]
    SEMAINE_VERROUILLEE,
    _creer,
)
from test_placement_manuel import (
    client,  # type: ignore[import-not-found]  # noqa: F401 — fixture réutilisée
)

from cal_iut.api.state import get_state


def _creee(client) -> dict:  # noqa: F811
    reponse = _creer(client, force=True)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _patch(client, sid: str, **corps):  # noqa: F811
    return client.patch(f"/placements/personnalisees/{sid}", json=corps)


def test_changer_l_enseignant_sur_la_semaine_en_cours_passe_sans_forcer(client) -> None:  # noqa: F811
    """LE test du signalement : même position, autre enseignant."""
    cree = _creee(client)
    reponse = _patch(
        client, cree["session_id"],
        teacher_codes=["MNI"], week=cree["week"], day=cree["day"], slot=cree["slot"],
    )
    assert reponse.status_code == 200, reponse.text

    state = get_state()
    assert state.sessions_by_id[cree["session_id"]].teacher_codes == ["MNI"]
    placement = next(p for p in state.timetable if p.session_id == cree["session_id"])
    assert placement.teacher_codes == ["MNI"], "la grille et Celcat lisent le placement"


def test_deplacer_dans_la_semaine_en_cours_propose_de_forcer(client) -> None:  # noqa: F811
    cree = _creee(client)
    reponse = _patch(client, cree["session_id"], week=SEMAINE_VERROUILLEE, day=cree["day"], slot=cree["slot"] + 1)

    assert reponse.status_code == 409, reponse.text
    detail = reponse.json()["detail"]
    assert isinstance(detail, dict) and detail["hard_conflicts"], detail
    assert not detail.get("blocking_conflicts"), "le verrou de semaine se force"

    force = _patch(
        client, cree["session_id"], week=SEMAINE_VERROUILLEE, day=cree["day"], slot=cree["slot"] + 1, force=True
    )
    assert force.status_code == 200, force.text
    assert force.json()["slot"] == cree["slot"] + 1


def test_un_refus_ne_laisse_aucune_modification_en_memoire(client) -> None:  # noqa: F811
    cree = _creee(client)
    seance = get_state().sessions_by_id[cree["session_id"]]
    avant = (list(seance.teacher_codes), seance.session_type)

    reponse = _patch(
        client, cree["session_id"],
        teacher_codes=["MNI"], session_type="TP",
        week=SEMAINE_VERROUILLEE, day=cree["day"], slot=cree["slot"] + 1,
    )
    assert reponse.status_code == 409, reponse.text
    assert (list(seance.teacher_codes), seance.session_type) == avant
