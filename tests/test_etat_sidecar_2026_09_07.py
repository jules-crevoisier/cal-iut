"""Le worker Celcat doit charger l'état applicatif, comme l'API le fait.

Cause racine trouvée le 07/09/2026, après trois signalements humains (un CM
déplacé resté à son ancienne heure, une séance reportée toujours affichée,
une catégorie fausse) et une journée d'enquête.

Les logs du sidecar, une fois rendus lisibles :

    463 job(s) — 0 réussi(s) — 463 ignoré(s)
    (WR120-S1-TD-1-but1-td-gh : séance inconnue de la maquette; …)

Aucune écriture Celcat n'échouait : elles ne partaient jamais.
`_consommer_file` résout chaque job via `entrees_pour_state(get_state())`,
qui se construit à partir de `state.timetable`. Or `state.py` expose un
`_state = AppState()` VIDE au chargement du module, peuplé par
`main.py::startup()` — l'événement de démarrage de FastAPI. Le sidecar ne
démarre aucune application web : il importe des modules et appelle
`get_state()`, qui lui rend l'état vierge. Toutes les séances lui étaient
donc « inconnues de la maquette », depuis le premier jour.

Le même vide expliquait le reste : `executer_job_nuit` n'enfilait rien
(`state.timetable` vide) puis marquait quand même les semaines comme
`semaines_lancees` — d'où un planning réputé poussé alors que Celcat
n'avait jamais rien reçu.
"""

from __future__ import annotations

from cal_iut.api.state import get_state


def test_charger_etat_applicatif_peuple_ce_dont_le_worker_a_besoin(db_isole) -> None:
    """Sans groupes ni salles ni calendrier, `entrees_pour_state` ne peut
    traduire aucune séance vers Celcat — et le worker ignore tout en
    silence. Cette fonction est le point d'entrée commun à l'API et aux
    scripts du sidecar, précisément pour qu'aucun des deux ne puisse
    l'oublier."""
    from cal_iut.api.main import charger_etat_applicatif

    charger_etat_applicatif()
    state = get_state()

    assert state.groups, "les groupes sont indispensables au nom Celcat du groupe"
    assert state.rooms, "les salles le sont à la résolution de `room_id`"
    assert state.config_dir.exists(), "config_dir doit pointer sur une arborescence réelle"
    assert state.calendar.teaching_mondays, "sans calendrier, aucune date de semaine"


def test_les_scripts_du_sidecar_chargent_l_etat_avant_de_drainer() -> None:
    """Garde-fou de non-régression, volontairement structurel.

    Le défaut ne se voyait NULLE PART : pas d'exception, pas d'échec, un
    worker qui tournait et journalisait sereinement. Ce qui l'a rendu
    possible, c'est qu'un script puisse drainer la file sans jamais avoir
    chargé l'état — ce test refuse que ce soit à nouveau possible sans
    qu'on s'en aperçoive.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1] / "scripts"
    for nom in ("celcat_immediat.py", "celcat_nuit.py"):
        source = (racine / nom).read_text(encoding="utf-8")
        assert "charger_etat_applicatif" in source, (
            f"{nom} draine la file sans charger l'état applicatif : toutes les "
            "séances lui seront « inconnues de la maquette » (panne du 07/09/2026)"
        )
