"""Le clic sur « mapper » doit se voir tout de suite, pas au passage suivant.

Signalement de Kyllian Bresson, 25/09/2026 : « j'ai l'impression que le clic
sur mapper ne fonctionne pas. »

CE QUI SE PASSAIT. `mappings.definir()` enregistrait bien la correspondance
(`celcat_mappings.json`), et `PUT /celcat/mappings` répondait 200 avec la
liste à jour — mais cette liste (`celcat_mappings()`) construisait
`manquants` à partir des lignes de journal « blocked » dont le job était
encore EN FILE, sans jamais vérifier si une correspondance existait déjà
pour la clé du motif. Le job reste en file tant que le worker ne l'a pas
retenté (jusqu'à 90 s, cf. `nuit.py`) : entre le clic et ce passage, l'écran
réaffichait donc EXACTEMENT le même blocage, avec le même formulaire —
aucune différence visible, alors que la correspondance était bel et bien
enregistrée (vérifiable ailleurs via `GET /celcat/mappings` : elle apparaît
sous « correspondances ajoutées »).

Ce test prouve que `celcat_mappings()` cesse de compter un blocage comme
« manquant » dès qu'une correspondance existe pour sa clé — sans attendre que
le job ait quitté la file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from celcat_sync_helpers import vider_file  # type: ignore[import-not-found]
from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée

from cal_iut.celcat import mappings

pytestmark = pytest.mark.usefixtures("planning")


@pytest.fixture(autouse=True)
def _surcouche_isolee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mappings, "_path", lambda: tmp_path / "celcat_mappings.json")


def _bloquer_en_file(session_id: str, semaine: int, motif: str) -> None:
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.logs import append

    enfiler({"action": "create", "session_id": session_id, "semaine": semaine})
    append(kind="blocked", session_id=session_id, motif=motif, regrouper=True)


def test_mapper_une_salle_retire_aussitot_le_blocage_de_la_liste() -> None:
    from cal_iut.api.main import celcat_mappings
    from cal_iut.celcat.file_attente import lister

    vider_file()
    _bloquer_en_file("s-salle", 5, "salle « e-102 » sans équivalent Celcat")

    # Avant le clic : le blocage est bien là, et le job toujours en file —
    # rien n'a encore retenté quoi que ce soit.
    avant = celcat_mappings(semaine=5)
    assert [m["seances"] for m in avant.manquants] == [["s-salle"]]
    assert any(j["session_id"] == "s-salle" for j in lister())

    # Le clic sur « mapper », côté écran.
    mappings.definir("salles", "e-102", "H.104", par="kyllian@iut")

    # Sans qu'AUCUN worker n'ait tourné entre-temps — le job est encore en
    # file, exactement comme avant le clic —, le blocage doit disparaître de
    # la liste : une correspondance existe désormais pour « e-102 ».
    apres = celcat_mappings(semaine=5)
    assert apres.manquants == [], (
        "le blocage reste affiché comme si le clic sur « mapper » n'avait rien fait"
    )
    assert any(j["session_id"] == "s-salle" for j in lister()), (
        "le job doit rester en file : c'est le worker qui le retentera"
    )
    # La correspondance, elle, doit être visible ailleurs sur l'écran — pas
    # avalée avec le blocage.
    assert [(m.cle, m.valeur) for m in apres.salles] == [("e-102", "H.104")]


def test_mapper_un_enseignant_retire_aussitot_le_blocage() -> None:
    """Même garantie pour un trigramme, en majuscules comme le mappe l'écran."""
    from cal_iut.api.main import celcat_mappings

    vider_file()
    _bloquer_en_file("s-prof", 5, "enseignant JHU sans code Celcat")
    assert len(celcat_mappings(semaine=5).manquants) == 1

    mappings.definir("enseignants", "jhu", "38999", par="kyllian@iut")

    assert celcat_mappings(semaine=5).manquants == []


def test_un_blocage_sans_correspondance_reste_affiche() -> None:
    """Le garde-fou ne doit pas avaler les blocages réels : sans
    correspondance ajoutée, la liste ne doit pas se vider toute seule."""
    from cal_iut.api.main import celcat_mappings

    vider_file()
    _bloquer_en_file("s-salle", 5, "salle « e-102 » sans équivalent Celcat")
    mappings.definir("salles", "autre-salle", "H.999", par="kyllian@iut")

    assert [m["seances"] for m in celcat_mappings(semaine=5).manquants] == [["s-salle"]]
