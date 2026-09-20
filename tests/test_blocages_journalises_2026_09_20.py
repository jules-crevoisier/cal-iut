"""Un job écarté par le worker doit laisser une trace lisible dans l'application.

CE QU'ON LISAIT EN PRODUCTION, le 20/09/2026, à chaque passage, à l'identique :

    398 job(s) — 0 réussi(s) — 2 en échec — 30 ignoré(s) —
    25× séance inconnue de la maquette (ex. WR303D-S3-TP-1-but2-dev-fi-tp-c) |
    3× séance non saisissable, enseignant manquant(s) : enseignant JHU sans
       code Celcat |
    2× séance non saisissable, salle manquant(s) : salle « e-102 » sans
       équivalent Celcat

Trente jobs bloqués depuis des jours, réécartés toutes les quatre-vingt-dix
secondes — et **rien dans l'application**. Les cinq endroits qui écartent un
job (`bilan.ignores`) ne journalisaient pas : la colonne « Bloquées » de
l'écran n'était alimentée que par les refus immédiats de `ops.py`, jamais par
le worker. L'information n'existait que dans `docker compose logs`, c'est-à-
dire nulle part pour qui utilise l'outil. La file, elle, ne descendait pas.

    « il faut faire en sorte d'avoir des logs sur ce qu'il se passe, exemple :
      prof non attribué dans Celcat, salle non mappée » (20/09/2026)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    place,
    poser_semaines_celcat,
    seance,
    vider_file,
)
from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state
from cal_iut.celcat import mappings


def _placer(session_id: str, prof: str = "ZZZ"):
    etat = get_state()
    s = seance(session_id, prof=prof)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _sans_ecriture(monkeypatch) -> None:
    def _creer(page, entrees, **kw):
        raise AssertionError("aucune écriture ne doit être tentée")

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)


def _bloques() -> list[dict]:
    from cal_iut.celcat.logs import tous

    return [ligne for ligne in tous() if ligne.get("kind") == "blocked"]


def test_un_enseignant_sans_code_celcat_apparait_dans_le_journal(
    planning, monkeypatch  # noqa: F811
) -> None:
    """LE test du signalement : « prof non attribué dans Celcat » doit se
    lire dans l'application, pas dans les logs Docker."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-sans-prof")
    enfiler({"action": "create", "session_id": "s-sans-prof", "semaine": SEMAINE})
    poser_semaines_celcat()
    _sans_ecriture(monkeypatch)

    drainer_file_immediate(FaussePage())

    lignes = _bloques()
    assert len(lignes) == 1, lignes
    assert lignes[0]["session_id"] == "s-sans-prof"
    assert "enseignant" in lignes[0]["motif"]


def test_une_seance_disparue_de_la_maquette_est_nommee(planning, monkeypatch) -> None:  # noqa: F811
    """Vingt-cinq jobs orphelins tournaient sans que rien ne les nomme."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    enfiler({"action": "create", "session_id": "s-fantome", "semaine": SEMAINE})
    poser_semaines_celcat()

    drainer_file_immediate(FaussePage())

    lignes = _bloques()
    assert [l["session_id"] for l in lignes] == ["s-fantome"]
    assert lignes[0]["motif"] == "séance inconnue de la maquette"


def test_un_blocage_qui_dure_compte_ses_tentatives_sur_une_seule_ligne(
    planning, monkeypatch  # noqa: F811
) -> None:
    """Le worker repasse toutes les 90 s : une ligne par tentative écrirait
    des milliers d'entrées identiques par jour. Le compteur dit depuis
    combien de temps ça dure, ce qu'une ligne seule ne dit pas."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-sans-prof")
    enfiler({"action": "create", "session_id": "s-sans-prof", "semaine": SEMAINE})
    poser_semaines_celcat()
    _sans_ecriture(monkeypatch)

    for _ in range(3):
        drainer_file_immediate(FaussePage())

    lignes = _bloques()
    assert len(lignes) == 1, f"un blocage qui dure reste UNE ligne : {lignes}"
    assert lignes[0]["repetitions"] == 3


def test_mapper_la_salle_debloque_la_seance_au_passage_suivant(
    planning, monkeypatch, tmp_path: Path  # noqa: F811
) -> None:
    """La promesse faite à l'écran : on mappe, et ça repart tout seul — sans
    redéploiement, et sans ré-enfiler quoi que ce soit à la main."""
    monkeypatch.setattr(mappings, "_path", lambda: tmp_path / "celcat_mappings.json")
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    etat = get_state()
    s = seance("s-salle-inconnue", prof="DAN")
    etat.sessions += [s]
    etat.sessions_by_id[s.id] = s
    placement = place(s, week=SEMAINE, day=2)
    # Une salle que `celcat.yaml` ne connaît pas — exactement « e-102 ».
    placement.room_id = "e-102"
    placement.room_label = "E.102"
    etat.timetable += [placement]
    enfiler({"action": "create", "session_id": "s-salle-inconnue", "semaine": SEMAINE})
    poser_semaines_celcat()

    _sans_ecriture(monkeypatch)
    drainer_file_immediate(FaussePage())
    assert any("salle" in l["motif"] for l in _bloques()), _bloques()

    # L'utilisateur mappe la salle depuis l'écran.
    mappings.definir("salles", "e-102", "H.104", par="jules@iut")

    tentees: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        tentees.append(entrees[0].session_id)
        assert entrees[0].salle == "H.104", entrees[0].salle
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 900_001))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: {"room_id": 1})

    bilan = drainer_file_immediate(FaussePage())

    assert tentees == ["s-salle-inconnue"], "la séance doit repartir d'elle-même"
    assert bilan.reussis == 1
