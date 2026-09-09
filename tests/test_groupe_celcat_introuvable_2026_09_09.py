"""Un groupe absent de la table ne doit RIEN écrire — et surtout pas un
`group_id` à zéro.

L'ENQUÊTE. Kyllian Bresson demande le 09/09/2026 ce que veut dire, sur dix
cours, « Une des ressources affectées a été supprimée ». Le journal de
production en comptait 17, tous sur les mêmes deux groupes :

    17× RPC Celcat : {'code': 'EUDLDSError', 'message': "Impossible
    d'enregistrer l'événement, une des ressources affectées a été
    supprimée"}   (ex. WRA507D-S5-TD-5-but3-dev-fc-td-ef)

Rien n'avait été supprimé. `data/config/celcat_groupes.yaml` ne contenait
que trois groupes de S5 (TD AB, TP A, TP B) ; les BUT3 en alternance sont
sur `BUT MMI S5 TD EF` et `BUT MMI S5 TD GH`, qui existent bel et bien dans
Celcat (1662681 et 1662684, retrouvés par balayage de `recordIDs`) mais
manquaient à la table. La résolution échouait, `_group_id_pour` rendait
`0`, et l'écriture partait quand même avec `groups: [{group_id: 0}]` — d'où
un message Celcat qui parlait de suppression.

C'EST LA MÊME CAUSE QUE « matière introuvable ». `udlResources.load` refuse
d'énumérer les matières ET les groupes (`ETooManyRecords`). Les deux
catalogues sont donc devinés depuis des relevés partiels, et les deux
échouent sur la même population : les formations en alternance, jamais
posées jusqu'ici. Seule la façon d'échouer diffère — et c'est ce qui a
rendu l'une lisible (« RessourceIntrouvable : matière TSBZC01M ») et
l'autre indéchiffrable.

LE PIÈGE, plus grave que le message. En modification, `localiser_evenement(
..., group_ids=[0])` ne trouve rien et lève « absent des group_ids » —
exactement le motif que `_evenement_a_disparu` interprète comme « cet
évènement n'existe plus ». Le journal oubliait alors l'`event_id` d'un
évènement bien vivant, et le passage suivant en créait un second. Une table
de groupes incomplète fabriquait des doublons.
"""

from __future__ import annotations

import re
from pathlib import Path

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
from cal_iut.celcat import ecriture
from cal_iut.celcat.ecriture import (
    RessourceIntrouvable,
    _groupes_connus,
    _normaliser_groupe,
    _trouver_groupe,
)
from cal_iut.celcat.nuit import _evenement_a_disparu, motif_groupe_absent

CHEMIN = Path(__file__).resolve().parents[1] / "data" / "config" / "celcat_groupes.yaml"


class _Entree:
    nom_groupe_celcat = "BUT MMI S5 TD EF"
    course_code = "WRA507D"


# --------------------------------------------------------------------------
# La table elle-même
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nom",
    [
        "BUT MMI S5 TD EF",   # but3-dev-fc-td-ef     — les 17 échecs
        "BUT MMI S5 TD GH",   # but3-creacom-fc-td-gh
        "BUT MMI S5 TD AB",   # but3-dev-fi-td-ab
        "BUT MMI S3 TD GH",   # but2-creacom-fc-td-gh
    ],
)
def test_les_groupes_des_alternants_sont_dans_la_table(nom: str) -> None:
    """Les quatre groupes de BUT2/BUT3 sur lesquels la file butait."""
    assert nom in _groupes_connus(), (
        f"{nom} absent de {CHEMIN.name} : la saisie repartira sur group_id=0"
    )


def test_aucun_identifiant_de_groupe_n_est_partage() -> None:
    """Deux noms sur le même id écriraient l'un sur l'autre. Le relevé du
    09/09 en contenait un piège : « BUT MMI S4 TP G » (1654830) existe à
    côté de « BUT MMI S4 TP G - 2024 » (1662345) — seul le second est de la
    bonne cohorte."""
    connus = _groupes_connus()
    doublons = {v for v in connus.values() if list(connus.values()).count(v) > 1}
    assert not doublons, f"identifiants partagés : {doublons}"


def test_la_table_couvre_les_six_semestres_sauf_les_cm_absents_de_celcat() -> None:
    """Balayage complet de 1600000 à 1710000 le 09/09/2026 : aucun groupe
    MMI en dehors de 1640000-1670000, et pas de « BUT MMI S5 CM » ni de
    « BUT MMI S6 CM ». Les promotions BUT3 n'ont donc PAS de groupe CM côté
    Celcat — le constater ici évite de croire à un oubli de relevé."""
    cm = {n for n in _groupes_connus() if n.endswith(" CM")}
    assert cm == {f"BUT MMI S{i} CM" for i in (1, 2, 3, 4)}, cm


# --------------------------------------------------------------------------
# La résolution
# --------------------------------------------------------------------------


def test_un_nom_inconnu_est_un_refus_pas_un_zero() -> None:
    with pytest.raises(RessourceIntrouvable):
        _trouver_groupe(None, "groupe BUT MMI S9 TD ZZ", "BUT MMI S9 TD ZZ")


def test_un_nom_tronque_n_accroche_pas_un_groupe_voisin() -> None:
    """LE danger introduit par une table complète : la comparaison était
    « préfixe de » dans les deux sens. « BUT MMI S5 » aurait désigné
    « BUT MMI S5 TD AB » et déversé une promotion sur le mauvais groupe."""
    with pytest.raises(RessourceIntrouvable):
        _trouver_groupe(None, "groupe BUT MMI S5", "BUT MMI S5")


