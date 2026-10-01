"""Règles d'envoi Celcat — WR100BU (visite de la BU) et séances PTUT.

Demande de Kyllian Bresson (01/10/2026), « Remontée des interventions de
Valérie Mariot dans Celcat » : WR100BU est un code INVENTÉ, absent de
Celcat. Ses séances étaient « sans code (voulu) », donc jamais envoyées.
Elles doivent désormais partir avec :

    Enseignant  Valérie Mariot (3696)      Type d'évènement  TD0 (pondération 0)
    Salle       celle de la séance          Classe           le groupe de la séance
    Remarque    WR100BU                     Département      T_MMI T29

et AUCUNE matière — ne jamais chercher un module « WR100BU » dans Celcat.

Seconde demande, même jour : toute séance de TYPE PTUT, quel que soit le
cours, part en catégorie « Projet » (pondération 0), remarque « PTUT », avec
le module du COURS s'il est connu (« oui, on veut pouvoir mettre un
module »), sans module sinon — jamais un module « PTUT ».

Ce que ces tests protègent :

- les règles sont déclaratives (`celcat.yaml::regles_envoi`, `cours:` et
  `types:`), chargées et validées ; un cours à la fois « sans code (voulu) »
  et sous règle est refusé au chargement ; la règle du cours passe avant
  celle du type ;
- l'entrée Celcat : pas de module, catégorie TD0, remarque, département ;
- la charge RPC, construite sans AUCUNE recherche de matière ; catégorie et
  département résolus par leur NOM, refus nommé s'ils manquent ;
- notre identifiant de séance reste lisible dans `notes` (« WR100BU — <id> »),
  et la comparaison / la suppression reconnaissent l'évènement ;
- une séance WR100BU d'un autre enseignant n'est pas envoyée, motif dit ;
- le plan, le worker, le hook immédiat, le garde-fou de catégorie, l'onglet
  « Codes Celcat » ;
- l'essai `cal-iut celcat-essai-sans-module` n'écrit jamais en production.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    monter_planning,
    place,
    poser_semaines_celcat,
    restaurer_etat,
    seance,
    snapshot_etat,
    vider_file,
)
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state
from cal_iut.celcat import ecriture
from cal_iut.celcat.categories import CategorieRefusee, verifier_charge_categorie
from cal_iut.celcat.mapping import (
    MODULE_AUCUN,
    MODULE_COURS,
    CelcatConfig,
    ConfigCelcatInvalide,
    entree_pour_placement,
    entrees_pour_state,
    load_celcat_config,
    session_id_depuis_notes,
)
from cal_iut.celcat.navigateur import (
    BASE_ENTRAINEMENT,
    BASE_PRODUCTION,
    TYPE_CATEGORIES_EVENEMENT,
    TYPE_DEPARTEMENTS,
    TYPE_GROUPES,
    TYPE_MATIERES,
    TYPE_PERSONNEL,
    TYPE_SALLES,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _regles_actives(monkeypatch):
    """Les règles sont DÉSACTIVÉES par défaut (`CAL_IUT_REGLES_ENVOI`) ; ce
    fichier décrit leur comportement une fois activées. Les tests de
    l'interrupteur coupé la retirent eux-mêmes (`_regles_coupees`)."""
    monkeypatch.setenv("CAL_IUT_REGLES_ENVOI", "on")


def _regles_coupees(monkeypatch) -> None:
    monkeypatch.delenv("CAL_IUT_REGLES_ENVOI", raising=False)
CONFIG = ROOT / "data" / "config"

# Catalogues d'une base Celcat factice. « TD0 bis » et « T_MMI » sont là pour
# vérifier qu'un nom VOISIN n'est jamais retenu.
CATALOGUES = {
    TYPE_SALLES: [{"name": "H.101", "unique_name": "H.101", "id": 601}],
    TYPE_PERSONNEL: [
        {"name": "MARIOT Valérie", "unique_name": "3696", "id": 501},
        {"name": "RIGUET Marine", "unique_name": "34044", "id": 502},
    ],
    TYPE_CATEGORIES_EVENEMENT: [
        {"name": "TD0 bis", "id": 999},
        {"name": "[TD]", "id": 433},
        {"name": "TD0", "id": 465},
        {"name": "Projet", "id": 700},
    ],
    TYPE_DEPARTEMENTS: [
        {"name": "T_MMI", "unique_name": "T_MMI", "id": 28},
        {"name": "T_MMI T29", "unique_name": "T_MMI T29", "id": 29},
    ],
}


class Appels:
    """Ce que la fausse base Celcat a dû chercher."""

    def __init__(self) -> None:
        self.types: list[int] = []      # catalogues `udlResources.load` demandés
        self.matieres: list[str] = []   # codes de matière cherchés

    @property
    def aucune_matiere(self) -> bool:
        return not self.matieres and TYPE_MATIERES not in self.types


@pytest.fixture
def catalogues(monkeypatch) -> Appels:
    """Faux `udlResources.load` : rend les catalogues ci-dessus et NOTE
    chaque type demandé ; fausse résolution de matière qui NOTE le code
    cherché (1590001 pour TSBZ1M01, refus nommé sinon)."""
    appels = Appels()

    def _charger(page, type_id, filtre):
        appels.types.append(type_id)
        if type_id == TYPE_MATIERES:
            raise AssertionError("les matières passent par la table relevée, jamais par le catalogue")
        if type_id == TYPE_GROUPES:
            return [{"name": "BUT MMI S1 TD AB - 2024", "id": 1661972}]
        return list(CATALOGUES.get(type_id, []))

    def _matiere(page, libelle, code, *cles):
        appels.matieres.append(code)
        if code == "TSBZ1M01":
            return 1590001
        raise ecriture.RessourceIntrouvable(libelle)

    monkeypatch.setattr(ecriture, "charger_ressources", _charger)
    monkeypatch.setattr(ecriture, "_trouver_matiere", _matiere)
    return appels


def _cfg() -> CelcatConfig:
    return load_celcat_config(CONFIG)


