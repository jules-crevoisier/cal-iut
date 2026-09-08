"""Un drainage qui n'écrit rien ne doit plus dire « file d'attente drainée ».

Diagnostic du 07/09/2026. Trois signalements distincts — le CM de Régis
Huez déplacé à 15h30 mais resté à 14h dans Celcat, la séance WR120 de
Kyllian Bresson reportée mais toujours présente, un WR118 mal catégorisé —
avaient la même origine : le worker de production n'a JAMAIS réussi une
seule écriture (`created: 0, modified: 0, deleted: 0`, dernière écriture
« jamais »), pendant que 89 modifications attendaient sur les seules
semaines validées.

Rien n'a alerté personne, parce que rien n'était visible. Les logs du
sidecar affichaient toutes les minutes, sereinement :

    Connexion URCA_2026 rôle 985_T_MMI…
    file d'attente drainée (temps réel)
    VPN rendu (session libérée pour le compte partagé)

Or `_consommer_file` ne lisait QUE les succès (`resultat.crees`,
`resultat_m.modifiees`) : `echecs` n'était lu nulle part, et un job dont
l'entrée maquette manquait était abandonné par un `continue` muet. Le job
restait en file — c'est voulu, il faut le retenter — et le message
« drainée » se répétait à l'identique. Une panne totale et une file vide
produisaient exactement la même ligne de journal.

Ces tests fixent le contraire : le bilan porte ce qui a échoué, avec son
motif, pour que la prochaine panne de ce genre se voie dès la première
minute plutôt qu'après plusieurs jours et trois signalements humains.
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
from test_celcat_nuit import GROUP_ID, planning  # noqa: F401 — fixture réutilisée
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state


def test_un_echec_d_ecriture_apparait_dans_le_bilan_avec_son_motif(planning, monkeypatch) -> None:
    """Le cas de Huez : une modification calculée, sans bloquant, qui part
    et qui échoue. Le job reste en file (il faut le retenter), mais le
    motif doit être dit."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()

    def _modifier_qui_echoue(*_a, **_k):
        from cal_iut.celcat.modification import ResultatModification

        resultat = ResultatModification()
        resultat.echecs.append(("s-sem-validee", "ETooManyRecords"))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _modifier_qui_echoue)
    enfiler(
        {
            "action": "update",
            "session_id": "s-sem-validee",
            "event_id": 1931666,
            "group_id": GROUP_ID,
            "semaine": SEMAINE,
        }
    )

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 0
    # Le motif peut être enrichi de la cause d'une résolution d'ids ratée
    # (cf. `test_drainage_lots_2026_09_07`) : on vérifie qu'il PORTE
    # l'erreur, pas qu'il lui est identique.
    assert any(
        sid == "s-sem-validee" and "ETooManyRecords" in motif for sid, motif in bilan.echecs
    ), bilan.echecs
    assert jobs_en_attente(), "un échec RPC reste en file pour la prochaine tentative"
    assert "ETooManyRecords" in bilan.resume()
    assert "0 réussi" in bilan.resume()


def test_un_job_sans_entree_maquette_est_signale_au_lieu_d_etre_saute(planning, monkeypatch) -> None:
    """Le `continue` muet : une séance en file que la maquette ne connaît
    pas restait indéfiniment, sans que rien ne le dise. Elle ne peut pas
    être traitée — raison de plus pour la nommer."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    enfiler({"action": "update", "session_id": "s-inconnue-de-la-maquette", "event_id": 4242})

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 0
    assert any(sid == "s-inconnue-de-la-maquette" for sid, _motif in bilan.ignores)
    assert "s-inconnue-de-la-maquette" in bilan.resume()


def test_un_drainage_qui_reussit_le_dit_aussi(planning, monkeypatch) -> None:
    """Sans quoi on remplacerait un silence trompeur par une alarme
    permanente, tout aussi vite ignorée."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()

    def _modifier_ok(*_a, **_k):
        from cal_iut.celcat.modification import ResultatModification

        resultat = ResultatModification()
        resultat.modifiees.append(("s-sem-validee", 1931666))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _modifier_ok)
    enfiler(
        {
            "action": "update",
            "session_id": "s-sem-validee",
            "event_id": 1931666,
            "group_id": GROUP_ID,
            "semaine": SEMAINE,
        }
    )

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 1
    assert bilan.echecs == []
    assert jobs_en_attente() == []
    assert "1 réussi" in bilan.resume()


def test_une_file_vide_reste_distinguable_d_une_panne(planning) -> None:
    """« rien à faire » et « tout a échoué » ne doivent jamais s'écrire
    pareil : c'est exactement la confusion qui a masqué la panne."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()

    bilan = drainer_file_immediate(FaussePage())

    assert not bilan, "file vide : rien à faire (compatible avec l'ancien retour booléen)"
    assert bilan.en_attente == 0
    assert bilan.echecs == []


def test_les_creations_en_echec_remontent_aussi(planning, monkeypatch) -> None:
    """`creer_manquants` rend ses échecs dans `resultat.echecs` — ils
    étaient ignorés au même titre que ceux des modifications."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    etat = get_state()
    s = seance("s-create-qui-echoue")
    etat.sessions += [s]
    etat.sessions_by_id["s-create-qui-echoue"] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]

    vider_file()
    enfiler({"action": "create", "session_id": "s-create-qui-echoue", "semaine": SEMAINE})
    poser_semaines_celcat()

    def _creer_qui_echoue(*_a, **_k):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        resultat.echecs.append(("s-create-qui-echoue", "RessourceIntrouvable: salle H.999"))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer_qui_echoue)

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 0
    assert any("H.999" in motif for _sid, motif in bilan.echecs)
