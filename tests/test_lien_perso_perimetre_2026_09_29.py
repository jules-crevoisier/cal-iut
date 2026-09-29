"""Périmètre du lien personnel public (`?t=`) — audit du 29/09/2026, P0-2.

Avant : dès que `?t=` était non vide, le middleware `require_auth` laissait
passer TOUTE route protégée. `/legacy?t=x` rendait 769 Ko de HTML avec 32
adresses mail d'enseignants et leurs contraintes en clair ; `/taches`,
`/exceptions`, `/export/csv`... étaient lisibles de la même façon.

Après : `?t=` n'ouvre que les lectures (GET/HEAD) des vues publiques
(`_LIEN_PERSO_CHEMINS`, `_LIEN_PERSO_PREFIXES`). Ce test parcourt TOUTES
les routes protégées : une route ajoutée demain sans y penser reste fermée.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import main
from cal_iut.api.main import app
from conftest import creer_compte_actif_et_connecter


def _chemin_concret(chemin: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", chemin)


def _routes_protegees() -> list[tuple[str, str]]:
    routes = []
    for route in app.routes:
        chemin = getattr(route, "path", None)
        methodes = getattr(route, "methods", None) or set()
        if not chemin or not chemin.startswith(main._PROTECTED_PREFIXES):
            continue
        if chemin.startswith(main._PUBLIC_PREFIXES):
            continue
        for methode in sorted(methodes - {"HEAD", "OPTIONS"}):
            routes.append((methode, chemin))
    return routes


def _ouverte_au_lien_perso(methode: str, chemin: str) -> bool:
    concret = _chemin_concret(chemin)
    return methode == "GET" and (
        concret in main._LIEN_PERSO_CHEMINS or concret.startswith(main._LIEN_PERSO_PREFIXES)
    )


def test_la_liste_blanche_ne_contient_que_les_lectures_des_vues_publiques() -> None:
    assert main._LIEN_PERSO_CHEMINS == frozenset({"/app-state", "/meta", "/timetable"})
    assert main._LIEN_PERSO_PREFIXES == ("/ics/",)


@pytest.mark.parametrize(("methode", "chemin"), _routes_protegees())
def test_un_lien_perso_sans_compte_n_ouvre_que_la_liste_blanche(db_isole, methode, chemin) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    reponse = client.request(methode, _chemin_concret(chemin), params={"t": "x"})
    if _ouverte_au_lien_perso(methode, chemin):
        assert reponse.status_code != 401, f"{methode} {chemin} devrait rester lisible par un lien perso"
    else:
        assert reponse.status_code == 401, f"{methode} {chemin}?t=x rend {reponse.status_code} sans compte"


def test_legacy_n_est_plus_ouverte_par_un_lien_perso(db_isole) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    reponse = client.get("/legacy", params={"t": "KBR"})
    assert reponse.status_code == 401
    assert "@" not in reponse.text


def test_legacy_est_reservee_aux_admins(db_isole) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    creer_compte_actif_et_connecter(client, role="edit")
    assert client.get("/legacy").status_code == 403


def test_un_prefixe_de_chaine_ne_suffit_pas() -> None:
    """`/metadata?t=x` ne doit pas hériter de l'ouverture de `/meta`."""

    class _Req:
        method = "GET"

        class url:  # noqa: N801
            path = "/metadata"

    assert main._lien_perso_autorise(_Req()) is False  # type: ignore[arg-type]


def test_un_lien_perso_ne_permet_aucune_ecriture(db_isole) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/timetable", params={"t": "x"}).status_code == 401