def _entree(
    prof: str = "VMA", *, cours: str = "WR100BU", sid: str = "WR100BU-S1-TD-1-but1-td-ab", type_: str = "TD", cfg=None
):
    return entree_pour_placement(
        cfg or _cfg(),
        session_id=sid,
        course_code=cours,
        session_type=type_,
        week=2, day=1, slot=4, duration_slots=1,
        teacher_codes=[prof],
        room_id="h101",
        groupe="TD AB",
        semestre="S1",
        lundi="2026-09-14",
    )


def _ecrire_config(tmp_path: Path, texte: str) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "celcat.yaml").write_text(texte, encoding="utf-8")
    return config


# ---------------------------------------------------------------------------
# La règle, dans la configuration
# ---------------------------------------------------------------------------


def test_les_regles_wr100bu_et_ptut_sont_chargees_depuis_la_config_reelle() -> None:
    cfg = _cfg()
    regle = cfg.regles_cours["WR100BU"]
    assert (regle.portee, regle.module, regle.categorie, regle.remarque, regle.departement, regle.enseignants) == (
        "cours", MODULE_AUCUN, "TD0", "WR100BU", "T_MMI T29", ("VMA",)
    )
    assert "Kyllian" in regle.motif
    ptut = cfg.regles_types["PTUT"]
    assert (ptut.portee, ptut.module, ptut.categorie, ptut.remarque, ptut.departement, ptut.enseignants) == (
        "type", MODULE_COURS, "Projet", "PTUT", "T_MMI T29", ()
    )
    assert cfg.enseignants["VMA"] == "3696"
    # Plus « sans code (voulu) », pas de module, origine lisible.
    assert "WR100BU" not in cfg.sans_code["cours"]
    assert "WR100BU" not in cfg.modules
    assert cfg.origines["cours"]["WR100BU"] == "regle"
    assert cfg.regle_sans_module("WR100BU") is regle and cfg.regle_sans_module("WR101") is None


def _regle_bu(**champs: str) -> str:
    lignes = {"module": "aucun", "categorie": "TD0", "departement": "T_MMI T29", **champs}
    return "".join(f"      {k}: {v}\n" for k, v in lignes.items() if v is not None)


def test_un_cours_a_la_fois_sans_code_voulu_et_sous_regle_est_refuse(tmp_path) -> None:
    config = _ecrire_config(
        tmp_path,
        "sans_code_voulu:\n  cours:\n    WR100BU: \"visite\"\n"
        "regles_envoi:\n  cours:\n    WR100BU:\n" + _regle_bu(),
    )
    with pytest.raises(ConfigCelcatInvalide) as exc:
        load_celcat_config(config)
    message = str(exc.value)
    assert "WR100BU" in message and "sans_code_voulu" in message and "regles_envoi" in message


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("modules:\n  WR100BU: \"TSBZ0000\"\nregles_envoi:\n  cours:\n    WR100BU:\n" + _regle_bu(),
         "`module: aucun`"),
        ("regles_envoi:\n  cours:\n    WR100BU:\n" + _regle_bu(categorie=""), "sans `categorie`"),
        ("regles_envoi:\n  cours:\n    WR100BU:\n" + _regle_bu(module=""), "`module` doit valoir"),
        ("regles_envoi:\n  cours:\n    WR100BU:\n" + _regle_bu(module="PTUT"), "`module` doit valoir"),
        ("regles_envoi:\n  cours:\n    WR100BU:\n" + _regle_bu(categories="TD"), "champ(s) inconnu(s) : categories"),
        ("regles_envoi:\n  cours:\n    WR100BU: TD0\n", "doit être une table"),
        ("regles_envoi:\n  WR100BU:\n" + _regle_bu(), "`cours:` et/ou `types:`"),
        ("regles_envoi:\n  types:\n    PROJET:\n" + _regle_bu(module="cours"), "type de séance inconnu"),
    ],
)
def test_une_regle_mal_ecrite_est_refusee_au_chargement(tmp_path, texte: str, attendu: str) -> None:
    with pytest.raises(ConfigCelcatInvalide) as exc:
        load_celcat_config(_ecrire_config(tmp_path, texte))
    assert attendu in str(exc.value)


def test_une_regle_de_cours_module_cours_peut_avoir_un_code_module(tmp_path) -> None:
    config = _ecrire_config(
        tmp_path,
        "modules:\n  WR101: \"TSBZ1M01\"\nregles_envoi:\n  cours:\n    WR101:\n" + _regle_bu(module="cours"),
    )
    cfg = load_celcat_config(config)
    assert cfg.regles_cours["WR101"].module == MODULE_COURS and cfg.modules["WR101"] == "TSBZ1M01"
    assert cfg.regles_cours["WR101"].departement == "T_MMI T29"


def test_une_saisie_ancienne_dans_l_appli_ne_contourne_pas_la_regle(monkeypatch) -> None:
    """Un code module ou un « sans code » saisi dans l'appli avant la règle
    ne doit ni faire chercher une matière, ni rendre la séance « non
    envoyée »."""
    from cal_iut.celcat import mappings

    monkeypatch.setattr(mappings, "table", lambda famille: {"WR100BU": "TSBZ9999"} if famille == "matieres" else {})
    monkeypatch.setattr(
        mappings, "sans_code_voulus",
        lambda: {"matieres": {"WR100BU": {"motif": "ancien", "ajoute_le": "", "ajoute_par": ""}}},
    )
    cfg = _cfg()
    assert "WR100BU" not in cfg.modules
    assert "WR100BU" not in cfg.sans_code["cours"]
    e = _entree(cfg=cfg)
    assert e.prete and e.code_module is None and e.regle == "WR100BU" and e.sans_module


# ---------------------------------------------------------------------------
# L'entrée Celcat
# ---------------------------------------------------------------------------


def test_l_entree_part_sans_module_en_td0_avec_remarque_et_departement() -> None:
    e = _entree()
    assert e.prete, e.bloquants
    assert e.code_module is None
    assert (e.regle, e.regle_libelle, e.categorie_celcat, e.remarque, e.departement) == (
        "WR100BU", "sans module (règle WR100BU)", "TD0", "WR100BU", "T_MMI T29"
    )
    assert e.sans_module
    assert (e.code_enseignant, e.salle, e.nom_groupe_celcat) == ("3696", "H.101", "BUT MMI S1 TD AB")
    assert e.notes_celcat == "WR100BU — WR100BU-S1-TD-1-but1-td-ab"
    # La règle entre dans la signature : la changer re-saisit la séance.
    assert e.signature().endswith("|regle:TD0|T_MMI T29|WR100BU")


