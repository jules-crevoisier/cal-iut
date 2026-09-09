"""Mettre le worker en pause libère le VPN — et ne détruit RIEN.

Demande de Jules Crevoisier, 09/09/2026 : « c'est possible de faire un
bouton qui active et désactive le worker qui utilise le VPN dans
l'interface ? ».

POURQUOI IL EN A BESOIN. Le VPN et le compte Celcat sont PARTAGÉS avec
l'équipe pédagogique. Tant que le worker tourne, il monte le tunnel toutes
les 90 secondes, et personne ne peut ouvrir une session durable à côté. Le
même jour, une recherche d'identifiant (le numéro de personnel de JHU,
absent de `celcat.yaml`) a dû être abandonnée : le tunnel était coupé à
chaque cycle.

CE QUI EXISTAIT DÉJÀ NE POUVAIT PAS SERVIR. `PATCH /celcat/saisie
{active: false}` a l'air d'une pause, mais il appelle `vider()` : couper la
saisie EFFACE la file d'attente. S'en servir aurait perdu les corrections en
attente — 99 jobs le jour de la demande. C'est un piège déjà signalé plus
tôt dans la journée, et il fallait donc un second interrupteur, pas
réutiliser le premier.

La pause ne touche ni la file, ni le journal, ni les semaines validées : le
worker reprend exactement là où il s'était arrêté.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    jobs_en_attente,
    monter_planning,
    place,
    seance,
    vider_file,
)

from cal_iut.celcat.etat import charger, sauver, worker_en_pause

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def client_admin(db_isole):
    """Client admin sur un état applicatif minimal — le même montage que les
    autres tests Celcat, pour ne pas dépendre d'un planning réel."""
    s = seance("s-quelconque")
    return monter_planning([(s, place(s, week=SEMAINE))])


# --------------------------------------------------------------------------
# L'état
# --------------------------------------------------------------------------


def test_le_worker_tourne_par_defaut(db_isole) -> None:
    """Un état ancien, écrit avant l'existence de ce champ, doit continuer de
    travailler — pas s'arrêter en silence."""
    doc = charger()
    doc.pop("worker_actif", None)
    sauver(doc)

    assert worker_en_pause() is False


@pytest.mark.parametrize(("actif", "en_pause"), [(True, False), (False, True)])
def test_la_pause_se_lit_depuis_l_etat_partage(db_isole, actif: bool, en_pause: bool) -> None:
    doc = charger()
    doc["worker_actif"] = actif
    sauver(doc)

    assert worker_en_pause() is en_pause


# --------------------------------------------------------------------------
# LE point : ça ne doit rien détruire
# --------------------------------------------------------------------------


def test_mettre_en_pause_ne_vide_pas_la_file(client_admin) -> None:
    """C'EST TOUTE LA RAISON D'ÊTRE de cette route. `PATCH /celcat/saisie`
    appelle `vider()` : s'en servir comme d'une pause aurait perdu les 99
    corrections en attente."""
    from cal_iut.celcat.file_attente import enfiler

    vider_file()
    enfiler({"action": "create", "session_id": "s-en-attente", "semaine": SEMAINE})

    reponse = client_admin.patch("/celcat/worker", json={"actif": False})

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["worker_actif"] is False
    assert [j["session_id"] for j in jobs_en_attente()] == ["s-en-attente"], (
        "la file doit survivre à la pause"
    )


def test_la_pause_ne_touche_ni_le_journal_ni_les_semaines(client_admin) -> None:
    doc = charger()
    doc["semaines_validees"] = [4, 5]
    doc["journal"] = {"s-x": {"session_id": "s-x", "event_id": "1234"}}
    sauver(doc)

    client_admin.patch("/celcat/worker", json={"actif": False})

    apres = charger()
    assert apres["semaines_validees"] == [4, 5]
    assert apres["journal"]["s-x"]["event_id"] == "1234"


def test_reprendre_remet_le_worker_en_marche(client_admin) -> None:
    client_admin.patch("/celcat/worker", json={"actif": False})
    reponse = client_admin.patch("/celcat/worker", json={"actif": True})

    assert reponse.json()["worker_actif"] is True
    assert worker_en_pause() is False


def test_l_etat_expose_la_pause(client_admin) -> None:
    """L'écran a besoin de connaître la position de l'interrupteur."""
    client_admin.patch("/celcat/worker", json={"actif": False})

    assert client_admin.get("/celcat/etat").json()["worker_actif"] is False


# --------------------------------------------------------------------------
# Les trois scripts du sidecar doivent regarder ce drapeau
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script", ["celcat_immediat.py", "celcat_instantane.py", "celcat_nuit.py"]
)
def test_chaque_script_du_sidecar_sort_avant_de_monter_le_vpn(script: str) -> None:
    """Le contrôle doit être fait par CHACUN des trois — c'est le premier qui
    tourne dans la boucle des 90 secondes qui prend le tunnel, et il suffit
    d'un seul oublié pour que la pause ne libère rien.

    Vérifié dans l'AST : `worker_en_pause` doit être appelé DANS `principal`,
    et avant tout appel à `reseau` (qui monte le tunnel).
    """
    arbre = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"))
    principal = next(
        n for n in ast.walk(arbre)
        if isinstance(n, ast.FunctionDef) and n.name == "principal"
    )

    lignes_pause = [
        n.lineno for n in ast.walk(principal)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "worker_en_pause"
    ]
    lignes_reseau = [
        n.lineno for n in ast.walk(principal)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "reseau"
    ]

    assert lignes_pause, f"{script} ne consulte pas la pause"
    assert lignes_reseau, f"{script} ne touche pas au réseau — test à revoir"
    assert min(lignes_pause) < min(lignes_reseau), (
        f"{script} monte le VPN avant de regarder la pause : "
        f"pause ligne {min(lignes_pause)}, réseau ligne {min(lignes_reseau)}"
    )
