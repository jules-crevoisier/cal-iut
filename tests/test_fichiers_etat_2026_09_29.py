"""Fichiers d'état non atomiques qui se vidaient en silence — audit du
29/09/2026, P0-4.

Chaîne de perte corrigée : `custom_sessions.json` tronqué -> relu comme `[]`
-> l'ajout suivant réécrit le fichier avec une seule séance -> au démarrage
suivant, les placements de toutes les autres sont purgés de la base comme
« orphelins ».
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import custom_rooms, custom_sessions, forced_pending, main, session_overrides
from cal_iut.celcat.fichiers import FichierEtatIllisible, lire_json_etat
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from conftest import creer_compte_actif_et_connecter


@pytest.fixture
def fichiers_isoles(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(custom_sessions, "_path", lambda: tmp_path / "custom_sessions.json")
    monkeypatch.setattr(session_overrides, "_path", lambda: tmp_path / "session_overrides.json")
    monkeypatch.setattr(custom_rooms, "_path", lambda: tmp_path / "custom_rooms.json")
    monkeypatch.setattr(forced_pending, "_path", lambda: tmp_path / "forced_pending.json")
    return tmp_path


def _seance(n: int) -> SessionToPlace:
    return SessionToPlace(
        id=f"WR101-S1-TD-CUSTOM{n}-but1-td-ab",
        course_code="WR101", course_name="Écriture", semestre="S1", parcours="BUT1",
        annee="1", session_type=SessionType.TD, group_ids=["but1-td-ab"],
        teacher_codes=["KBR"], metadata={"custom_session": True},
    )


# --------------------------------------------------------------------------
# Lecture : absent = défaut, illisible = mis de côté + erreur explicite.
# --------------------------------------------------------------------------


def test_un_fichier_absent_rend_le_defaut(tmp_path: Path) -> None:
    assert lire_json_etat(tmp_path / "absent.json", []) == []


def test_un_json_tronque_est_mis_de_cote_et_leve(tmp_path: Path) -> None:
    chemin = tmp_path / "etat.json"
    chemin.write_text('[{"id": "a"', encoding="utf-8")
    with pytest.raises(FichierEtatIllisible) as erreur:
        lire_json_etat(chemin, [])
    assert not chemin.exists()
    copies = list(tmp_path.glob("etat.json.corrompu-*"))
    assert len(copies) == 1
    assert copies[0].read_text(encoding="utf-8") == '[{"id": "a"'
    assert erreur.value.copie == copies[0]
    assert "illisible" in str(erreur.value)


def test_une_racine_du_mauvais_type_est_traitee_comme_illisible(tmp_path: Path) -> None:
    chemin = tmp_path / "etat.json"
    chemin.write_text('{"pas": "une liste"}', encoding="utf-8")
    with pytest.raises(FichierEtatIllisible):
        lire_json_etat(chemin, [], types=list)
    assert list(tmp_path.glob("etat.json.corrompu-*"))


@pytest.mark.parametrize(
    ("module", "appel"),
    [
        (custom_sessions, lambda: custom_sessions.add_custom_session(_seance(99))),
        (session_overrides, lambda: session_overrides.upsert_overlay("s1", {"is_eval": True})),
        (custom_rooms, lambda: custom_rooms.set_room_override("h005", placement_auto=False)),
        (forced_pending, lambda: forced_pending.mark("s1", 1, 2, 3)),
    ],
)
def test_une_ecriture_sur_un_fichier_illisible_ne_repart_pas_de_vide(fichiers_isoles, module, appel) -> None:
    module._path().write_text("{ tronqué", encoding="utf-8")
    with pytest.raises(FichierEtatIllisible):
        appel()
    # Rien n'a été réécrit « à partir de rien » à la place du fichier abîmé.
    assert not module._path().exists()
    assert list(fichiers_isoles.glob(f"{module._path().name}.corrompu-*"))


# --------------------------------------------------------------------------
# Écriture : atomique et sous verrou.
# --------------------------------------------------------------------------


def test_les_ecritures_ne_passent_plus_par_write_text(fichiers_isoles) -> None:
    def _interdit(*_a, **_k):
        raise AssertionError("écriture non atomique")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "write_text", _interdit)
        custom_sessions.add_custom_session(_seance(1))
        session_overrides.upsert_overlay("s1", {"is_eval": True})
        custom_rooms.set_room_override("h005", placement_auto=False)
        forced_pending.mark("s1", 1, 2, 3)
    assert len(json.loads(custom_sessions._path().read_text(encoding="utf-8"))) == 1


def test_des_ajouts_simultanes_ne_se_perdent_pas(fichiers_isoles) -> None:
    fils = [threading.Thread(target=custom_sessions.add_custom_session, args=(_seance(n),)) for n in range(20)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert len(custom_sessions.load_custom_sessions()) == 20


def test_des_retouches_simultanees_ne_se_perdent_pas(fichiers_isoles) -> None:
    fils = [
        threading.Thread(target=session_overrides.upsert_overlay, args=(f"s{n}", {"is_eval": True}))
        for n in range(20)
    ]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert len(session_overrides.load_overrides()) == 20


# --------------------------------------------------------------------------
# API : 503 explicite plutôt qu'une réécriture silencieuse.
# --------------------------------------------------------------------------


def test_l_api_repond_503_sur_un_fichier_d_etat_illisible(db_isole, fichiers_isoles) -> None:
    custom_rooms._path().write_text("[{", encoding="utf-8")
    client = TestClient(main.app)
    creer_compte_actif_et_connecter(client, role="admin")
    reponse = client.post("/rooms", json={"label": "Amphi test", "capacity": 30})
    assert reponse.status_code == 503
    assert "illisible" in reponse.json()["detail"]


# --------------------------------------------------------------------------
# Restauration : pas de purge massive des placements « orphelins ».
# --------------------------------------------------------------------------


def _placements(n: int, prefixe: str = "WR101-S1-TD-") -> list[SimpleNamespace]:
    return [SimpleNamespace(session_id=f"{prefixe}{i}") for i in range(n)]


def test_quelques_orphelins_de_maquette_sont_purges() -> None:
    orphelins = _placements(2)
    assert main._orphelins_a_purger(orphelins, 100) == orphelins


def test_au_dela_du_seuil_rien_n_est_purge(caplog) -> None:
    with caplog.at_level("ERROR"):
        assert main._orphelins_a_purger(_placements(6), 100) == []
    assert "aucune purge" in caplog.text


def test_les_orphelins_de_seances_personnalisees_ne_sont_jamais_purges() -> None:
    maquette = _placements(1)
    perso = _placements(1, prefixe="WR101-S1-TD-CUSTOM1-but1-td-ab")
    assert main._orphelins_a_purger(maquette + perso, 100) == maquette