def test_une_seance_ordinaire_garde_sa_signature_et_ses_notes() -> None:
    e = _entree("MRI", cours="WR101", sid="WR101-S1-TD-1-but1-td-ab")
    assert e.code_module == "TSBZ1M01" and not e.regle and not e.sans_module
    assert e.notes_celcat == "WR101-S1-TD-1-but1-td-ab"
    assert "regle" not in e.signature()


def test_une_seance_wr100bu_d_un_autre_enseignant_n_est_pas_envoyee() -> None:
    e = _entree("MRI")
    assert not e.prete and not e.regle
    assert e.non_envoyee == "WR100BU : seules les interventions de VMA sont envoyées (règle d'envoi de celcat.yaml)"
    assert not e.bloquants


def test_session_id_reconnu_dans_les_deux_formes_de_notes() -> None:
    assert session_id_depuis_notes("WR100BU — WR100BU-S1-TD-1-but1-td-ab") == "WR100BU-S1-TD-1-but1-td-ab"
    assert session_id_depuis_notes("WR101-S1-TD-1-but1-td-ab") == "WR101-S1-TD-1-but1-td-ab"


def test_une_ptut_d_un_cours_avec_code_part_en_projet_avec_le_module_du_cours() -> None:
    e = _entree("MRI", cours="WR101", sid="WR101-S1-PTUT-1-but1-tp-a", type_="PTUT")
    assert e.prete, e.bloquants
    assert (e.regle, e.regle_libelle, e.code_module, e.sans_module) == (
        "PTUT", "module du cours (règle PTUT)", "TSBZ1M01", False
    )
    assert (e.categorie_celcat, e.remarque, e.departement) == ("Projet", "PTUT", "T_MMI T29")
    assert e.notes_celcat == "PTUT — WR101-S1-PTUT-1-but1-tp-a"


def test_une_ptut_d_un_cours_sans_code_part_sans_module_au_lieu_d_etre_bloquee() -> None:
    e = _entree("MRI", cours="WRZ99", sid="WRZ99-S1-PTUT-1", type_="PTUT")
    assert e.prete, e.bloquants
    assert (e.regle_libelle, e.code_module, e.sans_module) == (
        "sans module — cours sans code Celcat (règle PTUT)", None, True
    )
    # Sans la règle, la même séance est bloquée (type et module sans code).
    ordinaire = _entree("MRI", cours="WRZ99", sid="WRZ99-S1-TD-1", type_="TD")
    assert not ordinaire.prete and "module WRZ99 sans code Celcat" in ordinaire.bloquants


def test_une_ptut_d_un_cours_sans_code_voulu_part_quand_meme_sans_module() -> None:
    e = _entree("MRI", cours="WS1PJ", sid="WS1PJ-S1-PTUT-1", type_="PTUT")
    assert e.prete and not e.non_envoyee and e.sans_module and e.regle == "PTUT"


def test_la_regle_du_cours_passe_avant_celle_du_type() -> None:
    vma = _entree("VMA", type_="PTUT")
    assert (vma.regle, vma.categorie_celcat, vma.sans_module) == ("WR100BU", "TD0", True)
    # Elle décide seule : un autre enseignant n'est pas rattrapé par la règle PTUT.
    mri = _entree("MRI", type_="PTUT")
    assert not mri.regle and "seules les interventions de VMA" in mri.non_envoyee


# ---------------------------------------------------------------------------
# La charge RPC et la résolution des identifiants
# ---------------------------------------------------------------------------


def test_la_charge_est_construite_sans_aucune_recherche_de_matiere(catalogues) -> None:
    e = _entree()
    ids = ecriture.resoudre_ids(FaussePage(), e, categorie="[TD]")  # la règle passe devant
    assert ids == {"room_id": 601, "staff_id": 501, "event_cat_id": 465, "dept_id": 29}
    assert catalogues.aucune_matiere
    charge = ecriture.charge_utile(e, group_id=1661972, ids=ids, masque="N" * 5 + "Y" + "N" * 48, event_id=0)
    assert charge["modules"] == []
    assert charge["event_cat_id"] == 465 and charge["dept_id"] == 29
    assert charge["rooms"] == [{"room_id": 601}] and charge["staff"] == [{"staff_id": 501}]
    assert charge["groups"] == [{"group_id": 1661972}]
    assert charge["notes"] == "WR100BU — WR100BU-S1-TD-1-but1-td-ab"
    verifier_charge_categorie(charge, type_seance_nom="TD", categorie_regle="TD0")


def test_creer_manquants_envoie_la_charge_td0(catalogues, monkeypatch) -> None:
    envoyees: list[dict] = []

    def _enregistrer(page, charge, *, methode):
        envoyees.append(charge)
        return 4242

    monkeypatch.setattr(ecriture, "enregistrer_evenement", _enregistrer)
    e = _entree()
    ids = ecriture.resoudre_ids(FaussePage(), e, categorie="")
    res = ecriture.creer_manquants(
        FaussePage(), [e], group_id=1661972, ids=ids, masque="N" * 5 + "Y" + "N" * 48,
        methode="udlTimetables.save",
    )
    assert res.crees == [("WR100BU-S1-TD-1-but1-td-ab", 4242)], res.echecs
    assert envoyees[0]["event_cat_id"] == 465 and envoyees[0]["modules"] == []
    assert catalogues.aucune_matiere


def test_une_ptut_cherche_la_matiere_du_cours_jamais_ptut(catalogues) -> None:
    e = _entree("MRI", cours="WR101", sid="WR101-S1-PTUT-1", type_="PTUT")
    ids = ecriture.resoudre_ids(FaussePage(), e, categorie="")
    assert ids == {"module_id": 1590001, "room_id": 601, "staff_id": 502, "event_cat_id": 700, "dept_id": 29}
    assert catalogues.matieres == ["TSBZ1M01"]
    charge = ecriture.charge_utile(e, group_id=1661972, ids=ids, masque="N" * 5 + "Y" + "N" * 48, event_id=0)
    assert charge["modules"] == [{"module_id": 1590001}] and charge["notes"] == "PTUT — WR101-S1-PTUT-1"
    verifier_charge_categorie(charge, type_seance_nom="PTUT", categorie_regle="Projet", sans_module=False)


