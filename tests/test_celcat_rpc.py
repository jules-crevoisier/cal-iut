"""RPC Celcat dans la page — sans Playwright, sans clic.

`FaussePage.evaluate` simule le `fetch` JSON-RPC 2.0 que `rpc.appeler`
injecte vers `/script/CTWebService.dll`. Rien ici n'ouvre Celcat.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from cal_iut.celcat.navigateur import TYPE_GROUPES, TYPE_MATIERES
from cal_iut.celcat.rpc import (
    SessionCelcatTimeout,
    appeler,
    charger_edt,
    charger_ressources,
    enregistrer_evenement,
    masquer_semaine,
    parser_reponse,
    preparer_evenement,
)

GROUP_ID = 1661972


class FaussePage:
    """Page Playwright factice — ne pas importer playwright."""

    def __init__(self) -> None:
        self.journal: list[tuple] = []
        self.reponses: dict = {}
        self.evenements_enregistres: list[dict] = []

    def evaluate(self, js, arg=None):
        self.journal.append((js, arg))
        methode = None
        params = None
        if isinstance(arg, dict):
            methode = arg.get("methode") or arg.get("method")
            params = arg.get("params")
        catalogue = self._catalogue_demande(methode, params)
        if catalogue is not None:
            return self._ok(catalogue)
        if methode and methode in self.reponses:
            val = self.reponses[methode]
            if isinstance(val, dict) and "error" in val:
                return val
            if isinstance(val, int):
                self.evenements_enregistres.append({"event_id": val})
                return self._ok(val)
            if isinstance(val, dict) and (val.get("event_id") or val.get("id")):
                self.evenements_enregistres.append(dict(val))
            return self._ok(val)
        if methode and "load" in str(methode).lower():
            return self._ok(list(self.evenements_enregistres))
        return self._ok(None)

    @staticmethod
    def _catalogue_demande(methode: object, params: object) -> list[dict] | None:
        """Répond aux catalogues GROUPES et MATIÈRES avec les vraies tables.

        Sans ça, `udlResources.load` retombait sur la réponse générique (la
        liste des évènements enregistrés), `_trouver_groupe` ne trouvait
        rien, et `nuit.py` écrivait avec `group_id=0`. Les tests de drainage
        passaient donc en exerçant un chemin qui, en vrai, ne peut RIEN
        écrire : Celcat refuse un groupe à zéro par « une des ressources
        affectées a été supprimée » (production, 09/09/2026).

        La table lue est celle du dépôt : la fausse Celcat porte les mêmes
        groupes que la vraie, ni plus ni moins. Un identifiant absent de la
        table reste donc introuvable ici aussi, et c'est voulu.
        """
        if methode != "udlResources.load" or not isinstance(params, list) or len(params) < 2:
            return None
        from cal_iut.celcat.ecriture import _groupes_connus, _matieres_connues

        if params[0] == TYPE_GROUPES:
            par_id = {v: k for k, v in _groupes_connus().items()}
            cle, nomme = "group_id", "name"
        elif params[0] == TYPE_MATIERES:
            par_id = {v: k for k, v in _matieres_connues().items()}
            cle, nomme = "module_id", "unique_name"
        else:
            return None
        demandes = (params[1] or {}).get("recordIDs") or []
        return [
            {cle: int(i), "id": int(i), nomme: par_id[int(i)]}
            for i in demandes
            if int(i) in par_id
        ]

    @staticmethod
    def _ok(result: object) -> dict:
        return {
            "status": 200,
            "texte": json.dumps(
                {"jsonrpc": "2.0", "id": 0, "result": result},
                ensure_ascii=False,
            ),
        }


def test_should_return_single_y_when_masquer_semaine_indice_in_range() -> None:
    masque = masquer_semaine(longueur=54, indice=3)
    assert len(masque) == 54
    assert masque.count("Y") == 1
    assert masque[3] == "Y"
    assert set(masque) <= {"Y", "N"}


def test_should_raise_when_masquer_semaine_indice_out_of_range() -> None:
    with pytest.raises((IndexError, ValueError)):
        masquer_semaine(longueur=54, indice=54)
    with pytest.raises((IndexError, ValueError)):
        masquer_semaine(longueur=54, indice=-1)


def test_should_post_udl_timetables_load_when_charger_edt() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = []
    charger_edt(page, group_ids=[GROUP_ID])
    assert page.journal, "appeler doit passer par page.evaluate"
    js, arg = page.journal[0]
    assert "CTWebService.dll" in js
    assert "X-Use-Object-Date" in js
    assert isinstance(arg, dict)
    nom = arg.get("methode") or arg.get("method")
    assert nom == "udlTimetables.load"
    assert arg["params"] == [{"GroupIDs": [GROUP_ID]}]


def test_should_raise_session_timeout_when_esessiontimeout() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = {"error": {"code": "ESessionTimeout"}}
    with pytest.raises(SessionCelcatTimeout):
        appeler(page, "udlTimetables.load", [{"GroupIDs": [GROUP_ID]}])


def test_should_not_import_playwright_when_rpc_module_loads() -> None:
    avant = set(sys.modules)
    from cal_iut.celcat import rpc  # noqa: F401

    nouveaux = set(sys.modules) - avant
    assert not any(m == "playwright" or m.startswith("playwright.") for m in nouveaux)
    arbre = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    racines: list[str] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            racines.extend(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            racines.append(noeud.module.split(".")[0])
    assert "playwright" not in racines


def test_should_raise_when_enregistrer_evenement_methode_empty() -> None:
    page = FaussePage()
    with pytest.raises(Exception) as captured:
        enregistrer_evenement(page, {"weeks": "NNNY" + "N" * 50}, methode="")
    assert captured.type.__name__ == "MethodeEcritureAbsente"


def test_should_wrap_event_in_array_when_enregistrer_evenement() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.save"] = 8000001
    enregistrer_evenement(
        page,
        {
            "event_id": 202985,
            "weeks": "Y" + "N" * 53,
            "notes": "cal-iut-canari",
            "accessRights": {},
            "registerRequired": "Y",
        },
        methode="udlTimetables.save",
    )
    _js, arg = page.journal[0]
    params = arg["params"]
    assert isinstance(params[0], list)
    evenement = params[0][0]
    assert evenement["_type_"] == "Event"
    assert evenement["notes"] == "cal-iut-canari"
    assert "accessRights" not in evenement
    assert "registerRequired" not in evenement


def test_should_strip_nested_event_id_when_preparer_create() -> None:
    pret = preparer_evenement({
        "event_id": 0,
        "weeks": "Y" + "N" * 53,
        "modules": [{"module_id": 1, "event_id": 99}],
        "groups": [{"group_id": 2, "event_id": 99}],
        "rooms": [{"room_id": 3, "event_id": 99}],
        "staff": [{"staff_id": 4, "event_id": 99}],
    })
    assert pret.get("event_id") in (None, 0)
    assert "event_id" not in pret
    assert pret["_type_"] == "Event"
    assert pret["modules"][0]["module_id"] == 1
    assert "event_id" not in pret["modules"][0]
    assert pret["groups"][0]["_type_"] == "Group"


def test_should_keep_event_id_when_preparer_update() -> None:
    pret = preparer_evenement({
        "event_id": 1931666,
        "weeks": "Y" + "N" * 53,
        "modules": [{"module_id": 1}],
        "groups": [{"group_id": 2}],
        "rooms": [{"room_id": 3}],
        "staff": [{"staff_id": 4}],
    })
    assert pret["event_id"] == 1931666
    assert pret["_type_"] == "Event"


def test_should_load_resources_by_type_when_charger_ressources() -> None:
    page = FaussePage()
    page.reponses["udlResources.load"] = [{"id": 1604422, "name": "H.105"}]
    salles = charger_ressources(page, 604, {"name": "H.105", "customOnly": False})
    assert salles[0]["id"] == 1604422
    _js, arg = page.journal[0]
    assert arg["methode"] == "udlResources.load"
    assert arg["params"][0] == 604


def test_should_convert_js_month_zero_to_june_when_parser_reponse() -> None:
    lu = parser_reponse('{"d": new Date(2026,5,12,8,0,0,0)}')
    assert lu["d"] == "2026-06-12T08:00:00"
