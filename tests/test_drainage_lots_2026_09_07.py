"""Drainer 489 jobs d'un coup ne marche pas, et n'apprend rien.

Premier drainage réel, 07/09/2026 (après la correction de l'état
applicatif) :

    489 job(s) — 70 réussi(s) — 415 en échec — 4 ignoré(s)

Trois enseignements, trois correctifs ici.

1. LE CYCLE A DURÉ 2h11. Pendant tout ce temps la session VPN du compte
   partagé est restée prise — l'utilisateur ne pouvait pas se connecter à
   Celcat — et rien n'était journalisé : pendant 37 minutes j'ai cru à
   tort que le worker était bloqué, faute de la moindre trace. Un cycle
   doit tenir dans quelques minutes, quitte à reprendre au suivant : la
   file est persistante, il n'y a aucune urgence à tout faire d'un coup.

2. LE RÉSUMÉ MONTRAIT TROIS ÉCHECS SUR 415, pris dans l'ordre d'arrivée.
   Impossible de savoir si c'est un problème massif ou quinze cas isolés,
   donc impossible de prioriser. Ce qu'il faut, c'est la répartition par
   motif.

3. `_ids_pour` AVALAIT SA CAUSE. Il rend `{}` sur n'importe quelle
   exception, et l'écriture échoue plus loin sur « TD exige event_cat_id
   pour [TD] — reçu vide » : un symptôme, jamais la cause. Quelle
   ressource manquait — salle, module, enseignant ? Le message ne le
   disait pas, alors que la réponse était dans l'exception jetée.
"""

from __future__ import annotations

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
from cal_iut.celcat.nuit import BilanDrainage


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


# --------------------------------------------------------------------------
# 2. Le résumé doit dire COMBIEN de fois, pas seulement trois exemples
# --------------------------------------------------------------------------


def test_le_resume_groupe_les_echecs_par_motif() -> None:
    """« 415 en échec » suivi de trois exemples ne permet pas de décider.
    La même erreur répétée 400 fois et 15 cas isolés n'appellent pas le
    même geste."""
    bilan = BilanDrainage(en_attente=10)
    for i in range(6):
        bilan.echecs.append((f"s-{i}", "RPC Celcat : EUDLDSError partial key"))
    for i in range(3):
        bilan.echecs.append((f"t-{i}", "TD exige event_cat_id pour [TD] — reçu vide"))
    bilan.echecs.append(("u-0", "RessourceIntrouvable : salle H.999"))

    resume = bilan.resume()

    assert "6×" in resume and "EUDLDSError partial key" in resume
    assert "3×" in resume and "event_cat_id" in resume
    assert "1×" in resume and "H.999" in resume
    # Le motif le plus fréquent d'abord : c'est celui par lequel commencer.
    assert resume.index("EUDLDSError") < resume.index("event_cat_id")


def test_le_resume_nomme_une_seance_par_motif() -> None:
    """Un compte sans exemple n'est pas actionnable : il faut pouvoir aller
    regarder UNE séance concernée dans Celcat."""
    bilan = BilanDrainage(en_attente=2)
    bilan.echecs.append(("WR108-S1-CM-1", "RPC Celcat : partial key"))

    assert "WR108-S1-CM-1" in bilan.resume()


# --------------------------------------------------------------------------
# 1. Un cycle borné, pour rendre le VPN et reprendre au suivant
# --------------------------------------------------------------------------


def test_le_drainage_s_arrete_apres_la_limite_de_jobs(planning, monkeypatch) -> None:
    """La file est persistante : ce qui n'est pas fait maintenant se fera au
    cycle suivant, VPN rendu entre les deux."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    for i in range(7):
        _placer(f"s-lot-{i}")
        enfiler({"action": "create", "session_id": f"s-lot-{i}", "semaine": SEMAINE})
    poser_semaines_celcat()

    traites: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        traites.append(entrees[0].session_id)
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 900000 + len(traites)))
        return resultat

    # La fausse page ne tient aucun catalogue : sans ça, `_ids_pour` échoue
    # et le job n'atteint jamais l'écriture (comportement voulu depuis que
    # la cause est remontée — cf. le dernier test de ce fichier).
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.resoudre_ids",
        lambda *_a, **_k: {
            "module_id": 1,
            "room_id": 2,
            "staff_id": 3,
            "event_cat_id": 433,
            "dept_id": 4,
        },
    )
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    bilan = drainer_file_immediate(FaussePage(), limite=3)

    assert len(traites) == 3, "le cycle s'arrête à la limite, il ne fait pas les 7"
    assert bilan.reussis == 3
    assert len(jobs_en_attente()) == 4, "le reste attend le prochain cycle, rien n'est perdu"


def test_sans_limite_le_drainage_traite_tout(planning, monkeypatch) -> None:
    """Le comportement par défaut ne change pas : la limite est un choix de
    l'appelant, pas une nouvelle contrainte imposée aux tests existants."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    for i in range(4):
        _placer(f"s-tout-{i}")
        enfiler({"action": "create", "session_id": f"s-tout-{i}", "semaine": SEMAINE})
    poser_semaines_celcat()

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 950001))
        return resultat

    # La fausse page ne tient aucun catalogue : sans ça, `_ids_pour` échoue
    # et le job n'atteint jamais l'écriture (comportement voulu depuis que
    # la cause est remontée — cf. le dernier test de ce fichier).
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.resoudre_ids",
        lambda *_a, **_k: {
            "module_id": 1,
            "room_id": 2,
            "staff_id": 3,
            "event_cat_id": 433,
            "dept_id": 4,
        },
    )
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 4
    assert jobs_en_attente() == []


# --------------------------------------------------------------------------
# 3. La cause, pas le symptôme
# --------------------------------------------------------------------------


def test_une_ressource_introuvable_est_nommee_dans_l_echec(planning, monkeypatch) -> None:
    """Sans ça, l'échec se présente comme « event_cat_id reçu vide » — le
    symptôme du garde-fou, jamais la ressource réellement manquante."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-sans-salle")
    enfiler({"action": "create", "session_id": "s-sans-salle", "semaine": SEMAINE})
    poser_semaines_celcat()

    def _resoudre_qui_echoue(*_a, **_k):
        from cal_iut.celcat.ecriture import RessourceIntrouvable

        raise RessourceIntrouvable("salle H.999")

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", _resoudre_qui_echoue)

    bilan = drainer_file_immediate(FaussePage())

    assert any("H.999" in motif for _sid, motif in bilan.echecs), (
        f"la ressource manquante doit être nommée, reçu : {bilan.echecs}"
    )
    assert bilan.reussis == 0