def test_une_ptut_sans_code_ne_cherche_aucune_matiere(catalogues) -> None:
    e = _entree("MRI", cours="WRZ99", sid="WRZ99-S1-PTUT-1", type_="PTUT")
    ids = ecriture.resoudre_ids(FaussePage(), e, categorie="")
    assert "module_id" not in ids and catalogues.aucune_matiere
    charge = ecriture.charge_utile(e, group_id=1661972, ids=ids, masque="N" * 5 + "Y" + "N" * 48, event_id=0)
    assert charge["modules"] == []
    verifier_charge_categorie(charge, type_seance_nom="PTUT", categorie_regle="Projet", sans_module=True)


def test_projet_introuvable_bloque_la_ptut(catalogues, monkeypatch) -> None:
    monkeypatch.setitem(CATALOGUES, TYPE_CATEGORIES_EVENEMENT, [{"name": "Projet tutoré", "id": 701}])
    with pytest.raises(ecriture.RessourceIntrouvable, match="catégorie « Projet » introuvable dans Celcat"):
        ecriture.resoudre_ids(FaussePage(), _entree("MRI", cours="WR101", type_="PTUT"), categorie="")


def test_td0_introuvable_dans_celcat_bloque_avec_un_motif_nomme(catalogues, monkeypatch) -> None:
    """Jamais une catégorie voisine : « TD0 bis » existe, « TD0 » non."""
    monkeypatch.setitem(CATALOGUES, TYPE_CATEGORIES_EVENEMENT, [{"name": "TD0 bis", "id": 999}, {"name": "[TD]", "id": 433}])
    with pytest.raises(ecriture.RessourceIntrouvable) as exc:
        ecriture.resoudre_ids(FaussePage(), _entree(), categorie="")
    assert "catégorie « TD0 » introuvable dans Celcat" in str(exc.value)


def test_departement_introuvable_bloque_sans_prendre_un_voisin(catalogues, monkeypatch) -> None:
    monkeypatch.setitem(CATALOGUES, TYPE_DEPARTEMENTS, [{"name": "T_MMI", "unique_name": "T_MMI", "id": 28}])
    with pytest.raises(ecriture.RessourceIntrouvable) as exc:
        ecriture.resoudre_ids(FaussePage(), _entree(), categorie="")
    assert "département « T_MMI T29 » introuvable dans Celcat" in str(exc.value)


# ---------------------------------------------------------------------------
# Garde-fou de catégorie
# ---------------------------------------------------------------------------


def _charge(cat: object, modules: list | None = None) -> dict:
    return {"event_cat_id": cat, "modules": modules if modules is not None else []}


def test_le_garde_fou_accepte_td0_pour_une_entree_sous_regle() -> None:
    verifier_charge_categorie(_charge(465), type_seance_nom="TD", categorie_regle="TD0")


@pytest.mark.parametrize(
    "charge, motif",
    [
        (_charge(None), "exigée"),
        (_charge(433), "attend event_cat_id=465"),
        (_charge(465, [{"module_id": 1590000}]), "aucune"),
    ],
)
def test_le_garde_fou_refuse_une_charge_de_regle_incorrecte(charge: dict, motif: str) -> None:
    with pytest.raises(CategorieRefusee) as exc:
        verifier_charge_categorie(charge, type_seance_nom="TD", categorie_regle="TD0")
    assert motif in str(exc.value)


def test_le_garde_fou_d_une_ptut_avec_module() -> None:
    avec_module = _charge(700, [{"module_id": 1590001}])
    verifier_charge_categorie(avec_module, type_seance_nom="PTUT", categorie_regle="Projet", sans_module=False)
    with pytest.raises(CategorieRefusee, match="aucune"):
        verifier_charge_categorie(avec_module, type_seance_nom="PTUT", categorie_regle="Projet", sans_module=True)
    with pytest.raises(CategorieRefusee, match="CM/TD/TP"):
        verifier_charge_categorie(_charge(433), type_seance_nom="PTUT", categorie_regle="Projet", sans_module=False)


def test_le_garde_fou_refuse_td0_sur_une_seance_ordinaire() -> None:
    for type_nom in ("TD", "TP", "CM", "PTUT", ""):
        with pytest.raises(CategorieRefusee, match="réservé aux règles"):
            verifier_charge_categorie(_charge(465), type_seance_nom=type_nom)
    verifier_charge_categorie(_charge(433), type_seance_nom="TD")


def test_une_regle_sur_une_categorie_inconnue_refuse_les_ids_cm_td_tp() -> None:
    with pytest.raises(CategorieRefusee, match="CM/TD/TP"):
        verifier_charge_categorie(_charge(433), type_seance_nom="TD", categorie_regle="Réunion")
    verifier_charge_categorie(_charge(777), type_seance_nom="TD", categorie_regle="Réunion")


# ---------------------------------------------------------------------------
# Modification et suppression : l'évènement reste reconnu
# ---------------------------------------------------------------------------


def test_la_modification_retire_une_matiere_et_garde_l_identifiant() -> None:
    from cal_iut.celcat.modification import fusionner_deltas

    brut = {
        "event_id": 777, "event_cat_id": 433, "dept_id": 29, "notes": "",
        "modules": [{"module_id": 1590001, "event_id": 777, "name": "WR101"}],
        "rooms": [{"room_id": 601, "event_id": 777}],
        "staff": [{"staff_id": 501, "event_id": 777}],
        "groups": [{"group_id": 1661972, "event_id": 777}],
    }
    e = _entree()
    fusionne = fusionner_deltas(
        FaussePage(), brut, entree=e, ids={"room_id": 601, "staff_id": 501, "event_cat_id": 465, "dept_id": 29},
        group_id=1661972, masque="N" * 5 + "Y" + "N" * 48,
    )
    assert fusionne["modules"] == [{"-event_id": 777, "-module_id": 1590001, "_type_": "Module"}]
    assert fusionne["event_cat_id"] == 465
    assert session_id_depuis_notes(fusionne["notes"]) == e.session_id
    verifier_charge_categorie(fusionne, type_seance_nom="TD", categorie_regle="TD0")


