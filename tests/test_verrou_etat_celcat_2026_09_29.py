"""Verrou inter-processus sur les fichiers d'état Celcat (audit 29/09/2026, P1-14).

Le backend et `celcat-nuit` relisent, modifient et réécrivent
`celcat_sync.json` (journal séance -> event_id, seul rempart contre les
doublons). L'écriture était atomique, pas la séquence : une ligne écrite par
l'un pouvait disparaître sous l'écriture de l'autre.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from cal_iut.celcat import fichiers

pytestmark = pytest.mark.skipif(fichiers.fcntl is None, reason="fcntl indisponible (Windows)")

ROOT = Path(__file__).resolve().parents[1]


def _processus(code: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=ROOT,
    )


def test_un_autre_processus_qui_tient_le_verrou_fait_attendre_l_ecriture(tmp_path):
    fichier = tmp_path / "celcat_sync.json"
    autre = _processus(
        "import sys\n"
        "from pathlib import Path\n"
        "from cal_iut.celcat.fichiers import verrou_fichier\n"
        "with verrou_fichier(Path(sys.argv[1])):\n"
        "    print('pris', flush=True)\n"
        "    sys.stdin.readline()\n",
        str(fichier),
    )
    try:
        assert autre.stdout.readline().strip() == "pris"
        entre = threading.Event()

        def ecrire() -> None:
            with fichiers.verrou_fichier(fichier):
                entre.set()

        t = threading.Thread(target=ecrire)
        t.start()
        assert not entre.wait(0.3), "le verrou de l'autre processus n'a pas été respecté"
        autre.stdin.write("\n")
        autre.stdin.flush()
        assert entre.wait(10)
        t.join(5)
    finally:
        autre.kill()
        autre.wait(5)


def test_deux_processus_qui_journalisent_en_meme_temps_ne_perdent_aucune_ligne(tmp_path):
    fichier = tmp_path / "celcat_sync.json"
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from cal_iut.celcat import etat, sync\n"
        "p = Path(sys.argv[1])\n"
        "etat._path = lambda: p\n"
        "sys.stdin.readline()\n"
        # Numéros d'évènement PROPRES à chaque processus : depuis le
        # 02/10/2026, un évènement n'appartient qu'à une séance
        # (`test_celcat_evenement_deux_seances_2026_10_02.py`) — deux séances
        # sur le même numéro ne font plus deux lignes.
        "base = 1000 if sys.argv[2] == 'nuit' else 0\n"
        "for i in range(40):\n"
        "    sync.reconcilier([{'session_id': f'{sys.argv[2]}-{i}', 'event_id': base + i}])\n"
    )
    procs = [_processus(code, str(fichier), tag) for tag in ("api", "nuit")]
    for p in procs:  # départ simultané
        p.stdin.write("\n")
        p.stdin.flush()
    for p in procs:
        assert p.wait(60) == 0

    from cal_iut.celcat import etat

    etat_path = etat._path
    etat._path = lambda: fichier
    try:
        journal = etat.charger()["journal"]
    finally:
        etat._path = etat_path
    assert len(journal) == 80


def test_le_verrou_est_reentrant_dans_un_meme_thread(tmp_path):
    fichier = tmp_path / "x.json"
    with fichiers.verrou_fichier(fichier), fichiers.verrou_fichier(fichier):
        pass
    assert (tmp_path / "x.json.lock").exists()


def test_sans_fcntl_le_verrou_ne_bloque_pas(tmp_path, monkeypatch):
    """Poste de développement Windows : pas de `fcntl`, pas de second
    processus — le verrou de thread suffit, et rien ne casse."""
    monkeypatch.setattr(fichiers, "fcntl", None)
    fichier = tmp_path / "y.json"
    with fichiers.verrou_fichier(fichier), fichiers.verrou_fichier(fichier):
        pass
    assert not (tmp_path / "y.json.lock").exists()


def test_les_routes_celcat_ecrivent_sous_le_verrou(monkeypatch):
    from cal_iut.api import main
    from cal_iut.api.schemas import CelcatWorkerRequest
    from cal_iut.celcat import etat

    vus: list[bool] = []
    original = etat.sauver

    def sauver_espion(doc):
        verrou, profondeur = fichiers._verrou_local(str(etat._path().resolve()))
        vus.append(profondeur[0] > 0)
        original(doc)

    monkeypatch.setattr(etat, "sauver", sauver_espion)
    monkeypatch.setattr(main, "_celcat_etat_public", lambda: None)
    main.celcat_worker_actif(CelcatWorkerRequest(actif=False))
    assert vus == [True]