@pytest.mark.parametrize(
    "ecrit",
    ["BUT MMI S5 TD EF", "but mmi s5 td ef", "BUT  MMI   S5  TD EF", "BUT MMI S5 TD EF - 2024"],
)
def test_la_casse_les_espaces_et_la_cohorte_ne_font_pas_echouer(ecrit: str) -> None:
    assert _normaliser_groupe(ecrit) == "BUT MMI S5 TD EF"


# --------------------------------------------------------------------------
# Le motif de refus
# --------------------------------------------------------------------------


def test_le_motif_nomme_le_groupe_et_le_fichier_a_corriger() -> None:
    motif = motif_groupe_absent(_Entree())
    assert "BUT MMI S5 TD EF" in motif
    assert "celcat_groupes.yaml" in motif


def test_le_motif_ne_passe_pas_pour_un_evenement_disparu() -> None:
    """SANS CE TEST, le correctif serait pire que le mal. `marquer_supprime`
    oublie l'`event_id` du journal ; l'appliquer à un groupe manquant ferait
    recréer une séance qui existe déjà."""
    assert not _evenement_a_disparu(motif_groupe_absent(_Entree()))


def test_le_fichier_ne_contient_que_des_noms_de_groupes_bien_formes() -> None:
    """Un nom mal formé ne lèverait rien : il ne correspondrait simplement
    jamais, et rendrait le groupe silencieusement introuvable."""
    for nom in _groupes_connus():
        assert re.fullmatch(r"BUT MMI S\d (CM|TD [A-Z]{2}|TP [A-Z])", nom), nom


@pytest.fixture(autouse=True)
def _table_relue() -> None:
    """`_GROUPES` est un cache de module : le vider évite qu'un autre test
    l'ait rempli depuis un fichier temporaire."""
    ecriture._GROUPES = None
    yield
    ecriture._GROUPES = None


# --------------------------------------------------------------------------
# Le drainage : rien ne part chez Celcat, et le journal n'est pas amputé
# --------------------------------------------------------------------------


EVENT_ID_VIVANT = 1933241


def _seance_placee(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _journaliser_event_id(session_id: str, event_id: int) -> None:
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    journal = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}
    journal[session_id] = {"event_id": str(event_id), "semaine": SEMAINE}
    doc["journal"] = journal
    sauver(doc)


def _event_id_journalise(session_id: str) -> str | None:
    from cal_iut.celcat.etat import charger

    journal = charger().get("journal") or {}
    row = journal.get(session_id) or {}
    return row.get("event_id")


def _groupe_irresoluble(monkeypatch) -> None:
    """Reproduit l'état de la production le 09/09 : le nom du groupe ne
    répond à rien, donc `_group_id_pour` retombe sur 0."""

    def _refus(*_a: object, **_k: object) -> int:
        raise RessourceIntrouvable("groupe BUT MMI S5 TD EF")

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", _refus)


def test_une_creation_sans_groupe_n_ecrit_rien_et_dit_pourquoi(
    planning, monkeypatch  # noqa: F811
) -> None:
    """C'ÉTAIT le bug. L'écriture partait avec `groups: [{group_id: 0}]` et
    Celcat répondait « une des ressources affectées a été supprimée »."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _seance_placee("s-groupe-inconnu")
    vider_file()
    enfiler({"action": "create", "session_id": "s-groupe-inconnu", "semaine": SEMAINE})
    poser_semaines_celcat()
    _groupe_irresoluble(monkeypatch)

    appels: list = []
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.creer_manquants",
        lambda *a, **k: appels.append(k) or (_ for _ in ()).throw(AssertionError("écriture")),
    )

    bilan = drainer_file_immediate(FaussePage())

    assert appels == [], "aucune écriture ne doit partir avec un group_id à 0"
    motifs = [m for _, m in bilan.echecs]
    assert any("celcat_groupes.yaml" in m for m in motifs), motifs
    assert jobs_en_attente(), "le job reste en file : il redeviendra saisissable"


def test_une_modification_sans_groupe_ne_fait_pas_oublier_l_event_id(
    planning, monkeypatch  # noqa: F811
) -> None:
    """LE piège le plus coûteux. `localiser_evenement(..., group_ids=[0])`
    lève « absent des group_ids », que `_evenement_a_disparu` prend pour une
    suppression : l'event_id serait effacé du journal et la séance recréée
    en DOUBLON au passage suivant."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _seance_placee("s-maj-groupe-inconnu")
    _journaliser_event_id("s-maj-groupe-inconnu", EVENT_ID_VIVANT)
    vider_file()
    enfiler(
        {
            "action": "update",
            "session_id": "s-maj-groupe-inconnu",
            "event_id": EVENT_ID_VIVANT,
            "semaine": SEMAINE,
        }
    )
    poser_semaines_celcat()
    _groupe_irresoluble(monkeypatch)
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.modifier_manquants",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("écriture")),
    )

    drainer_file_immediate(FaussePage())

    assert _event_id_journalise("s-maj-groupe-inconnu") == str(EVENT_ID_VIVANT), (
        "l'évènement existe toujours dans Celcat : oublier son event_id "
        "ferait créer un doublon au passage suivant"
    )