def test_la_suppression_accepte_un_evenement_td0_sans_matiere(monkeypatch) -> None:
    from cal_iut.celcat import suppression

    brut = {
        "event_id": 777, "day_of_week": 1, "start_time": "15:30", "end_time": "17:00",
        "weeks": "N" * 5 + "Y" + "N" * 48, "evCatName": "TD0", "modules": [],
        "rooms": [{"name": "H.101"}], "groups": [{"name": "BUT MMI S1 TD AB - 2024", "id": 1661972}],
        "protected": "N", "notes": "WR100BU — WR100BU-S1-TD-1-but1-td-ab",
    }
    supprimes: list[int] = []
    monkeypatch.setattr(suppression, "localiser_evenement", lambda page, eid, group_ids: brut)
    monkeypatch.setattr(suppression, "supprimer_evenement_rpc", lambda page, eid, methode: supprimes.append(eid))
    suppression.supprimer_evenement(FaussePage(), 777, group_id=1661972, methode="udlTimetables.save")
    assert supprimes == [777]


def _placement(sid: str, prof: str = "VMA"):
    from types import SimpleNamespace

    return SimpleNamespace(
        session_id=sid, course_code="WR100BU", week=2, day=1, slot=4,
        room_id="h101", room_label="H.101", teacher_codes=[prof], group_ids=["but1-td-ab"],
    )


def _evenement(**champs) -> dict:
    ev = {
        "event_id": 777, "semaine": 5, "jour": 1, "heure_debut": "15:20", "salle": "H.101",
        "categorie": "TD0", "module": "", "groupe": "BUT MMI S1 TD AB",
    }
    ev.update(champs)
    return ev


def test_la_comparaison_reconnait_l_evenement_td0_sans_ecart_de_categorie_ni_de_module() -> None:
    from cal_iut.celcat.comparaison import comparer

    sid = "WR100BU-S1-TD-1-but1-td-ab"
    commun = {
        "semaine": 2, "semaine_celcat": 5, "salles_celcat": {"h101": "H.101"},
        "groupes_celcat": {sid: "BUT MMI S1 TD AB"}, "codes_celcat": {"WR101"},
        "types_seance": {sid: "TD"}, "categories_regle": {sid: "TD0"},
    }
    for journal in ({sid: 777}, None):  # par le journal, puis par ressemblance
        lignes = comparer(placements=[_placement(sid)], evenements=[_evenement()], journal=journal, **commun)
        assert [(l["statut"], l["ecarts"]) for l in lignes] == [("identique", [])]
    # Pondération affichée par Celcat : ce n'est pas une autre catégorie.
    lignes = comparer(placements=[_placement(sid)], evenements=[_evenement(categorie="TD0 [0%]")], **commun)
    assert lignes[0]["statut"] == "identique"
    # Saisi en [TD] à la main : c'est bien un écart de catégorie.
    lignes = comparer(placements=[_placement(sid)], evenements=[_evenement(categorie="[TD]")], **commun)
    assert (lignes[0]["statut"], lignes[0]["ecarts"]) == ("ecart", ["catégorie"])


def test_absente_de_celcat_est_un_vrai_manque_sous_regle_et_hors_perimetre_sinon() -> None:
    from cal_iut.celcat.comparaison import comparer

    vma, mri = "WR100BU-S1-TD-1-but1-td-ab", "WR100BU-S1-TD-1-but1-td-cd"
    lignes = comparer(
        placements=[_placement(vma), _placement(mri, "MRI")], evenements=[], semaine=2, semaine_celcat=5,
        codes_celcat={"WR101"}, categories_regle={vma: "TD0"},
    )
    assert {l["session_id"]: l["statut"] for l in lignes} == {vma: "absente_celcat", mri: "hors_celcat"}


# ---------------------------------------------------------------------------
# Plan, worker, hook immédiat, onglet « Codes Celcat » (config réelle)
# ---------------------------------------------------------------------------


def _ptut(sid: str, *, code: str, groupe: str, prof: str = "MRI"):
    from cal_iut.models.entities import SessionType

    return seance(sid, groupe=groupe, prof=prof, code=code).model_copy(update={"session_type": SessionType.PTUT})


@pytest.fixture
def bu(db_isole):
    """Planning minimal sur la VRAIE config : une visite de la BU par VMA
    (TD AB), une par MRI (TD CD), un TD ordinaire de WR101, une séance PTUT
    de WR101 (code TSBZ1M01) et une PTUT d'un cours sans code (WRZ99)."""
    etat = get_state()
    ancien = snapshot_etat(etat)
    vma = seance("bu-vma", groupe="but1-td-ab", prof="VMA", code="WR100BU")
    mri = seance("bu-mri", groupe="but1-td-cd", prof="MRI", code="WR100BU")
    ordinaire = seance("wr101-td", groupe="but1-td-ab", prof="MRI", code="WR101")
    ptut_avec = _ptut("ptut-avec", code="WR101", groupe="but1-td-cd")
    ptut_sans = _ptut("ptut-sans", code="WRZ99", groupe="but1-td-ab")
    client = monter_planning(
        [
            (vma, place(vma, day=0, slot=0)), (mri, place(mri, day=1, slot=0)),
            (ordinaire, place(ordinaire, day=2, slot=0)),
            (ptut_avec, place(ptut_avec, day=3, slot=0)), (ptut_sans, place(ptut_sans, day=4, slot=0)),
        ]
    )
    yield client
    restaurer_etat(etat, ancien)


