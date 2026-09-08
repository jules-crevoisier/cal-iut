"""Un job qui échoue toujours ne doit pas confisquer la file.

Constaté en production le 08/09/2026, quelques minutes après avoir déployé
le filtre par semaine posée. La file ne bougeait plus :

    504 -> 493 -> 491 -> 491 -> 491 -> 491 …

et chaque passage rendait le même compte rendu : « 24 en échec », toujours
les mêmes séances (`WRA506D…`, les CM en `partial key`). Le worker tournait
pourtant toutes les cinq minutes, VPN pris et rendu, journal écrit.

L'ENCHAÎNEMENT. Un cycle est borné (`limite`) et prend les PREMIERS jobs de
la file. Un job en échec RPC y RESTE — c'est voulu, une panne réseau ou un
Celcat momentanément indisponible doit être réessayé. Mais s'il échoue
systématiquement (une ressource supprimée côté Celcat, un module absent du
catalogue), il reste en tête pour toujours : le cycle suivant reprend les
mêmes vingt-cinq, échoue pareil, et les quatre cent dix jobs derrière ne
sont JAMAIS atteints. Une file bloquée par sa propre tête, pendant que tout
a l'air de tourner normalement.

LE REMÈDE. Après un passage, les jobs tentés-et-échoués repartent en FIN de
file. Rien n'est perdu, rien n'est abandonné : ils seront réessayés, mais
après les autres. C'est la file qui avance au lieu de tourner en rond.

Aucun compteur d'échecs, aucune mise au rebut automatique : un job écarté
en silence est précisément ce qui a coûté trois jours cette semaine. Un job
définitivement impossible reviendra donc à chaque tour de file — et c'est
bien, parce qu'il continue d'apparaître dans le bilan, où on peut le voir.
"""

from __future__ import annotations

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

IDS = {"module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4}


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def test_les_jobs_en_echec_repartent_en_fin_de_file(planning, monkeypatch) -> None:  # noqa: F811
    """LE test de cette correction.

    Deux jobs qui échouent toujours en tête, deux jobs sains derrière, un
    cycle qui n'en prend que deux. Sans rotation, les deux premiers sont
    rejoués indéfiniment et les sains ne partent jamais — c'est la file de
    491 vue en production.
    """
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    for sid in ("s-maudit-1", "s-maudit-2", "s-sain-1", "s-sain-2"):
        _placer(sid)
        enfiler({"action": "create", "session_id": sid, "semaine": SEMAINE})
    poser_semaines_celcat()

    ecrits: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        for e in entrees:
            if e.session_id.startswith("s-maudit"):
                resultat.echecs.append((e.session_id, "ressource supprimée côté Celcat"))
            else:
                ecrits.append(e.session_id)
                resultat.crees.append((e.session_id, 900_000 + len(ecrits)))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    # Premier passage : les deux maudits, rien d'écrit.
    bilan = drainer_file_immediate(FaussePage(), limite=2)
    assert len(bilan.echecs) == 2
    assert ecrits == []

    # Ils doivent maintenant être DERRIÈRE les sains.
    ordre = [str(j.get("session_id")) for j in lister()]
    assert ordre == ["s-sain-1", "s-sain-2", "s-maudit-1", "s-maudit-2"], (
        f"les échecs doivent repartir en fin de file, reçu {ordre}"
    )

    # Second passage : la file avance enfin.
    drainer_file_immediate(FaussePage(), limite=2)
    assert ecrits == ["s-sain-1", "s-sain-2"], (
        "sans rotation, le cycle rejouerait les deux mêmes échecs indéfiniment"
    )


def test_rien_n_est_perdu_par_la_rotation(planning, monkeypatch) -> None:  # noqa: F811
    """Repousser n'est pas jeter. Un job impossible doit revenir à chaque
    tour de file : il continue ainsi d'apparaître dans le bilan, là où on
    peut le voir. Une mise au rebut silencieuse serait exactement la panne
    que cette semaine a passé son temps à réparer."""
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    for sid in ("s-a", "s-b", "s-c"):
        _placer(sid)
        enfiler({"action": "create", "session_id": sid, "semaine": SEMAINE})
    poser_semaines_celcat()

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        for e in entrees:
            resultat.echecs.append((e.session_id, "Celcat indisponible"))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    for _ in range(4):
        drainer_file_immediate(FaussePage(), limite=2)

    restants = {str(j.get("session_id")) for j in lister()}
    assert restants == {"s-a", "s-b", "s-c"}, f"aucun job ne doit disparaître, reçu {restants}"


def test_un_job_ignore_qui_reste_en_file_est_aussi_repousse(planning, monkeypatch) -> None:  # noqa: F811
    """Pas seulement les échecs.

    « séance inconnue de la maquette » est classée IGNORÉE, mais le job
    reste en file — il squattait donc la tête au même titre qu'un échec
    (journaux de production du 08/09/2026 : `WR303D-S3-TD-2`, rejouée à
    chaque cycle). C'est pourquoi la rotation est définie par soustraction —
    tout ce qui a été examiné sans être retiré — plutôt que cas par cas :
    l'énumération avait déjà oublié celui-là.
    """
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    # Aucun placement pour « s-fantome » : elle n'existe pas dans la maquette.
    enfiler({"action": "create", "session_id": "s-fantome", "semaine": SEMAINE})
    _placer("s-vrai")
    enfiler({"action": "create", "session_id": "s-vrai", "semaine": SEMAINE})
    poser_semaines_celcat()

    ecrits: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        for e in entrees:
            ecrits.append(e.session_id)
            resultat.crees.append((e.session_id, 900_001))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    bilan = drainer_file_immediate(FaussePage(), limite=1)

    assert len(bilan.ignores) == 1, "la séance inconnue doit être signalée"
    assert lister()[0].get("session_id") == "s-vrai", (
        "le job ignoré doit repartir derrière, sinon il confisque le cycle"
    )


def test_un_job_arrive_pendant_le_cycle_n_est_pas_perdu(planning, monkeypatch) -> None:  # noqa: F811
    """La rotation réécrit le fichier de file, partagé avec l'API qui y
    enfile en continu. Elle doit donc raisonner sur ce que le fichier
    contient AU MOMENT d'écrire, jamais sur une copie prise au début du
    cycle — sinon un déplacement de séance fait pendant le passage du worker
    serait silencieusement effacé."""
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-echoue")
    enfiler({"action": "create", "session_id": "s-echoue", "semaine": SEMAINE})
    poser_semaines_celcat()

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        # Quelqu'un déplace une séance dans l'application pendant l'écriture.
        enfiler({"action": "update", "session_id": "s-pendant", "event_id": 4242})
        resultat = ResultatEcriture()
        resultat.echecs.append((entrees[0].session_id, "Celcat indisponible"))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    drainer_file_immediate(FaussePage())

    restants = {str(j.get("session_id")) for j in lister()}
    assert "s-pendant" in restants, "un job enfilé pendant le cycle ne doit pas être perdu"
    assert "s-echoue" in restants
