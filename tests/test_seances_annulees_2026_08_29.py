"""Séances annulées : des heures qui n'auront pas lieu, et qui ne doivent
pas revenir.

Demande du 29/08/2026. Martial Martin, à propos des quatre derniers TD de
WR104 : « la dernière 1,5h de TD éparpillée le 25 janvier pour AB, le 18
novembre pour CD, le 4 novembre pour EF, le 7 octobre pour GH ; le mieux est
de les supprimer, je ne vais pas pouvoir en faire quelque chose. »

Le piège central : « supprimer » ne veut PAS dire « déplacer hors du
planning ». Une séance simplement retirée du planning redevient une séance
« à placer », donc elle réapparaît dans l'inventaire, dans « À traiter », et
au prochain placement automatique. Il faut qu'elle cesse d'exister à
l'INGESTION, sinon elle revient à chaque redémarrage du serveur — qui
ré-ingère.

D'où un fichier de configuration, et pas un simple appel d'API : c'est la
seule forme qui survive à un re-fetch de la maquette (laquelle continuera
d'annoncer ces heures) et qui garde la trace de QUI a demandé l'annulation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cal_iut.ingestion.config_loader import load_seances_annulees
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace

ROOT = Path(__file__).resolve().parents[1]


def _seance(sid: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR104", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-cd"], teacher_codes=["MMA"], duration_slots=1,
    )


def _ecrire(dossier: Path, contenu: object) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "seances_annulees.yaml").write_text(
        yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8"
    )
    return dossier


# --------------------------------------------------------------------------
# Lecture du fichier
# --------------------------------------------------------------------------


def test_sans_fichier_rien_n_est_annule(tmp_path) -> None:
    assert load_seances_annulees(tmp_path) == set()


def test_un_fichier_vide_n_annule_rien(tmp_path) -> None:
    """Un fichier vidé à la main ne doit pas faire disparaître de cours."""
    (tmp_path / "seances_annulees.yaml").write_text("", encoding="utf-8")
    assert load_seances_annulees(tmp_path) == set()


def test_les_identifiants_sont_lus(tmp_path) -> None:
    _ecrire(tmp_path, {"annulees": [
        {"session_id": "WR104-S1-TD-3-but1-td-cd", "motif": "x", "demande_par": "y", "le": "2026-08-29"},
        {"session_id": "WR104-S1-TD-3-but1-td-ef", "motif": "x", "demande_par": "y", "le": "2026-08-29"},
    ]})
    assert load_seances_annulees(tmp_path) == {
        "WR104-S1-TD-3-but1-td-cd", "WR104-S1-TD-3-but1-td-ef",
    }


def test_une_entree_sans_identifiant_est_refusee(tmp_path) -> None:
    """Silencieusement ignorée, elle donnerait une annulation qu'on croit
    faite et qui ne l'est pas."""
    _ecrire(tmp_path, {"annulees": [{"motif": "oubli d'identifiant"}]})
    with pytest.raises(ValueError, match="session_id"):
        load_seances_annulees(tmp_path)


def test_le_motif_est_obligatoire(tmp_path) -> None:
    """Dans un an, une annulation sans justification est soit supprimée à
    tort, soit conservée à tort — même principe que
    `evenements_supplementaires.yaml`."""
    _ecrire(tmp_path, {"annulees": [{"session_id": "WR104-S1-TD-3-but1-td-cd"}]})
    with pytest.raises(ValueError, match="motif"):
        load_seances_annulees(tmp_path)


# --------------------------------------------------------------------------
# Effet sur l'ingestion
# --------------------------------------------------------------------------


def test_une_seance_annulee_disparait_de_la_liste() -> None:
    from cal_iut.ingestion.pipeline import retirer_seances_annulees

    seances = [_seance("a"), _seance("b"), _seance("c")]
    restantes = retirer_seances_annulees(seances, {"b"})
    assert [s.id for s in restantes] == ["a", "c"]


def test_annuler_une_seance_inexistante_ne_casse_rien() -> None:
    """Le fichier survit à une régénération : un identifiant devenu obsolète
    ne doit pas faire échouer l'ingestion entière."""
    from cal_iut.ingestion.pipeline import retirer_seances_annulees

    seances = [_seance("a")]
    assert [s.id for s in retirer_seances_annulees(seances, {"fantome"})] == ["a"]


def test_sans_annulation_la_liste_est_intacte() -> None:
    from cal_iut.ingestion.pipeline import retirer_seances_annulees

    seances = [_seance("a"), _seance("b")]
    assert retirer_seances_annulees(seances, set()) is seances


# --------------------------------------------------------------------------
# Le fichier réel du dépôt
# --------------------------------------------------------------------------


def test_le_fichier_du_depot_est_lisible() -> None:
    annulees = load_seances_annulees(ROOT / "data" / "config")
    assert isinstance(annulees, set)


def test_les_quatre_td_de_martial_martin_sont_annules() -> None:
    """Demande explicite du 29/08/2026, une séance par groupe de TD."""
    annulees = load_seances_annulees(ROOT / "data" / "config")
    attendues = {
        "WR104-S1-TD-3-but1-td-ab",
        "WR104-S1-TD-3-but1-td-cd",
        "WR104-S1-TD-3-but1-td-ef",
        "WR104-S1-TD-3-but1-td-gh",
    }
    assert attendues <= annulees, attendues - annulees


def test_les_seances_annulees_ne_sont_plus_ingerees() -> None:
    """Le test qui compte : après ingestion réelle, elles ne sont NULLE PART
    — ni placées, ni « à placer »."""
    import json

    seances = json.loads((ROOT / "data" / "generated" / "sessions.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in seances}
    annulees = load_seances_annulees(ROOT / "data" / "config")
    assert not (ids & annulees), f"encore présentes : {ids & annulees}"