def test_le_plan_montre_la_seance_a_creer_sans_module(bu) -> None:
    corps = bu.get(f"/celcat/plan?semaines={SEMAINE}").json()
    par_id = {e["session_id"]: e for e in corps["entrees"]}
    assert par_id["bu-vma"]["action"] == "creer"
    assert par_id["bu-vma"]["regle"] == "sans module (règle WR100BU)"
    assert (par_id["bu-vma"]["categorie"], par_id["bu-vma"]["remarque"]) == ("TD0", "WR100BU — bu-vma")
    assert par_id["bu-mri"]["action"] == "non_envoyee"
    assert "seules les interventions de VMA" in par_id["bu-mri"]["motif_non_envoi"]
    assert par_id["wr101-td"]["regle"] == ""
    assert corps["regles_envoi"] == {
        "sans module (règle WR100BU) : catégorie TD0, remarque WR100BU, département T_MMI T29": 1,
        "module du cours (règle PTUT) : catégorie Projet, remarque PTUT, département T_MMI T29": 1,
        "sans module — cours sans code Celcat (règle PTUT) : catégorie Projet, remarque PTUT, département T_MMI T29": 1,
    }
    assert corps["motifs_non_envoi"] == {
        "WR100BU : seules les interventions de VMA sont envoyées (règle d'envoi de celcat.yaml)": 1
    }
    assert (par_id["ptut-avec"]["action"], par_id["ptut-avec"]["regle"], par_id["ptut-avec"]["module"]) == (
        "creer", "module du cours (règle PTUT)", "TSBZ1M01"
    )
    assert (par_id["ptut-avec"]["categorie"], par_id["ptut-avec"]["remarque"]) == ("Projet", "PTUT — ptut-avec")
    assert (par_id["ptut-sans"]["action"], par_id["ptut-sans"]["regle"], par_id["ptut-sans"]["module"]) == (
        "creer", "sans module — cours sans code Celcat (règle PTUT)", ""
    )
    assert not any("WR100BU" in m for m in corps["motifs_blocage"])


def test_le_worker_cree_td0_et_projet_et_ecarte_l_autre_enseignant(bu, catalogues, monkeypatch) -> None:
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.logs import tous
    from cal_iut.celcat.nuit import drainer_file_immediate
    from cal_iut.celcat.sync import journal

    envoyees: dict[str, dict] = {}

    def _enregistrer(page, charge, *, methode):
        envoyees[session_id_depuis_notes(charge["notes"])] = charge
        return 4242 + len(envoyees)

    monkeypatch.setattr(ecriture, "enregistrer_evenement", _enregistrer)
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    activer_saisie(bu)
    vider_file()
    for sid in ("bu-vma", "bu-mri", "ptut-avec", "ptut-sans"):
        enfiler({"action": "create", "session_id": sid, "semaine": SEMAINE})
    poser_semaines_celcat()

    drainer_file_immediate(FaussePage(), production_autorisee=False)

    assert set(envoyees) == {"bu-vma", "ptut-avec", "ptut-sans"}, envoyees
    bu_vma, avec, sans = envoyees["bu-vma"], envoyees["ptut-avec"], envoyees["ptut-sans"]
    assert (bu_vma["event_cat_id"], bu_vma["dept_id"], bu_vma["modules"]) == (465, 29, [])
    assert bu_vma["notes"] == "WR100BU — bu-vma"
    # PTUT : catégorie Projet, module DU COURS quand il est connu, aucun sinon.
    assert (avec["event_cat_id"], avec["dept_id"], avec["modules"]) == (700, 29, [{"module_id": 1590001}])
    assert avec["notes"] == "PTUT — ptut-avec"
    assert (sans["event_cat_id"], sans["modules"], sans["notes"]) == (700, [], "PTUT — ptut-sans")
    # Jamais un module « PTUT » ni « WR100BU » : seul le code du cours WR101.
    assert catalogues.matieres == ["TSBZ1M01"]
    assert {sid for sid in ("bu-vma", "ptut-avec", "ptut-sans") if journal().get(sid, {}).get("event_id")} == {
        "bu-vma", "ptut-avec", "ptut-sans"
    }
    non_envoyes = [l for l in tous() if l.get("kind") == "non_envoye"]
    assert [l["session_id"] for l in non_envoyes] == ["bu-mri"]
    assert not [l for l in tous() if l.get("kind") == "blocked"]


def test_le_hook_immediat_n_enfile_que_l_intervention_de_vma(bu) -> None:
    from cal_iut.celcat.file_attente import lister
    from cal_iut.celcat.logs import tous
    from cal_iut.celcat.ops import _executer

    activer_saisie(bu)
    vider_file()
    _executer("bu-vma", "create")
    _executer("bu-mri", "create")
    assert [j["session_id"] for j in lister()] == ["bu-vma"]
    lignes = {l["session_id"]: l for l in tous()}
    assert lignes["bu-mri"]["kind"] == "non_envoye"
    assert "bu-vma" not in lignes or lignes["bu-vma"]["kind"] != "blocked"


def test_le_contexte_de_comparaison_porte_la_categorie_de_regle(bu) -> None:
    from cal_iut.celcat.planification import contexte

    ctx = contexte(get_state())
    assert ctx.categories_regle == {"bu-vma": "TD0", "ptut-avec": "Projet", "ptut-sans": "Projet"}


def test_l_onglet_codes_celcat_montre_l_origine_regle(bu) -> None:
    corps = bu.get("/reference/codes-celcat?famille=cours").json()
    ligne = next(l for l in corps["familles"]["cours"]["lignes"] if l["cle"] == "WR100BU")
    assert (ligne["origine"], ligne["origine_detail"], ligne["code"]) == ("regle", "envoi sans module (règle)", None)
    assert "catégorie TD0" in ligne["note"] and "T_MMI T29" in ligne["note"] and "VMA" in ligne["note"]
    assert ligne["modifiable"] is False and ligne["peut_marquer_sans_code"] is False
    assert corps["familles"]["cours"]["sans_module"] == 1
    # Ni manquant, ni « voulu ».
    assert ligne["origine"] not in ("manquant", "voulu")


def test_aucun_code_module_ni_sans_code_ne_se_saisit_pour_un_cours_sous_regle(bu) -> None:
    put = bu.put("/reference/codes-celcat", json={"famille": "cours", "cle": "WR100BU", "code": "TSBZ1M01"})
    assert put.status_code == 409 and "sans module" in put.json()["detail"]
    sans = bu.put("/reference/codes-celcat/sans-code", json={"famille": "cours", "cle": "WR100BU", "motif": "visite"})
    assert sans.status_code == 409 and "sans module" in sans.json()["detail"]


def test_les_donnees_a_completer_ne_reclament_pas_de_module_pour_wr100bu(bu) -> None:
    reponse = bu.get("/reference/manques")
    assert reponse.status_code == 200, reponse.text
    assert not [m for m in reponse.json()["manques"] if m.get("cle") == "WR100BU"]


