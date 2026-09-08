"""Le journal Celcat doit enregistrer ce qui est ÉCRIT, pas seulement ce qui
est bloqué.

Demande utilisateur 08/09/2026 : « j'aimerais bien une vue qui nous dit en
temps réel les cours modifiés dans cal-iut, leur statut dans Celcat […] un
peu comme un kanban », avec des colonnes par type d'action récente.

Prérequis découvert la veille : `kind="created"`, `"modified"` et
`"deleted"` ne sont écrits NULLE PART dans le code — seul `"blocked"` l'est
(`ops.py`). Les compteurs de l'interface affichent donc `0` en permanence,
que tout marche ou que rien ne marche : c'est ce qui m'a fait croire un
moment que le worker n'avait jamais rien écrit, alors que la preuve réelle
était ailleurs. Un kanban bâti là-dessus aurait des colonnes vides.

L'ANTI-SPAM n'est pas un détail. Le worker repasse toutes les 30 à 60
secondes et retente les jobs en échec, qui restent en file par conception.
Journaliser naïvement chaque tentative écrirait 415 échecs × ~1400 cycles,
soit plus d'un demi-million de lignes par jour — le journal deviendrait
illisible et le fichier ingérable. Une même séance qui échoue pour la même
raison doit occuper UNE ligne, dont on met à jour l'horodatage et le nombre
de tentatives : c'est aussi plus informatif (« échoue depuis 14h, 87
tentatives » plutôt que 87 lignes identiques).
"""

from __future__ import annotations

import pytest

from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée

from cal_iut.celcat import logs


@pytest.fixture(autouse=True)
def _journal_isole(tmp_path, monkeypatch):
    """Le journal est un fichier partagé : ces tests ne doivent pas écrire
    dans celui du dépôt."""
    monkeypatch.setattr(logs, "_path", lambda: tmp_path / "celcat_logs.json")
    yield


def test_une_ecriture_reussie_est_journalisee_avec_de_quoi_la_retrouver() -> None:
    """Sans `event_id` ni `course_code`, une ligne de journal ne permet pas
    d'aller vérifier dans Celcat — donc ne sert qu'à compter."""
    logs.append(kind="created", session_id="WR116-S1-CM-1", event_id=1931709, course_code="WR116")

    item = logs.tous()[0]
    assert item["kind"] == "created"
    assert item["session_id"] == "WR116-S1-CM-1"
    assert item["event_id"] == 1931709
    assert item["course_code"] == "WR116"
    assert item["at"], "un horodatage est indispensable pour un journal chronologique"


def test_les_trois_types_d_ecriture_sont_distingues() -> None:
    logs.append(kind="created", session_id="a")
    logs.append(kind="modified", session_id="b")
    logs.append(kind="deleted", session_id="c")

    assert [i["kind"] for i in logs.tous()] == ["created", "modified", "deleted"]


def test_un_echec_repete_n_occupe_qu_une_ligne() -> None:
    """Le worker retente toutes les 30 à 60 secondes. Sans regroupement, un
    seul job durablement en échec suffirait à noyer le journal."""
    for _ in range(50):
        logs.append(
            kind="echec",
            session_id="WR108-S1-CM-1",
            motif="EUDLDSError : partial key",
            regrouper=True,
        )

    items = logs.tous()
    assert len(items) == 1, f"50 tentatives identiques -> 1 ligne, reçu {len(items)}"
    assert items[0]["repetitions"] == 50, "le nombre de tentatives est ce qui a de la valeur"


def test_un_echec_regroupe_garde_l_horodatage_le_plus_recent() -> None:
    """« Échoue encore » et « a échoué une fois hier » n'appellent pas le
    même geste."""
    logs.append(kind="echec", session_id="s", motif="X", regrouper=True)
    premier = logs.tous()[0]["at"]
    logs.append(kind="echec", session_id="s", motif="X", regrouper=True)

    assert logs.tous()[0]["at"] >= premier


def test_deux_motifs_differents_restent_deux_lignes() -> None:
    """Regrouper ne doit pas fusionner des problèmes distincts : ce sont
    deux choses à corriger."""
    logs.append(kind="echec", session_id="s", motif="salle introuvable", regrouper=True)
    logs.append(kind="echec", session_id="s", motif="partial key", regrouper=True)

    assert len(logs.tous()) == 2


def test_deux_seances_avec_le_meme_motif_restent_deux_lignes() -> None:
    """Le kanban doit montrer COMBIEN de séances sont touchées."""
    logs.append(kind="echec", session_id="s1", motif="partial key", regrouper=True)
    logs.append(kind="echec", session_id="s2", motif="partial key", regrouper=True)

    assert len(logs.tous()) == 2


def test_les_reussites_ne_sont_jamais_regroupees() -> None:
    """Deux créations de la même séance sont deux évènements réels, à des
    moments différents — les fondre perdrait l'historique."""
    logs.append(kind="created", session_id="s", event_id=1)
    logs.append(kind="created", session_id="s", event_id=2)

    assert len(logs.tous()) == 2


def test_un_drainage_reussi_laisse_une_trace_dans_le_journal(planning, monkeypatch) -> None:
    """Bout en bout : ce ne sont pas les fonctions de journal qu'on veut
    vérifier, c'est que le WORKER s'en serve. Écrire dans Celcat sans le
    consigner ramènerait à la situation d'origine — des compteurs à zéro
    alors que le travail est fait."""
    from celcat_sync_helpers import (
        SEMAINE,
        activer_saisie,
        place,
        poser_semaines_celcat,
        seance,
        vider_file,
    )

    from cal_iut.api.state import get_state
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    etat = get_state()
    s = seance("s-journalisee")
    etat.sessions += [s]
    etat.sessions_by_id["s-journalisee"] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]

    vider_file()
    enfiler({"action": "create", "session_id": "s-journalisee", "semaine": SEMAINE})
    poser_semaines_celcat()

    monkeypatch.setattr(
        "cal_iut.celcat.nuit.resoudre_ids",
        lambda *_a, **_k: {
            "module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4
        },
    )

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        r = ResultatEcriture()
        r.crees.append((entrees[0].session_id, 987654))
        return r

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

    drainer_file_immediate(FaussePage())

    traces = [i for i in logs.tous() if i.get("session_id") == "s-journalisee"]
    assert traces, "une création réussie doit laisser une trace"
    assert traces[0]["kind"] == "created"
    assert traces[0]["event_id"] == 987654, "l'event_id permet d'aller vérifier dans Celcat"


def test_le_journal_est_borne_et_garde_les_plus_recentes() -> None:
    """Un fichier qui ne cesse de grossir finit par coûter plus cher qu'il
    ne rend service — et c'est le RÉCENT qu'on consulte."""
    for i in range(logs.MAX_ENTREES + 120):
        logs.append(kind="created", session_id=f"s{i}")

    items = logs.tous()
    assert len(items) == logs.MAX_ENTREES
    assert items[-1]["session_id"] == f"s{logs.MAX_ENTREES + 119}", "la dernière doit survivre"
    assert items[0]["session_id"] != "s0", "les plus anciennes sont écartées"
