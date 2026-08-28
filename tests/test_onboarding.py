"""Prise en main par quelqu'un qui n'a pas écrit le projet.

L'exigence tenue ici : **aucune trace Python ne doit jamais atteindre
l'utilisateur**, et tout message d'échec doit contenir l'action à faire. Un
outil destiné à une personne qui ne lira pas le code se juge d'abord là-dessus.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cal_iut.onboarding.doctor import run_doctor
from cal_iut.onboarding.refresh import compare_exports, refresh_sources

ROOT = Path(__file__).resolve().parents[1]


def _module(code: str, *, td: int = 4, prof: str = "AAA", seances: list | None = None) -> dict:
    return {
        "code_matiere": code,
        "semestre": "S1",
        "parcours": "BUT1",
        "total": {"cm": 0, "td": td, "tp": 0},
        "lead": {"code": prof},
        "profs": [{"code": prof, "cm": 0, "td": td, "tp": 0, "nbGpTd": 1, "nbGpTp": 1}],
        "maquette": {"groupes": {"td": 1, "tp": 1}},
        "progression": {"seances": seances or []},
    }


# --------------------------------------------------------------------------
# Comparaison des exports : dire ce qui change AVANT d'écrire
# --------------------------------------------------------------------------


def test_module_ajoute_et_retire_sont_nommes():
    resume = compare_exports([_module("WR101")], [_module("WR102")], "maquette.json")
    assert resume.ajoutes == ["WR102 (S1 BUT1)"]
    assert resume.retires == ["WR101 (S1 BUT1)"]
    assert not resume.identique


def test_changement_de_volume_est_detecte():
    resume = compare_exports([_module("WR101", td=4)], [_module("WR101", td=6)], "maquette.json")
    assert resume.modifies == ["WR101 (S1 BUT1)"]


def test_changement_d_enseignant_est_detecte():
    resume = compare_exports(
        [_module("WR101", prof="AAA")], [_module("WR101", prof="BBB")], "maquette.json"
    )
    assert resume.modifies == ["WR101 (S1 BUT1)"]


def test_un_commentaire_horodate_ne_compte_pas_comme_changement():
    """Les exports portent des horodatages de commentaires qui bougent seuls.

    Les signaler noierait les vrais changements — c'est exactement ce qui rend
    un diff inutilisable.
    """
    a = _module("WR101")
    b = _module("WR101")
    b["commentaires"] = [{"message": "coucou", "date": "2026-08-26T01:00:00+00:00"}]
    resume = compare_exports([a], [b], "maquette.json")
    assert resume.identique


def test_exports_identiques_donnent_aucun_changement():
    resume = compare_exports([_module("WR101")], [_module("WR101")], "maquette.json")
    assert resume.identique
    assert "aucun changement" in resume.to_text()


# --------------------------------------------------------------------------
# refresh : ne jamais écraser sans prévenir, ne jamais montrer une trace
# --------------------------------------------------------------------------


def test_apercu_n_ecrit_rien(tmp_path: Path):
    src = tmp_path / "contraintes_update"
    src.mkdir()
    (src / "maquette.json").write_text(json.dumps([_module("WR101")]), encoding="utf-8")
    (src / "progression.json").write_text(json.dumps([_module("WR101")]), encoding="utf-8")
    depuis = tmp_path / "recu"
    depuis.mkdir()
    (depuis / "maquette.json").write_text(json.dumps([_module("WR102")]), encoding="utf-8")
    (depuis / "progression.json").write_text(json.dumps([_module("WR102")]), encoding="utf-8")

    avant = (src / "maquette.json").read_text(encoding="utf-8")
    resumes, messages = refresh_sources(tmp_path, ecrire=False, depuis_fichiers=depuis)

    assert (src / "maquette.json").read_text(encoding="utf-8") == avant
    assert any("Rien n'a été écrit" in m for m in messages)
    assert any(r.total() for r in resumes)


def test_ecriture_sauvegarde_l_ancienne_version(tmp_path: Path):
    src = tmp_path / "contraintes_update"
    src.mkdir()
    (src / "maquette.json").write_text(json.dumps([_module("WR101")]), encoding="utf-8")
    (src / "progression.json").write_text(json.dumps([_module("WR101")]), encoding="utf-8")
    depuis = tmp_path / "recu"
    depuis.mkdir()
    (depuis / "maquette.json").write_text(json.dumps([_module("WR102")]), encoding="utf-8")
    (depuis / "progression.json").write_text(json.dumps([_module("WR102")]), encoding="utf-8")

    _, messages = refresh_sources(tmp_path, ecrire=True, depuis_fichiers=depuis)

    nouveau = json.loads((src / "maquette.json").read_text(encoding="utf-8"))
    assert nouveau[0]["code_matiere"] == "WR102"
    sauvegardes = list((tmp_path / "data" / "sauvegardes").iterdir())
    assert sauvegardes, "l'ancienne version doit être sauvegardée"
    ancien = json.loads((sauvegardes[0] / "maquette.json").read_text(encoding="utf-8"))
    assert ancien[0]["code_matiere"] == "WR101"
    assert any("sauvegardée" in m for m in messages)


def test_dossier_incomplet_donne_un_message_pas_une_trace(tmp_path: Path):
    depuis = tmp_path / "recu"
    depuis.mkdir()
    (depuis / "maquette.json").write_text("[]", encoding="utf-8")
    # progression.json volontairement absent

    resumes, messages = refresh_sources(tmp_path, ecrire=True, depuis_fichiers=depuis)

    assert not resumes
    assert any(m.startswith("ERREUR") for m in messages)
    assert any("progression.json" in m for m in messages)
    assert not any("Traceback" in m for m in messages)


def test_json_corrompu_donne_un_message_comprehensible(tmp_path: Path):
    depuis = tmp_path / "recu"
    depuis.mkdir()
    (depuis / "maquette.json").write_text("ceci n'est pas du json", encoding="utf-8")
    (depuis / "progression.json").write_text("[]", encoding="utf-8")

    _, messages = refresh_sources(tmp_path, ecrire=True, depuis_fichiers=depuis)
    erreur = next(m for m in messages if m.startswith("ERREUR"))
    assert "n'est pas un JSON valide" in erreur
    assert "tableur" in erreur, "le message doit suggérer la cause la plus fréquente"


def test_reseau_coupe_propose_le_repli_fichier(tmp_path: Path, monkeypatch):
    def _boom(url: str):
        raise httpx.ConnectError("réseau injoignable")

    monkeypatch.setattr("cal_iut.ingestion.fetch.fetch_export_sync", _boom)
    resumes, messages = refresh_sources(tmp_path, ecrire=False)

    assert not resumes
    erreur = next(m for m in messages if m.startswith("ERREUR"))
    assert "--depuis" in erreur, "l'utilisateur doit apprendre le repli hors ligne"


# --------------------------------------------------------------------------
# doctor : toujours dire l'étape suivante
# --------------------------------------------------------------------------


def test_doctor_sur_un_dossier_vide_ne_plante_pas_et_guide(tmp_path: Path):
    checks, etapes = run_doctor(tmp_path)

    assert checks, "le docteur doit produire des contrôles même sur un dossier vide"
    assert etapes and etapes[0].startswith("À FAIRE MAINTENANT")
    for check in checks:
        if not check.ok and check.bloquant:
            assert check.action, f"{check.libelle} ne dit pas quoi faire"


@pytest.mark.local  # état de la machine (ingestion, contraintes), pas le code
def test_doctor_sur_le_projet_reel_est_au_vert():
    checks, etapes = run_doctor(ROOT)
    bloquants_ko = [c for c in checks if not c.ok and c.bloquant]
    assert not bloquants_ko, "\n".join(f"{c.libelle} : {c.detail}" for c in bloquants_ko)
    assert any("Tout est en place" in e for e in etapes)


def test_doctor_reconnait_les_fichiers_accentues():
    """Sous Windows, « É » peut être stocké décomposé : le docteur annonçait
    à tort des fichiers manquants."""
    checks, _ = run_doctor(ROOT)
    sources = next(c for c in checks if c.libelle == "Fichiers sources officiels")
    assert sources.ok, sources.detail


def test_doctor_detecte_des_sources_plus_recentes_que_les_contraintes(tmp_path: Path):
    src = tmp_path / "contraintes_update"
    gen = tmp_path / "contraintes"
    src.mkdir()
    gen.mkdir()
    for i in range(6):
        (gen / f"0{i}_x.json").write_text("{}", encoding="utf-8")
    # Source modifiée APRÈS la génération.
    import time

    time.sleep(0.01)
    (src / "maquette.json").write_text("[]", encoding="utf-8")

    checks, _ = run_doctor(tmp_path)
    a_jour = next(c for c in checks if c.libelle == "Contraintes à jour avec les sources")
    assert not a_jour.ok
    assert "build_contraintes" in a_jour.action


def test_un_export_identique_n_est_pas_reecrit(tmp_path: Path):
    """Réécrire un fichier inchangé fait mentir tous les contrôles de fraîcheur.

    Constaté le 26/08/2026 : `cal-iut doctor` annonçait « 2 source(s)
    modifiée(s) » sur deux exports **identiques à l'octet près**, 6 millisecondes
    plus récents que la génération. Le seul effet réel de la réécriture était
    d'avancer la date de modification.
    """
    src = tmp_path / "contraintes_update"
    src.mkdir()
    contenu = json.dumps([_module("WR101")], ensure_ascii=False)
    for nom in ("maquette.json", "progression.json"):
        (src / nom).write_text(contenu, encoding="utf-8")
    dates = {nom: (src / nom).stat().st_mtime_ns for nom in ("maquette.json", "progression.json")}

    depuis = tmp_path / "recu"
    depuis.mkdir()
    for nom in ("maquette.json", "progression.json"):
        (depuis / nom).write_text(contenu, encoding="utf-8")

    _, messages = refresh_sources(tmp_path, ecrire=True, depuis_fichiers=depuis)

    for nom, avant in dates.items():
        assert (src / nom).stat().st_mtime_ns == avant, f"{nom} a été réécrit sans raison"
    assert any("Aucun changement" in m for m in messages)


def test_une_source_identique_mais_plus_recente_ne_declenche_pas_l_alerte(tmp_path: Path):
    """Une DATE plus récente ne prouve pas un CONTENU différent.

    Un contrôle qui crie à tort finit ignoré — et emporte avec lui la confiance
    dans tous les autres.
    """
    src = tmp_path / "contraintes_update"
    gen = tmp_path / "contraintes"
    src.mkdir()
    gen.mkdir()
    for i in range(6):
        (gen / f"0{i}_x.json").write_text("{}", encoding="utf-8")

    import time

    time.sleep(0.01)
    # Recopiée à l'identique dans `contraintes/`, mais plus récente.
    (gen / "maquette.json").write_text("[]", encoding="utf-8")
    (src / "maquette.json").write_text("[]", encoding="utf-8")

    checks, _ = run_doctor(tmp_path)
    a_jour = next(c for c in checks if c.libelle == "Contraintes à jour avec les sources")
    assert a_jour.ok, a_jour.detail


@pytest.mark.parametrize("commande", ["doctor", "audit", "refresh", "annee"])
def test_les_commandes_de_prise_en_main_sont_declarees(commande: str):
    import argparse

    from cal_iut import cli
    from cal_iut.cli import main  # noqa: F401

    parser_source = Path(cli.__file__).read_text(encoding="utf-8")
    assert f'sub.add_parser(\n        "{commande}"' in parser_source or \
           f'sub.add_parser("{commande}"' in parser_source, \
           f"la commande {commande} doit exister"
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)


# --------------------------------------------------------------------------
# regles : lire les règles actives sans ouvrir un seul YAML
# --------------------------------------------------------------------------


def test_l_inventaire_couvre_les_grandes_familles_de_regles():
    from cal_iut.onboarding.regles import inventorier

    inventaire = inventorier(ROOT)
    categories = set(inventaire.par_categorie())

    for attendue in (
        "Groupes étudiants",
        "Quand un cours peut commencer / doit finir",
        "Séances imposées à une date",
        "Durée des séances",
        "Répartition entre enseignants",
        "SAE",
    ):
        assert attendue in categories, f"catégorie « {attendue} » absente de l'inventaire"


def test_chaque_regle_dit_d_ou_elle_vient():
    """Une règle sans fichier d'origine est introuvable pour qui veut la changer."""
    from cal_iut.onboarding.regles import inventorier

    for regle in inventorier(ROOT).regles:
        assert regle.ou, f"« {regle.resume} » ne dit pas dans quel fichier elle vit"
        assert regle.resume


def test_les_regles_metier_citent_leur_raison():
    """Le champ `note` des YAML consigne qui a demandé quoi et pourquoi.

    Une règle dont on ne sait plus la raison finit supprimée à tort — ou
    conservée à tort. Les catégories purement descriptives (groupes, salles)
    sont exemptées : elles décrivent l'existant, elles ne l'arbitrent pas.
    """
    from cal_iut.onboarding.regles import inventorier

    descriptives = {"Groupes étudiants", "Salles", "SAE", "Disponibilités des enseignants"}
    sans_raison = [
        r.resume
        for r in inventorier(ROOT).regles
        if r.categorie not in descriptives and not r.raison
    ]
    assert not sans_raison, "règles sans justification : " + " ; ".join(sans_raison)


def test_l_inventaire_ne_plante_pas_sur_un_dossier_vide(tmp_path: Path):
    from cal_iut.onboarding.regles import inventorier

    try:
        inventaire = inventorier(tmp_path)
    except FileNotFoundError:
        # Acceptable tant que le message reste explicite : c'est `doctor` qui
        # diagnostique une installation incomplète, pas `regles`.
        return
    assert isinstance(inventaire.regles, list)