def test_les_seances_du_planning_partent_sous_leur_regle(bu) -> None:
    entrees = entrees_pour_state(get_state())
    assert entrees["bu-vma"].regle == "WR100BU"
    assert entrees["bu-mri"].non_envoyee
    assert (entrees["ptut-avec"].regle, entrees["ptut-avec"].code_module) == ("PTUT", "TSBZ1M01")
    assert (entrees["ptut-sans"].regle, entrees["ptut-sans"].code_module, entrees["ptut-sans"].prete) == ("PTUT", None, True)
    assert entrees["wr101-td"].regle == ""


def test_l_essai_peut_traiter_une_vraie_seance_comme_une_ptut(bu) -> None:
    """Aucune PTUT au planning réel : l'essai prend une vraie séance comme
    support, sans rien changer au plan ni au robot."""
    from cal_iut.celcat import essai_regle as essai

    e = essai.entree_comme_type(get_state(), "wr101-td", "PTUT")
    assert (e.regle, e.categorie_celcat, e.code_module, e.notes_celcat) == ("PTUT", "Projet", "TSBZ1M01", "PTUT — wr101-td")
    assert entrees_pour_state(get_state())["wr101-td"].regle == ""
    with pytest.raises(LookupError, match="--comme-type"):
        essai.choisir_entree({}, type_seance="PTUT")


# ---------------------------------------------------------------------------
# L'essai en direct : jamais d'écriture en production
# ---------------------------------------------------------------------------


def test_l_essai_refuse_d_ecrire_ailleurs_qu_en_base_d_entrainement() -> None:
    from cal_iut.celcat.essai_regle import EssaiRefuse, ResultatEssai, ecrire_relire_supprimer

    res = ResultatEssai(entree=_entree(), base=BASE_PRODUCTION, charge={"weeks": "Y"})
    with pytest.raises(EssaiRefuse):
        ecrire_relire_supprimer(FaussePage(), res, methode="udlTimetables.save", methode_suppression="udlTimetables.save")


@pytest.mark.parametrize("cible", [[], ["--cours", "WR100BU", "--type", "PTUT"]])
def test_la_commande_exige_un_cours_ou_un_type(capsys, monkeypatch, cible) -> None:
    from cal_iut import cli

    monkeypatch.setattr("sys.argv", ["cal-iut", "celcat-essai-regle", *cible])
    assert cli.main() == 2
    assert "--cours" in capsys.readouterr().err


def test_la_commande_refuse_ecrire_sur_urca_2026_avant_toute_connexion(capsys, monkeypatch) -> None:
    from cal_iut import cli

    monkeypatch.setattr(
        "sys.argv", ["cal-iut", "celcat-essai-sans-module", "--cours", "WR100BU", "--base", "URCA_2026", "--ecrire"]
    )
    code = cli.main()
    assert code == 2
    assert "REFUSÉ" in capsys.readouterr().err


def test_l_essai_simule_puis_cree_relit_et_supprime_en_formation(catalogues, monkeypatch) -> None:
    from cal_iut.celcat import essai_regle as essai

    page = FaussePage()
    stock: dict[int, dict] = {}
    supprimes: list[int] = []

    def _enregistrer(p, charge, *, methode):
        stock[5150] = {**charge, "event_id": 5150, "evCatName": "TD0", "deptName": "T_MMI T29",
                       "rooms": [{"name": "H.101"}], "groups": [{"name": "BUT MMI S1 TD AB - 2024"}],
                       "staff": [{"name": "MARIOT Valérie"}]}
        return 5150

    def _edt(p, *, group_ids):
        return list(stock.values())

    def _supprimer(p, eid, *, group_id, methode, base, production_autorisee):
        assert base == BASE_ENTRAINEMENT and production_autorisee is False
        supprimes.append(eid)
        stock.pop(eid, None)

    monkeypatch.setattr(essai, "enregistrer_evenement", _enregistrer)
    monkeypatch.setattr(essai, "charger_edt", _edt)
    monkeypatch.setattr("cal_iut.celcat.suppression.supprimer_evenement", _supprimer)
    monkeypatch.setattr(essai, "resoudre_groupe", lambda *a, **k: (_ for _ in ()).throw(ecriture.RessourceIntrouvable("groupe")))
    monkeypatch.setattr(essai, "charger_ressources", lambda *a, **k: [{"name": "BUT MMI S1 TD AB - 2024"}])

    e = _entree()
    res = essai.preparer(page, e, base=BASE_ENTRAINEMENT, masque="N" * 5 + "Y" + "N" * 48)
    assert res.ok, res.erreur
    assert res.group_id == essai.GROUPE_CANARI_FORMATION
    assert res.charge["modules"] == [] and res.charge["event_cat_id"] == 465
    assert res.charge["_type_"] == "Event" and "event_id" not in res.charge
    assert catalogues.aucune_matiere

    res = essai.ecrire_relire_supprimer(page, res, methode="udlTimetables.save", methode_suppression="udlTimetables.save")
    assert res.event_id == 5150 and supprimes == [5150] and res.supprime is True
    assert res.relu["categorie"] == "TD0" and res.relu["departement"] == "T_MMI T29"
    assert res.relu["remarque (notes)"] == "WR100BU — WR100BU-S1-TD-1-but1-td-ab"
    assert res.relu["session_id lu dans notes"] == e.session_id
    assert res.relu["matieres"] == [] and res.relu["salles"] == ["H.101"]


def test_l_essai_rend_le_blocage_quand_td0_manque(catalogues, monkeypatch) -> None:
    from cal_iut.celcat import essai_regle as essai

    monkeypatch.setitem(CATALOGUES, TYPE_CATEGORIES_EVENEMENT, [{"name": "[TD]", "id": 433}])
    monkeypatch.setattr(essai, "charger_ressources", lambda *a, **k: [])
    res = essai.preparer(FaussePage(), _entree(), base=BASE_PRODUCTION, masque="N" * 5 + "Y" + "N" * 48, group_id=1661972)
    assert not res.ok and "catégorie « TD0 » introuvable dans Celcat" in res.erreur
    assert res.charge == {}


# ---------------------------------------------------------------------------
# L'interrupteur CAL_IUT_REGLES_ENVOI (off par défaut)
# ---------------------------------------------------------------------------

INACTIVE = "non envoyée — règle d'envoi en attente d'activation (CAL_IUT_REGLES_ENVOI)"


