"""`cal-iut completer` doit voir les VRAIES contraintes enseignant, pas
seulement `teacher_availability.yaml`.

Trouvé le 27/08/2026 en auditant un run complété via cette commande : 90
séances placées sur des créneaux que l'enseignant avait pourtant explicitement
déclarés indisponibles. Cause — `cmd_completer` chargeait
`teacher_availability.yaml` SEUL, sans le fusionner avec les contraintes
extraites du CSV établissement (`load_all_constraints` ->
`merge_teacher_availability`), contrairement à `api/main.py::startup()`.

Isolé dans `_construire_etat_pour_completion` pour être testable sans lancer
une complétion complète (potentiellement des dizaines de minutes) : ce module
ne teste que la CONSTRUCTION de l'état, pas le placement lui-même.
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.api.state import get_state
from cal_iut.cli import _construire_etat_pour_completion
from cal_iut.ingestion.config_loader import load_teacher_availability

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"


def test_les_enseignants_du_csv_etablissement_sont_bien_presents():
    """Sans la fusion, seule la poignée d'enseignants du YAML illustratif
    (FLI, AFR, ALO, JUL, KBR) serait visible — pas les ~23 du CSV réel."""
    etat = _construire_etat_pour_completion(ROOT)
    codes = {t.teacher_code for t in etat.teacher_availability}
    seuls_dans_yaml = {t.teacher_code for t in load_teacher_availability(CONFIG)}
    assert len(codes) > len(seuls_dans_yaml), (
        "aucun enseignant en plus du YAML illustratif : la fusion CSV a-t-elle disparu ?"
    )


def test_un_enseignant_du_yaml_et_du_csv_garde_les_deux_contraintes():
    """FLI porte une indisponibilité YAML (pré-rentrée du 3/09, cf.
    docs/DATA.md §66) ET, très probablement, des contraintes issues du CSV —
    la fusion doit garder les deux, pas remplacer l'une par l'autre."""
    etat = _construire_etat_pour_completion(ROOT)
    par_code = {t.teacher_code: t for t in etat.teacher_availability}
    assert "FLI" in par_code
    fli = par_code["FLI"]
    assert any(r.date == "2026-09-03" for r in fli.forbidden_date_slots), (
        "l'indisponibilité déclarée en YAML a disparu après fusion"
    )


def test_les_semaines_de_presence_fc_sont_chargees():
    """Sans elles, la complétion pourrait placer un cours FC pendant que
    l'étudiant est en entreprise (cf. test_alternance_fc_2026_08_27.py)."""
    etat = _construire_etat_pour_completion(ROOT)
    assert etat.student_presences, "aucune présence FC chargée"


def test_deux_appels_consecutifs_donnent_le_meme_resultat():
    """La construction ne doit dépendre d'aucun état résiduel laissé par un
    appel précédent (l'état applicatif est un singleton global, cf.
    `api/state.py::get_state`)."""
    premier = {t.teacher_code for t in _construire_etat_pour_completion(ROOT).teacher_availability}
    second = {t.teacher_code for t in _construire_etat_pour_completion(ROOT).teacher_availability}
    assert premier == second


def test_ne_touche_pas_au_planning_deja_charge():
    """Cette fonction ne construit QUE le contexte (règles, calendrier,
    salles) — `cmd_completer` reste seul responsable de charger les séances et
    le planning à compléter, propres à chaque fichier traité. Sans cette
    séparation, un appel répété pourrait écraser un planning en cours de
    complétion."""
    etat = get_state()
    etat.timetable = ["sentinelle"]
    _construire_etat_pour_completion(ROOT)
    assert etat.timetable == ["sentinelle"]
