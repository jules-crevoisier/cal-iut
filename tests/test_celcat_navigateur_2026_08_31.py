"""Ce que l'exploration du 31/08/2026 a etabli, verrouille par des tests.

Ces regles ont coute des essais : elles doivent survivre a une relecture
distraite. Rien ici ne touche au reseau — seulement les fonctions pures.
"""

import pytest
import yaml

from cal_iut.celcat import navigateur as nav

CONFIG = yaml.safe_load(open("data/config/celcat.yaml", encoding="utf-8"))


def test_les_dates_javascript_ont_un_mois_en_base_zero():
    """`new Date(2026,5,12)` est le 12 JUIN, pas le 12 mai.

    Se tromper d'un mois ne casserait rien de visible : les seances
    partiraient simplement a la mauvaise date.
    """
    lu = nav.lire_reponse('{"d": new Date(2026,5,12,11,11,5,0)}')
    assert lu["d"] == "2026-06-12T11:11:05"


def test_une_reponse_sans_date_reste_lisible():
    assert nav.lire_reponse('{"a": 1, "b": null}') == {"a": 1, "b": None}


def test_une_date_illisible_ne_fait_pas_echouer_la_reponse():
    """Mieux vaut une date perdue qu'un chargement entier perdu."""
    assert nav.lire_reponse('{"d": new Date(bizarre)}') == {"d": None}


def test_convention_de_nommage_des_groupes():
    """« BUT MMI S1 TD AB - 2024 », relevé le 31/08/2026."""
    assert nav.nom_groupe_celcat("S1", "TD AB") == "BUT MMI S1 TD AB - 2024"
    assert nav.nom_groupe_celcat("S5", "TD GH") == "BUT MMI S5 TD GH - 2024"


def test_la_convention_du_fichier_de_config_donne_le_meme_resultat():
    """Le YAML et le code ne doivent pas diverger en silence."""
    g = CONFIG["groupes"]
    attendu = g["convention"].format(semestre="S3", libelle="TP C", annee=g["annee_cohorte"])
    assert nav.nom_groupe_celcat("S3", "TP C", g["annee_cohorte"]) == attendu


def test_le_studio_porte_son_nom_complet():
    """H.022 s'appelle « H.022 studio » dans Celcat.

    Une recherche exacte sur « H.022 » ne remonte rien : le libellé complet
    est indispensable.
    """
    assert CONFIG["salles"]["h022"] == "H.022 studio"


def test_h018_pointe_desormais_vers_l_amphi_3_mmi():
    """Trouvé introuvable le 31/08/2026 (ni « H.018 » ni « amphi » côté IUT
    de Troyes), résolu le 01/09/2026 par réponse de Kyllian Bresson :
    « la salle h18 cerait : Amphi 3 MMI »."""
    assert CONFIG["salles"]["h018"] == "Amphi 3 MMI"


def test_les_salles_combinees_pointent_vers_une_seule_moitie():
    """H.007-008 et H.201-203 n'ont pas d'équivalent combiné dans Celcat.
    Décision utilisateur du 31/08/2026 : « pour les salle double on en
    choisit une seul et on met le td dedant » — une seule des deux
    retenue à chaque fois, pas de saisie double, pas de vide deviné."""
    assert CONFIG["salles"]["h007_h008"] == "H.007"
    assert CONFIG["salles"]["h201_h203"] == "H.201"


def test_la_203_pointe_bien_vers_la_023():
    """« H.203 » ne renvoie rien dans Celcat — confirmé le 31/08/2026."""
    assert CONFIG["salles"]["h203"] == "H.023"


@pytest.mark.parametrize("cle,attendu", [("h101", "H.101"), ("a018", "A.018"), ("h008", "H.008")])
def test_les_salles_verifiees_gardent_leur_libelle(cle, attendu):
    assert CONFIG["salles"][cle] == attendu


def test_les_roles_distinguent_lecture_et_ecriture():
    """Explorer en consultation rend l'ecriture IMPOSSIBLE, pas seulement
    evitee : c'est le garde-fou qui ne depend pas de la prudence du script."""
    assert nav.ROLE_LECTURE == "985_consultation"
    assert nav.ROLE_ECRITURE == "985_T_MMI"
    assert nav.BASE_ENTRAINEMENT == "URCA_FORMATION"


def test_chaque_type_de_ressource_a_son_icone():
    for type_id in (nav.TYPE_SALLES, nav.TYPE_GROUPES, nav.TYPE_PERSONNEL,
                    nav.TYPE_MATIERES, nav.TYPE_EQUIPES):
        assert type_id in nav.ICONES