@pytest.mark.parametrize("valeur", [None, "", "off", "non", "0"])
def test_les_regles_sont_inactives_par_defaut(monkeypatch, valeur) -> None:
    from cal_iut.celcat.mapping import regles_actives

    if valeur is None:
        _regles_coupees(monkeypatch)
    else:
        monkeypatch.setenv("CAL_IUT_REGLES_ENVOI", valeur)
    assert regles_actives() is False
    e = _entree()
    assert (e.prete, e.regle, e.non_envoyee, e.bloquants) == (False, "", INACTIVE, [])
    ptut = _entree("MRI", cours="WRZ99", sid="WRZ99-S1-PTUT-1", type_="PTUT")
    assert (ptut.regle, ptut.non_envoyee, ptut.bloquants) == ("", INACTIVE, [])
    # Rien d'autre ne change : une séance ordinaire part comme avant.
    ordinaire = _entree("MRI", cours="WR101", sid="WR101-S1-TD-1")
    assert ordinaire.prete and ordinaire.code_module == "TSBZ1M01" and not ordinaire.regle


def test_interrupteur_coupe_le_plan_montre_les_seances_non_envoyees(bu, monkeypatch) -> None:
    _regles_coupees(monkeypatch)
    corps = bu.get(f"/celcat/plan?semaines={SEMAINE}").json()
    par_id = {e["session_id"]: e for e in corps["entrees"]}
    for sid in ("bu-vma", "bu-mri", "ptut-avec", "ptut-sans"):
        assert par_id[sid]["action"] == "non_envoyee", sid
        assert par_id[sid]["motif_non_envoi"] == INACTIVE and par_id[sid]["regle"] == ""
    assert par_id["wr101-td"]["action"] == "creer"
    assert corps["regles_envoi"] == {}
    assert corps["motifs_non_envoi"] == {INACTIVE: 4}
    assert not any("PTUT" in m or "WR100BU" in m for m in corps["motifs_blocage"])
    assert bu.get("/celcat/etat").json()["regles_envoi_actives"] is False


def test_interrupteur_coupe_rien_ne_part_par_le_robot(bu, catalogues, monkeypatch) -> None:
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.logs import tous
    from cal_iut.celcat.nuit import drainer_file_immediate

    _regles_coupees(monkeypatch)

    def _enregistrer(page, charge, *, methode):
        raise AssertionError(f"rien ne doit partir : {charge.get('notes')}")

    monkeypatch.setattr(ecriture, "enregistrer_evenement", _enregistrer)
    activer_saisie(bu)
    vider_file()
    for sid in ("bu-vma", "bu-mri", "ptut-avec", "ptut-sans"):
        enfiler({"action": "create", "session_id": sid, "semaine": SEMAINE})
    poser_semaines_celcat()

    drainer_file_immediate(FaussePage(), production_autorisee=False)

    assert not lister(), "aucune entrée sous règle ne reste dans la file d'envoi"
    non_envoyes = {l["session_id"]: l["motif"] for l in tous() if l.get("kind") == "non_envoye"}
    assert non_envoyes == dict.fromkeys(("bu-vma", "bu-mri", "ptut-avec", "ptut-sans"), INACTIVE)
    assert not [l for l in tous() if l.get("kind") == "blocked"]


def test_interrupteur_coupe_le_hook_immediat_n_enfile_rien(bu, monkeypatch) -> None:
    from cal_iut.celcat.file_attente import lister
    from cal_iut.celcat.ops import _executer

    _regles_coupees(monkeypatch)
    activer_saisie(bu)
    vider_file()
    for sid in ("bu-vma", "ptut-avec", "ptut-sans"):
        _executer(sid, "create")
    _executer("wr101-td", "create")
    assert [j["session_id"] for j in lister()] == ["wr101-td"]


def test_interrupteur_coupe_la_comparaison_ne_les_reclame_pas(bu, monkeypatch) -> None:
    from cal_iut.celcat.comparaison import comparer
    from cal_iut.celcat.planification import contexte

    _regles_coupees(monkeypatch)
    ctx = contexte(get_state())
    assert ctx.categories_regle == {}
    assert ctx.non_envoyees == {"bu-vma", "bu-mri", "ptut-avec", "ptut-sans"}
    lignes = comparer(
        placements=list(get_state().timetable), evenements=[], semaine=SEMAINE, semaine_celcat=SEMAINE + 3,
        groupes_celcat=ctx.groupes_celcat, codes_celcat=ctx.codes_celcat, categories_regle=ctx.categories_regle,
        non_envoyees=ctx.non_envoyees,
    )
    statuts = {l["session_id"]: l["statut"] for l in lignes}
    assert statuts["ptut-avec"] == "hors_celcat" and statuts["bu-vma"] == "hors_celcat"
    assert statuts["wr101-td"] == "absente_celcat"


def test_interrupteur_coupe_codes_celcat_dit_regle_inactive(bu, monkeypatch) -> None:
    _regles_coupees(monkeypatch)
    corps = bu.get("/reference/codes-celcat?famille=cours").json()
    ligne = next(l for l in corps["familles"]["cours"]["lignes"] if l["cle"] == "WR100BU")
    assert (ligne["origine"], ligne["origine_detail"]) == ("regle", "règle d'envoi (inactive)")


def test_l_essai_force_les_regles_quel_que_soit_l_interrupteur(bu, monkeypatch) -> None:
    from cal_iut import cli
    from cal_iut.celcat import essai_regle as essai
    from cal_iut.celcat.mapping import regles_actives, regles_forcees

    _regles_coupees(monkeypatch)
    with regles_forcees():
        assert regles_actives()
        entrees = entrees_pour_state(get_state())
        assert entrees["bu-vma"].regle == "WR100BU"
        assert essai.entree_comme_type(get_state(), "wr101-td", "PTUT").regle == "PTUT"
    assert not regles_actives()
    assert entrees_pour_state(get_state())["bu-vma"].non_envoyee == INACTIVE

    vu: list[bool] = []
    monkeypatch.setattr(cli, "_essai_regle", lambda args: vu.append(regles_actives()) or 0)
    monkeypatch.setattr("sys.argv", ["cal-iut", "celcat-essai-regle", "--cours", "WR100BU"])
    assert cli.main() == 0 and vu == [True]
    assert not regles_actives()

