"""Le cycle se borne en TEMPS, plus en nombre de jobs.

Demande de Jules Crevoisier, 09/09/2026 : « j'en ai marre du 20 par 20,
pourquoi on passe pas tous d'un coup ? ».

CE QU'IL FALLAIT BORNER A TOUJOURS ÉTÉ LA DURÉE. Le premier drainage réel a
tenu 2h11 sur 489 jobs, session du compte Celcat — PARTAGÉ avec l'équipe —
prise du début à la fin. Le plafond de 25 jobs par cycle en était le proxy,
calibré sur ces ~16 secondes par job.

Ce coût-là n'existe plus. Il venait de trois choses, toutes corrigées
depuis :

- six résolutions RPC par job, mises en cache par cycle le 08/09/2026 ;
- le scan des matières : 88 chargements d'EDT plus une centaine de balayages
  de plages à CHAQUE module introuvable (#151) ;
- la résolution des groupes, qui échouait et repartait en balayage (#150).

Un plafond calibré sur l'ancien coût borne aujourd'hui la mauvaise
grandeur : il découpe en cinq passages ce qui tient en un, et fait payer
cinq fois le montage du VPN, la connexion et la déconnexion.

D'où l'échange : `--limite` passe à 0 (tous), et `--duree-max` (600 s) borne
ce qui doit l'être. Ce qui dépasse reste en file et repart au cycle suivant
— elle est persistante, rien ne se perd.

L'HORLOGE EST FAUSSE DANS CES TESTS, et c'est délibéré : un test qui
dormirait vraiment pour dépasser un budget serait lent ET flottant. Le faux
`monotonic` avance d'un pas fixe à chaque consultation, ce qui rend le
moment de l'arrêt exactement prévisible.
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


class _Horloge:
    """`monotonic` qui avance d'un pas fixe à chaque appel."""

    def __init__(self, pas: float = 1.0) -> None:
        self.maintenant = 0.0
        self.pas = pas

    def __call__(self) -> float:
        valeur = self.maintenant
        self.maintenant += self.pas
        return valeur


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _ids_resolus(monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.resoudre_ids",
        lambda *_a, **_k: {
            "module_id": 1, "room_id": 2, "staff_id": 3,
            "event_cat_id": 433, "dept_id": 4,
        },
    )


def _creations_comptees(monkeypatch) -> list[str]:
    traites: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        traites.append(entrees[0].session_id)
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 900000 + len(traites)))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    return traites


def _enfiler_creations(combien: int, prefixe: str) -> None:
    from cal_iut.celcat.file_attente import enfiler

    vider_file()
    for i in range(combien):
        _placer(f"{prefixe}-{i}")
        enfiler({"action": "create", "session_id": f"{prefixe}-{i}", "semaine": SEMAINE})
    poser_semaines_celcat()


# --------------------------------------------------------------------------


def test_sans_plafond_de_nombre_toute_la_file_passe_en_un_cycle(
    planning, monkeypatch  # noqa: F811
) -> None:
    """LA demande. 30 jobs, un seul passage — plus de découpage en lots."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creations(30, "s-tout")
    _ids_resolus(monkeypatch)
    traites = _creations_comptees(monkeypatch)

    bilan = drainer_file_immediate(FaussePage())

    assert len(traites) == 30, f"les 30 doivent passer d'un coup, reçu {len(traites)}"
    assert bilan.reussis == 30
    assert jobs_en_attente() == []
    assert bilan.interrompu == "", "rien ne borne un cycle sans budget"


def test_le_budget_de_temps_arrete_le_cycle_et_le_dit(
    planning, monkeypatch  # noqa: F811
) -> None:
    """Le remplaçant du plafond. Horloge à 1 s par consultation, budget 3 s.

    DEUX jobs passent, pas trois : le premier appel est `debut`, puis la
    vérification PRÉCÈDE le travail. Les contrôles tombent donc à t=1 et t=2
    (dans le budget), et celui de t=3 l'arrête. Compter à l'envers ici
    ferait un test qui passe pour la mauvaise raison.
    """
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creations(10, "s-budget")
    _ids_resolus(monkeypatch)
    traites = _creations_comptees(monkeypatch)
    monkeypatch.setattr("cal_iut.celcat.nuit.monotonic", _Horloge(1.0))

    bilan = drainer_file_immediate(FaussePage(), duree_max_s=3.0)

    assert len(traites) == 2, f"2 jobs tiennent dans 3 s, reçu {len(traites)}"
    assert bilan.reussis == 2
    assert "budget" in bilan.interrompu, (
        "un cycle qui s'arrête sans le dire ressemble à un cycle qui a tout "
        f"fait — reçu {bilan.interrompu!r}"
    )
    assert bilan.interrompu in bilan.resume()


def test_ce_qui_depasse_le_budget_reste_en_file(planning, monkeypatch) -> None:  # noqa: F811
    """Rien ne se perd : la file est persistante, le reste repart au cycle
    suivant. C'est ce qui rend le budget acceptable."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creations(10, "s-reste")
    _ids_resolus(monkeypatch)
    _creations_comptees(monkeypatch)
    monkeypatch.setattr("cal_iut.celcat.nuit.monotonic", _Horloge(1.0))

    drainer_file_immediate(FaussePage(), duree_max_s=3.0)

    assert len(jobs_en_attente()) == 8, (
        f"les 8 non traités doivent rester, reçu {len(jobs_en_attente())}"
    )


def test_un_budget_nul_ne_borne_rien(planning, monkeypatch) -> None:  # noqa: F811
    """Non-régression : `duree_max_s=0` est « sans limite », pas « budget
    déjà épuisé » — la confusion viderait chaque cycle de tout travail."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creations(5, "s-nul")
    _ids_resolus(monkeypatch)
    traites = _creations_comptees(monkeypatch)
    monkeypatch.setattr("cal_iut.celcat.nuit.monotonic", _Horloge(1000.0))

    drainer_file_immediate(FaussePage(), duree_max_s=0.0)

    assert len(traites) == 5


def test_le_plafond_en_nombre_reste_disponible(planning, monkeypatch) -> None:  # noqa: F811
    """`--limite` n'est pas supprimé, seulement retiré du chemin par défaut :
    il reste utile pour un passage manuel prudent."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creations(7, "s-limite")
    _ids_resolus(monkeypatch)
    traites = _creations_comptees(monkeypatch)

    drainer_file_immediate(FaussePage(), limite=3)

    assert len(traites) == 3


def test_le_worker_ne_decoupe_plus_par_defaut() -> None:
    """Les défauts du script du sidecar — c'est LUI qui tourne toutes les 30
    secondes en production, pas `drainer_file_immediate` appelée à la main.

    Lus dans l'AST plutôt que par une comparaison de texte : le test doit
    survivre à une reformulation de l'aide ou à un retour à la ligne.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "celcat_immediat.py"
    ).read_text(encoding="utf-8")

    defauts: dict[str, object] = {}
    for noeud in ast.walk(ast.parse(source)):
        if not (isinstance(noeud, ast.Call) and noeud.args):
            continue
        cible = noeud.args[0]
        if not (isinstance(cible, ast.Constant) and str(cible.value).startswith("--")):
            continue
        for mot in noeud.keywords:
            if mot.arg == "default" and isinstance(mot.value, ast.Constant):
                defauts[str(cible.value)] = mot.value.value

    assert defauts.get("--limite") == 0, (
        f"le worker doit prendre TOUTE la file par défaut, reçu {defauts.get('--limite')}"
    )
    assert defauts.get("--duree-max"), "le budget de temps doit borner le cycle"
