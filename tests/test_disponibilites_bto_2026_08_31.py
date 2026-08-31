"""Disponibilités réelles de Barthélémy Tomasina, redonnées le 31/08/2026.

Le questionnaire source portait une ligne mal formée — « mardi après-midi -
mardi » — que le parseur lit comme DEUX indisponibilités distinctes, la
seconde couvrant tout le mardi. Combinée à « lundi toute la journée » et
« vendredi toute la journée », l'ancienne donnée bloquait BTO les lundis et
vendredis toute l'année, bien au-delà de ce qu'il avait réellement déclaré.

Kyllian Bresson a transmis les vraies disponibilités : un code couleur par
demi-journée (bleu/idéal, noir/acceptable, rouge/impossible), semaine par
semaine, du 31 août au 23 octobre 2026 (semaines 2 à 9). Elles remplacent
l'ancienne indisponibilité récurrente, via `cancelled_forbidden_slots` — le
mécanisme qui permet à une entrée YAML d'ANNULER un blocage venu du JSON de
contraintes plutôt que de seulement s'y ajouter (`merge_teacher_availability`
UNIT les deux sources par défaut).

Trois règles à vérifier tiennent lieu de spécification :
  - aucun matin disponible avant le 5 octobre (S7) ;
  - le mercredi est impossible sur les huit semaines, sans exception ;
  - la semaine 2 (31 août-4 sept.) est entièrement exclue.
Et un point de cohérence signalé par l'utilisateur : le jeudi 22 octobre est
le seul jour NON-mercredi entièrement bloqué sur toute la période.
"""

from pathlib import Path

from cal_iut.ingestion.config_loader import load_teacher_availability
from cal_iut.ingestion.constraints_loader import merge_teacher_availability, parse_teacher_constraints_json

CONFIG_DIR = Path(__file__).resolve().parents[1] / "data" / "config"
CONTRAINTES = Path(__file__).resolve().parents[1] / "contraintes" / "05_enseignants_contraintes.json"


def _bto():
    yaml_teachers = load_teacher_availability(CONFIG_DIR)
    csv_teachers, _ = parse_teacher_constraints_json(CONTRAINTES)
    fusion = merge_teacher_availability(yaml_teachers, csv_teachers)
    return next(t for t in fusion if t.teacher_code == "BTO")


def test_la_fausse_indisponibilite_recurrente_est_entierement_annulee():
    """Plus aucun (jour, créneau) récurrent : tout venait du questionnaire
    mal formé, tout est remplacé par des dates précises."""
    bto = _bto()
    assert bto.forbidden_slots == []


def test_aucun_matin_disponible_avant_octobre():
    dates = {x.date for x in _bto().forbidden_date_slots}
    matins_septembre = [
        "2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29",
    ]
    for d in matins_septembre:
        assert d in dates, f"{d} devrait bloquer au moins le matin"


def test_le_mercredi_est_impossible_sur_les_huit_semaines():
    by_date = {x.date: set(x.slots) for x in _bto().forbidden_date_slots}
    mercredis = [
        "2026-09-02", "2026-09-09", "2026-09-16", "2026-09-23", "2026-09-30",
        "2026-10-07", "2026-10-14", "2026-10-21",
    ]
    for d in mercredis:
        assert by_date.get(d) == {0, 1, 2, 3, 4, 5}, f"{d} (mercredi) doit être bloqué toute la journée"


def test_la_semaine_2_est_entierement_exclue():
    by_date = {x.date: set(x.slots) for x in _bto().forbidden_date_slots}
    for d in ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
        assert by_date.get(d) == {0, 1, 2, 3, 4, 5}, f"{d} (semaine 2) doit être bloqué toute la journée"


def test_le_22_octobre_est_le_seul_jour_non_mercredi_entierement_bloque_en_octobre():
    """Point de cohérence relevé par l'utilisateur, à propos des semaines 7 à
    9 : c'est là que les matins redeviennent généralement ouverts (contraire
    à septembre, où ils sont TOUS bloqués), donc c'est là qu'un blocage
    complet hors mercredi est une exception notable — utile pour un binôme
    mardi + jeudi, cf. mail de Kyllian Bresson. Sert de garde-fou contre une
    inversion jour/moment dans la génération des dates d'octobre."""
    by_date = {x.date: set(x.slots) for x in _bto().forbidden_date_slots}
    jours_octobre = [
        "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
        "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16",
        "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23",
    ]
    mercredis_octobre = {"2026-10-07", "2026-10-14", "2026-10-21"}
    complets = {d for d in jours_octobre if by_date.get(d) == {0, 1, 2, 3, 4, 5}}
    assert complets - mercredis_octobre == {"2026-10-22"}


def test_des_matinees_ideales_ou_acceptables_restent_libres_en_octobre():
    """Les demi-journées d'octobre décrites comme idéales ou acceptables ne
    doivent porter AUCUN blocage — sans quoi la correction serait trop large."""
    by_date = {x.date: set(x.slots) for x in _bto().forbidden_date_slots}
    matinees_ouvertes = [
        "2026-10-05", "2026-10-06", "2026-10-08", "2026-10-09",  # S7 : idéal
        "2026-10-12", "2026-10-13", "2026-10-15", "2026-10-16",  # S8
        "2026-10-19", "2026-10-20", "2026-10-23",                 # S9
    ]
    for d in matinees_ouvertes:
        assert (0 in by_date.get(d, set())) is False, f"{d} : le matin devrait rester libre"


def test_les_apres_midis_negociables_restent_libres():
    """Retour utilisateur : tous les après-midis hors mercredi sont
    négociables, sauf quatre exceptions précises."""
    by_date = {x.date: set(x.slots) for x in _bto().forbidden_date_slots}
    exceptions = {"2026-09-07", "2026-09-15", "2026-09-16", "2026-10-22"}
    apres_midis_a_verifier = [
        "2026-09-08", "2026-09-10", "2026-09-11",  # S3
        "2026-09-14", "2026-09-17", "2026-09-18",  # S4
        "2026-10-19", "2026-10-20", "2026-10-23",  # S9
    ]
    for d in apres_midis_a_verifier:
        assert d not in exceptions
        assert not ({3, 4, 5} & by_date.get(d, set())), f"{d} : l'après-midi devrait rester libre"
