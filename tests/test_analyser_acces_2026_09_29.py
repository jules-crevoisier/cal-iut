"""`scripts/analyser_acces.py` (29/09/2026) — diagnostic d'aspiration à
partir des journaux d'accès, sans rien déployer."""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyser_acces.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("analyser_acces", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Enregistré avant exécution : `@dataclass` relit son module par son nom.
    sys.modules["analyser_acces"] = module
    spec.loader.exec_module(module)
    return module


DEBUT = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)


def _nginx(ip: str, quand: datetime, cible: str, ua: str, statut: int = 200) -> str:
    return f'{ip} - - [{quand:%d/%b/%Y:%H:%M:%S %z}] "GET {cible} HTTP/1.1" {statut} 512 "-" "{ua}"'


def _journal() -> list[str]:
    lignes = []
    # Aspirateur : toutes les 60 s, la nuit, 40 liens différents, UA python.
    for n in range(120):
        lignes.append(_nginx("203.0.113.66", DEBUT + timedelta(seconds=60 * n), f"/app-state?t=G{n % 40}",
                             "python-requests/2.31"))
    # Humains : quelques requêtes chacun, en journée.
    for k in range(30):
        quand = DEBUT + timedelta(hours=8, minutes=k * 7)
        for cible in ("/", "/assets/index-abc.js", "/app-state?t=KBR", "/meta?t=KBR"):
            lignes.append(_nginx(f"198.51.100.{k}", quand, cible, "Mozilla/5.0 (X11; Linux) Firefox/130.0"))
    # Agenda Google : régulier, mais légitime.
    for n in range(60):
        lignes.append(_nginx("66.249.84.10", DEBUT + timedelta(minutes=15 * n), f"/ics/prof/P{n % 5}.ics?t=x",
                             "Google-Calendar-Importer"))
    lignes.append("ligne sans rapport")
    return lignes


def test_repere_l_aspirateur_et_propose_la_commande(script) -> None:
    sortie = io.StringIO()
    resultat = script.analyser(_journal(), top=10, sortie=sortie)
    texte = sortie.getvalue()
    assert "203.0.113.66" in resultat["suspects"]
    assert not any(ip.startswith("198.51.100.") for ip in resultat["suspects"])
    assert "66.249.84.10" not in resultat["suspects"]
    assert any(c.startswith("cal-iut bloquer 203.0.113.66 ") and c.endswith("--prod") for c in resultat["commandes"])
    assert "cadence régulière" in texte
    assert "40 liens ?t= différents" in texte
    assert "User-Agent de robot" in texte
    # Codes masqués dans le classement des chemins, assets écartés.
    assert "/ics/prof/{code}.ics" in texte
    assert "/assets/" not in texte


def test_formats_traefik_uvicorn_et_gz(script, tmp_path, capsys) -> None:
    traefik = json.dumps({
        "ClientHost": "203.0.113.9", "RequestMethod": "GET", "RequestPath": "/timetable?t=abc",
        "DownstreamStatus": 200, "StartUTC": "2026-09-28T03:00:00.123456789Z", "request_User-Agent": "curl/8.0",
    })
    a = script.lire_ligne(traefik)
    assert (a.ip, a.chemin, a.t, a.statut, a.ua) == ("203.0.113.9", "/timetable", "abc", 200, "curl/8.0")
    assert a.quand.hour == 3

    uvicorn = '2026-09-28T03:00:00.000000000Z INFO:     203.0.113.9:51234 - "GET /meta?t=KBR HTTP/1.1" 304 Not Modified'
    a = script.lire_ligne(uvicorn)
    assert (a.ip, a.chemin, a.t, a.statut) == ("203.0.113.9", "/meta", "KBR", 304)

    # `docker service logs` (Swarm) préfixe chaque ligne du nom de la tâche.
    swarm = "cal-iut-frontend.1.x7k2@dokploy    | " + _nginx("203.0.113.9", DEBUT, "/meta?t=K", "curl/8.0")
    a = script.lire_ligne(swarm)
    assert (a.ip, a.chemin, a.ua) == ("203.0.113.9", "/meta", "curl/8.0")

    fichier = tmp_path / "access.log.gz"
    with gzip.open(fichier, "wt", encoding="utf-8") as f:
        f.write("\n".join(_journal()))
    assert script.main([str(fichier), "--top", "3"]) == 0
    assert "cal-iut bloquer 203.0.113.66" in capsys.readouterr().out


def test_previent_quand_le_journal_ne_voit_que_le_proxy(script) -> None:
    lignes = [_nginx("10.0.1.7", DEBUT + timedelta(seconds=n), "/app-state?t=x", "Mozilla/5.0") for n in range(50)]
    sortie = io.StringIO()
    script.analyser(lignes, sortie=sortie)
    assert "adresses PRIVÉES" in sortie.getvalue()
