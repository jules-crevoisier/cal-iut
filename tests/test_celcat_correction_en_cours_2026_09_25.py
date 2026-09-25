"""La correction envoyée pour une semaine doit survivre à l'onglet qu'on quitte.

Signalement de Jules Crevoisier, 25/09/2026 : « quand par exemple on corrige
un écart, ça envoie, ça met qu'on l'a envoyé à corriger, donc ça fait une
attente du passage du worker. Si on quitte et qu'on revient sur l'onglet
Celcat, ça le remet en mode qu'on peut le recorriger. »

Ces tests protègent `cal_iut.celcat.correction_en_cours` : l'écriture est
relue TELLE QUELLE après un redémarrage simulé (autre `Path` ré-ouvert), le
suivi s'efface tout seul une fois le worker repassé ET un relevé frais
arrivé, et il s'efface aussi après le délai généreux (45 min) — sans jamais
dire « échoué », puisque les jobs restent en file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cal_iut.celcat import correction_en_cours as cec
from cal_iut.celcat import drainage, instantane


@pytest.fixture(autouse=True)
def _fichiers_isoles(tmp_path, monkeypatch):
    monkeypatch.setattr(cec, "_path", lambda: tmp_path / "celcat_correction_en_cours.json")
    monkeypatch.setattr(drainage, "_path", lambda: tmp_path / "celcat_drainage.json")
    monkeypatch.setattr(instantane, "_path", lambda: tmp_path / "celcat_instantane.json")
    monkeypatch.setattr(instantane, "_path_demande", lambda: tmp_path / "celcat_instantane_demande.json")
    yield


def _iso(delta_min: float = 0.0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=delta_min)).isoformat()


def test_should_be_absente_when_nothing_was_ever_queued_for_the_week() -> None:
    etat = cec.lire(7)
    assert etat.etat == "absente"
    assert etat.mise_en_file_le is None


def test_should_record_a_correction_and_read_it_back_as_en_cours() -> None:
    cec.enregistrer(7, par="jules@iut", total=3)

    etat = cec.lire(7)
    assert etat.etat == "en_cours"
    assert etat.par == "jules@iut"
    assert etat.total == 3
    assert etat.mise_en_file_le is not None


def test_should_keep_the_record_across_a_fresh_process_reading_the_same_file(tmp_path, monkeypatch) -> None:
    """Redémarrage simulé : un second import qui rouvre le MÊME fichier doit
    retrouver exactement ce que le premier a écrit — c'est tout l'intérêt
    d'un état SERVEUR plutôt que d'un état React."""
    cec.enregistrer(9, par="kyllian@iut", total=5)

    # Un « autre processus » : une instance fraîche des mêmes fonctions, sur
    # le même fichier isolé.
    import importlib

    frais = importlib.reload(cec)
    monkeypatch.setattr(frais, "_path", lambda: tmp_path / "celcat_correction_en_cours.json")

    etat = frais.lire(9)
    assert etat.etat == "en_cours"
    assert etat.par == "kyllian@iut"
    assert etat.total == 5


def test_should_not_be_affected_by_a_correction_queued_for_another_week() -> None:
    cec.enregistrer(9, par="jules@iut", total=1)
    assert cec.lire(7).etat == "absente"
    assert cec.lire(9).etat == "en_cours"


def test_should_clear_once_the_worker_passed_since_queueing_and_a_fresher_releve_arrived() -> None:
    cec.enregistrer(7, par="jules@iut", total=2)
    # Le worker n'est PAS encore repassé : sa trace est restée celle d'avant
    # la mise en file (None ici, aucun passage connu).
    assert cec.lire(7).etat == "en_cours"

    # Le worker passe.
    drainage.enregistrer(en_attente=0, reussis=2, echecs=0, ignores=0, resume="ok")
    # Mais le relevé n'a pas encore suivi : toujours en attente.
    assert cec.lire(7).etat == "en_cours"

    # Un relevé plus récent que la mise en file arrive.
    instantane.enregistrer([], groupes=[])
    etat = cec.lire(7)
    assert etat.etat == "termine"

    # Et le suivi s'est effacé : relire ne montre plus rien.
    assert cec.lire(7).etat == "absente"


def test_should_stay_en_cours_when_worker_passed_but_releve_is_still_older_than_queueing() -> None:
    """Le worker peut passer AVANT que le relevé qu'on attend n'arrive — les
    deux conditions sont nécessaires, ni l'une ni l'autre ne suffit seule."""
    # Un relevé ancien, déjà là AVANT la mise en file.
    instantane.enregistrer([], groupes=[], releve_le=_iso(30))
    cec.enregistrer(7, par="jules@iut", total=1)
    drainage.enregistrer(en_attente=0, reussis=1, echecs=0, ignores=0, resume="ok")

    etat = cec.lire(7)
    assert etat.etat == "en_cours"


def test_should_expire_after_the_timeout_without_ever_saying_it_failed() -> None:
    doc = {
        "7": {
            "mise_en_file_le": _iso(cec.TIMEOUT_SECONDES / 60 + 1),
            "par": "jules@iut",
            "total": 4,
            "passe_le_avant": None,
        }
    }
    import json

    (cec._path()).parent.mkdir(parents=True, exist_ok=True)
    cec._path().write_text(json.dumps(doc), encoding="utf-8")

    etat = cec.lire(7)
    assert etat.etat == "expire"
    assert "échoué" not in etat.message.lower()
    assert "échec" not in etat.message.lower()

    # Et le suivi s'est effacé, comme pour "termine".
    assert cec.lire(7).etat == "absente"


def test_should_not_expire_before_the_timeout() -> None:
    doc = {
        "7": {
            "mise_en_file_le": _iso(cec.TIMEOUT_SECONDES / 60 - 1),
            "par": "jules@iut",
            "total": 1,
            "passe_le_avant": None,
        }
    }
    import json

    cec._path().parent.mkdir(parents=True, exist_ok=True)
    cec._path().write_text(json.dumps(doc), encoding="utf-8")

    assert cec.lire(7).etat == "en_cours"


def test_effacer_removes_the_week_without_touching_others() -> None:
    cec.enregistrer(7, par="jules@iut", total=1)
    cec.enregistrer(9, par="jules@iut", total=1)

    cec.effacer(7)

    assert cec.lire(7).etat == "absente"
    assert cec.lire(9).etat == "en_cours"


def test_effacer_on_an_absent_week_does_nothing_and_does_not_raise() -> None:
    cec.effacer(3)
    assert cec.lire(3).etat == "absente"
