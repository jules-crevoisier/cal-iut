"""Un job écarté par le worker doit laisser une trace lisible dans l'application.

CE QU'ON LISAIT EN PRODUCTION, le 20/09/2026, à chaque passage, à l'identique :

    398 job(s) — 0 réussi(s) — 2 en échec — 30 ignoré(s) —
    25× séance sans placement au planning (ex. WR303D-S3-TP-1-but2-dev-fi-tp-c) |
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
    # « sans placement », et non « inconnue de la maquette » : les sept
    # séances de WR303D signalées le 20/09/2026 figuraient toutes à la
    # maquette — elles n'avaient plus de place au planning.
    assert lignes[0]["motif"].startswith("séance sans placement au planning")


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


# --------------------------------------------------------------------------
# Restreindre à la semaine regardée (demande du 20/09/2026)
# --------------------------------------------------------------------------


def _bloquer_en_file(session_id: str, semaine: int, motif: str) -> None:
    """Un job en file ET une ligne de blocage — l'état réel d'une séance que
    le worker écarte à chaque passage."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.logs import append

    enfiler({"action": "create", "session_id": session_id, "semaine": semaine})
    append(kind="blocked", session_id=session_id, motif=motif, regrouper=True)


def _placer_en_semaine(session_id: str, semaine: int):
    """Une séance PLACÉE : c'est son placement, et non son job, qui dit de
    quelle semaine relève son blocage."""
    etat = get_state()
    s = seance(session_id, prof="ZZZ")
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=semaine, day=2)]
    return s


def test_les_blocages_se_limitent_a_la_semaine_regardee(planning) -> None:  # noqa: F811
    """« il faut afficher les séances bloquées de la semaine uniquement »."""
    from cal_iut.api.main import celcat_mappings

    vider_file()
    _placer_en_semaine("s-ici", SEMAINE)
    _placer_en_semaine("s-ailleurs", SEMAINE + 4)
    _bloquer_en_file("s-ici", SEMAINE, "salle « e-102 » sans équivalent Celcat")
    _bloquer_en_file("s-ailleurs", SEMAINE + 4, "enseignant JHU sans code Celcat")

    vue = celcat_mappings(semaine=SEMAINE)

    assert [m["seances"] for m in vue.manquants] == [["s-ici"]]
    assert vue.bloques_autres_semaines == 1, "ce qui bloque ailleurs se compte, il ne se tait pas"


def test_sans_semaine_on_voit_tout(planning) -> None:  # noqa: F811
    from cal_iut.api.main import celcat_mappings

    vider_file()
    _placer_en_semaine("s-ici", SEMAINE)
    _placer_en_semaine("s-ailleurs", SEMAINE + 4)
    _bloquer_en_file("s-ici", SEMAINE, "salle « e-102 » sans équivalent Celcat")
    _bloquer_en_file("s-ailleurs", SEMAINE + 4, "enseignant JHU sans code Celcat")

    vue = celcat_mappings()

    assert len(vue.manquants) == 2
    assert vue.bloques_autres_semaines == 0


def test_un_blocage_dont_le_job_a_quitte_la_file_disparait(planning) -> None:  # noqa: F811
    """Un motif résolu cessait d'être vrai sans cesser d'être affiché : le
    journal garde sa ligne, mais la séance n'attend plus rien."""
    from cal_iut.api.main import celcat_mappings
    from cal_iut.celcat.logs import append

    vider_file()
    append(kind="blocked", session_id="s-reglee", motif="salle « e-102 » sans équivalent", regrouper=True)

    assert celcat_mappings().manquants == []


def test_la_semaine_d_un_blocage_vient_du_placement_pas_du_job(planning) -> None:  # noqa: F811
    """« pourquoi on parle de 303 alors qu'il n'est pas dans les
    différences ? » (20/09/2026).

    Le job porte la semaine pour laquelle il a été enfilé. Si la séance a
    depuis été déplacée, cette semaine ne veut plus rien dire : le blocage se
    rangeait sous une semaine où la comparaison ne mentionne rien."""
    from cal_iut.api.main import celcat_mappings

    vider_file()
    # La séance est PLACÉE en semaine SEMAINE, mais son job dit semaine 9.
    _placer("s-deplacee")
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.logs import append

    enfiler({"action": "create", "session_id": "s-deplacee", "semaine": 9})
    append(kind="blocked", session_id="s-deplacee", motif="enseignant ZZZ sans code", regrouper=True)

    assert [m["seances"] for m in celcat_mappings(semaine=SEMAINE).manquants] == [["s-deplacee"]]
    assert celcat_mappings(semaine=9).manquants == [], "la semaine du job ne fait pas foi"


def test_une_seance_sans_placement_n_appartient_a_aucune_semaine(planning) -> None:  # noqa: F811
    """Elle doit rester visible quelle que soit la semaine regardée, et être
    marquée pour que l'écran la range à part."""
    from cal_iut.api.main import celcat_mappings

    vider_file()
    _bloquer_en_file("s-orpheline", 3, "séance sans placement au planning")

    for semaine in (3, 9, None):
        vue = celcat_mappings(semaine=semaine)
        assert [m["seances"] for m in vue.manquants] == [["s-orpheline"]], semaine
        assert vue.manquants[0]["sans_semaine"] is True


def test_l_ancien_libelle_se_fond_dans_le_nouveau(planning) -> None:  # noqa: F811
    """Le journal garde les lignes écrites avant le 20/09/2026 : sans cette
    fusion, le même blocage s'afficherait deux fois, sous deux formulations."""
    from cal_iut.api.main import celcat_mappings
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.logs import append
    from cal_iut.celcat.nuit import SANS_PLACEMENT

    vider_file()
    enfiler({"action": "create", "session_id": "s-orpheline", "semaine": 3})
    append(kind="blocked", session_id="s-orpheline", motif="séance inconnue de la maquette", regrouper=True)
    append(kind="blocked", session_id="s-orpheline", motif=SANS_PLACEMENT, regrouper=True)

    manquants = celcat_mappings().manquants
    assert len(manquants) == 1, manquants
    assert manquants[0]["motif"] == SANS_PLACEMENT
