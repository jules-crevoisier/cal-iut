"""Créer une séance sur la semaine en cours doit pouvoir se FORCER.

Signalement du 21/09/2026 :

    « Bonjour Jules, je souhaite créer une séance, sur cette semaine mais je
      ne peux pas la forcer, mince. »

Le verrou de semaine est FORÇABLE depuis le 29/08/2026 (« il faut que les
séances soient modifiables à tout moment pour l'instant en forçant »). Mais
`placer_seance` — que la création emprunte — et `_check_move_editable` le
levaient sous forme d'un SIMPLE TEXTE :

    HTTPException(409, "Semaine 4 non modifiable (statut : current)")

Or l'écran ne propose « Créer quand même » que s'il reçoit un conflit
STRUCTURÉ (`hard_conflicts`, cf. `utils/placement.ts::detailConflit`). Faute
de le trouver, il affichait le message brut et s'arrêtait là : un verrou
forçable, qu'aucun bouton ne permettait de forcer.

Le même défaut avait été réparé le 29/08/2026 pour le glisser-déposer de la
Vue Promo, qui passe par une vérification à blanc (cf. la docstring de
`_semaines_non_modifiables`). La création et le placement manuel, eux,
n'en font pas : ils tombaient droit dessus.
"""

from __future__ import annotations

import pytest
from test_maquette_session_patch import _cours  # type: ignore[import-not-found]
from test_placement_manuel import client  # noqa: F401 — fixture réutilisée

from cal_iut.api.state import get_state

# Semaine 0 : en cours ou passée dans le calendrier de test — verrouillée.
SEMAINE_VERROUILLEE = 0


def _conflit_structure(reponse) -> dict:
    """Le détail doit être un OBJET portant `hard_conflicts`, faute de quoi
    l'écran ne peut pas proposer de forcer."""
    assert reponse.status_code == 409, reponse.text
    detail = reponse.json().get("detail")
    assert isinstance(detail, dict), (
        f"le refus doit être structuré pour que l'écran propose « Forcer » : {detail!r}"
    )
    return detail


def _creer(client, **extra):  # noqa: F811
    get_state().courses = [_cours()]
    corps = {
        "course_code": "WR101",
        "session_type": "TD",
        "group_ids": ["but1-td-ab"],
        "teacher_codes": ["MRI"],
        "week": SEMAINE_VERROUILLEE,
        "day": 1,
        "slot": 2,
        **extra,
    }
    return client.post("/placements/personnalisees", json=corps)


def test_creer_sur_la_semaine_en_cours_renvoie_un_conflit_forcable(client) -> None:  # noqa: F811
    """LE test du signalement."""
    detail = _conflit_structure(_creer(client))

    assert any("non modifiable" in m for m in detail["hard_conflicts"]), detail
    assert not detail.get("blocking_conflicts"), (
        "le verrou de semaine se force : il ne doit pas être annoncé comme bloquant"
    )


def test_creer_en_forcant_passe(client) -> None:  # noqa: F811
    reponse = _creer(client, force=True)
    assert reponse.status_code == 200, reponse.text


def test_placer_sur_la_semaine_en_cours_renvoie_un_conflit_forcable(client) -> None:  # noqa: F811
    """Le placement manuel (« À placer ») emprunte le même chemin."""
    reponse = client.post(
        "/placements/manquante/placer",
        json={"week": SEMAINE_VERROUILLEE, "day": 0, "slot": 0},
    )
    detail = _conflit_structure(reponse)
    assert any("non modifiable" in m for m in detail["hard_conflicts"]), detail


def test_deplacer_sur_la_semaine_en_cours_renvoie_un_conflit_forcable(client) -> None:  # noqa: F811
    """`_check_move_editable` levait la même forme, pour tout appelant qui ne
    passe pas par la vérification à blanc."""
    reponse = client.patch(
        "/placements/placee", json={"week": SEMAINE_VERROUILLEE, "day": 0, "slot": 0}
    )
    detail = _conflit_structure(reponse)
    assert any("non modifiable" in m for m in detail["hard_conflicts"]), detail


@pytest.mark.parametrize("route", ["creer", "placer"])
def test_le_libelle_du_verrou_ne_change_pas(client, route) -> None:  # noqa: F811
    """Seule la FORME change. Le libellé est lu ailleurs : la Vue Promo titre
    sa modale « Semaine déjà en cours » en y cherchant « non modifiable »."""
    if route == "creer":
        reponse = _creer(client)
    else:
        reponse = client.post(
            "/placements/manquante/placer",
            json={"week": SEMAINE_VERROUILLEE, "day": 0, "slot": 0},
        )
    motif = next(m for m in _conflit_structure(reponse)["hard_conflicts"] if "non modifiable" in m)
    assert motif.startswith(f"Semaine {SEMAINE_VERROUILLEE + 1} non modifiable (statut : ")


def test_creer_une_seance_pour_marc_nino_passe(client) -> None:  # noqa: F811
    """22/09/2026 : MNI n'a encore aucune séance. Le serveur ne tient pas de
    liste blanche d'enseignants — c'est l'écran qui ne le proposait pas (cf.
    `test_enseignants_sans_seance_2026_09_22.py`). La création doit passer."""
    reponse = _creer(client, teacher_codes=["MNI"], force=True)
    assert reponse.status_code == 200, reponse.text
    assert "MNI" in get_state().timetable[-1].teacher_codes
