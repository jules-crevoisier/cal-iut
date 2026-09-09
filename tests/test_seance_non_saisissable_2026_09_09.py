"""Une séance à qui il manque une donnée n'est pas retentée toutes les 90 s.

CE QU'ON LISAIT EN PRODUCTION, 09/09/2026, à chaque cycle, à l'identique :

    99 job(s) — 0 réussi(s) — 14 en échec —
    7× TP exige event_cat_id pour [TP] — reçu vide
       [ids irrésolus : RessourceIntrouvable : personnel None]
       (ex. WR303D-S3-TP-2-but2-dev-fi-tp-a)
    7× TD exige event_cat_id pour [TD] — reçu vide
       [ids irrésolus : RessourceIntrouvable : personnel None]
       (ex. WRA303M-S3-TD-1-but2-creacom-fc-td-gh)

« personnel None » nomme le CHAMP, jamais la raison. Et la raison était
déjà connue : `mapping.py` la range dans `entree.bloquants` au moment de
construire l'entrée — « aucun enseignant », « enseignant PTU sans code
Celcat ». Le drainage ne l'a jamais lue.

Deux conséquences, la seconde pire que la première :

1. le message n'aidait personne à réparer ;
2. le job repartait à CHAQUE cycle, indéfiniment, alors qu'aucun passage ne
   pouvait inventer l'enseignant qui manque au planning. Quatorze jobs
   condamnés à tourner, avec toutes les apparences du travail.

CE QUI N'EST PAS BLOQUÉ, et c'est délibéré. Une séance à deux intervenants
porte elle aussi un bloquant — « Celcat n'en accepte qu'un, à trancher à la
main » — mais elle s'écrit très bien avec le premier déclaré. Bloquer sur
`bloquants` non vide l'aurait arrêtée aussi. On ne bloque donc que sur les
trois champs que `resoudre_ids` exige vraiment, lus sur l'entrée elle-même :
enseignant, matière, salle. Signaler n'est pas empêcher.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    jobs_en_attente,
    place,
    poser_semaines_celcat,
    seance,
    vider_file,
)
from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state
from cal_iut.celcat.nuit import motif_non_saisissable


def _entree(**kw):
    base = {
        "session_id": "WR303D-S3-TP-2-but2-dev-fi-tp-a",
        "code_enseignant": "39757",
        "code_module": "TSBZ303D",
        "salle": "H.005",
        "bloquants": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------
# Le motif
# --------------------------------------------------------------------------


def test_une_entree_complete_ne_bloque_rien() -> None:
    assert motif_non_saisissable(_entree()) == ""


@pytest.mark.parametrize(
    ("champ", "attendu"),
    [
        ("code_enseignant", "enseignant"),
        ("code_module", "matière"),
        ("salle", "salle"),
    ],
)
def test_chacun_des_trois_champs_exiges_bloque_et_se_nomme(champ, attendu) -> None:
    """Les trois que `resoudre_ids` traduit sinon en « ... None »."""
    motif = motif_non_saisissable(_entree(**{champ: None}))

    assert attendu in motif, motif
    assert "non saisissable" in motif


def test_le_motif_reprend_la_raison_deja_connue_de_mapping() -> None:
    """LE point. « enseignant PTU sans code Celcat » se répare ;
    « personnel None » ne dit à personne quoi faire."""
    motif = motif_non_saisissable(
        _entree(code_enseignant=None, bloquants=["enseignant PTU sans code Celcat"])
    )

    assert "enseignant PTU sans code Celcat" in motif


def test_une_seance_a_deux_intervenants_n_est_pas_bloquee() -> None:
    """Elle porte un bloquant, mais s'écrit très bien avec le premier
    déclaré. Bloquer sur `bloquants` non vide l'aurait arrêtée."""
    entree = _entree(
        bloquants=["2 enseignants (MRI, DAN) : Celcat n'en accepte qu'un, à trancher à la main"]
    )

    assert motif_non_saisissable(entree) == ""


# --------------------------------------------------------------------------
# Le drainage
# --------------------------------------------------------------------------


def _placer(session_id: str, prof: str):
    etat = get_state()
    s = seance(session_id, prof=prof)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _sans_ecriture(monkeypatch) -> list[str]:
    tentees: list[str] = []

    def _creer(page, entrees, **kw):
        tentees.append(entrees[0].session_id)
        raise AssertionError("aucune écriture ne doit être tentée")

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    return tentees


def test_une_seance_sans_enseignant_connu_n_est_pas_tentee(
    planning, monkeypatch  # noqa: F811
) -> None:
    """« ZZZ » n'est dans aucune table : `code_enseignant` reste None, comme
    pour les 14 jobs de production."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-sans-prof", prof="ZZZ")
    enfiler({"action": "create", "session_id": "s-sans-prof", "semaine": SEMAINE})
    poser_semaines_celcat()
    tentees = _sans_ecriture(monkeypatch)

    bilan = drainer_file_immediate(FaussePage())

    assert tentees == [], "on n'essaie pas ce qui ne peut pas aboutir"
    assert bilan.echecs == [], f"ce n'est pas un échec, c'est une donnée absente : {bilan.echecs}"
    motifs = [m for _sid, m in bilan.ignores]
    assert any("non saisissable" in m for m in motifs), motifs
    assert any("enseignant" in m for m in motifs), motifs


def test_la_seance_bloquee_reste_en_file(planning, monkeypatch) -> None:  # noqa: F811
    """Le jour où l'enseignant est affecté, le job repart tout seul : le
    retirer obligerait à le ré-enfiler à la main."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-reste-bloquee", prof="ZZZ")
    enfiler({"action": "create", "session_id": "s-reste-bloquee", "semaine": SEMAINE})
    poser_semaines_celcat()
    _sans_ecriture(monkeypatch)

    drainer_file_immediate(FaussePage())

    assert [j["session_id"] for j in jobs_en_attente()] == ["s-reste-bloquee"]


def test_le_resume_montre_les_motifs_bloquants(planning, monkeypatch) -> None:  # noqa: F811
    """Le résumé n'affichait que DEUX motifs d'ignorés : sur quatorze jobs
    bloqués pour des raisons différentes, douze restaient invisibles."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    for i in range(3):
        _placer(f"s-bloq-{i}", prof="ZZZ")
        enfiler({"action": "create", "session_id": f"s-bloq-{i}", "semaine": SEMAINE})
    poser_semaines_celcat()
    _sans_ecriture(monkeypatch)

    bilan = drainer_file_immediate(FaussePage())

    assert "3 ignoré(s)" in bilan.resume()
    assert "non saisissable" in bilan.resume()


def test_une_seance_complete_passe_toujours(planning, monkeypatch) -> None:  # noqa: F811
    """Non-régression : le garde-fou ne doit pas arrêter ce qui marchait."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-complete", prof="MRI")
    enfiler({"action": "create", "session_id": "s-complete", "semaine": SEMAINE})
    poser_semaines_celcat()

    ecrites: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        ecrites.append(entrees[0].session_id)
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 987654))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.resoudre_ids",
        lambda *_a, **_k: {
            "module_id": 1, "room_id": 2, "staff_id": 3,
            "event_cat_id": 433, "dept_id": 4,
        },
    )

    bilan = drainer_file_immediate(FaussePage())

    assert ecrites == ["s-complete"]
    assert bilan.reussis == 1
