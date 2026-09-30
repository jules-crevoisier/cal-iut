"""« Nouvel intervenant » depuis l'appli (30/09/2026).

Demande utilisateur (admin) : « ajoute la possibilité de créer un
intervenant ». Jusque-là : `enseignants_supplementaires.yaml` + une ligne
dans `celcat.yaml` + un déploiement. Ce que ces tests protègent :

- `POST /reference/enseignants` (admin) crée l'intervenant dans le volume
  (`data/state/references.json`), trace qui/quand, avance la révision ; il
  apparaît ensuite partout comme une entrée de `enseignants_supplementaires.yaml`
  (`/app-state`, `/api/v1/enseignants`, la liste de « Nouvelle séance »,
  les codes acceptés par la validation, l'onglet Codes Celcat) ; son code
  Celcat passe par l'écriture de l'onglet Codes Celcat et part au plan ;
- les GARDE-FOUS, dont le cas réel : « Anne Grenet » proposée sous AGR avec
  l'identifiant 3233, alors que `celcat.yaml` dit `AGR: "38321"  # Gram
  AMBROISE` et `AGT: "3233"  # GRENET ANNE` ;
- `DELETE /reference/enseignants/{code}` : seulement un intervenant créé
  dans l'appli, et seulement sans séance ;
- les droits : administrateurs seulement.
"""

from __future__ import annotations

import json

import pytest
from test_completer_reference_2026_09_29 import (  # noqa: F401 — fixtures partagées
    _seance,
    admin,
    edit,
    etat,
    lecteur,
)

from cal_iut.api import revision
from cal_iut.api.reference import noms_proches
from cal_iut.api.session_patch import codes_enseignants_connus
from cal_iut.celcat import mappings
from cal_iut.celcat.mapping import load_celcat_config
from cal_iut.ingestion import surcharges_reference
from cal_iut.ingestion.config_loader import load_teacher_contacts
from cal_iut.ingestion.enseignants import enseignants_declares

# Les deux lignes RÉELLES de `data/config/celcat.yaml` à l'origine des
# garde-fous, et un nom en commentaire pour MRI.
CELCAT_YAML = (
    "enseignants:\n"
    '  MRI: "111"  # RIGUET Marine\n'
    '  KBR: "0"\n'
    '  AGR: "38321"  # Gram AMBROISE\n'
    '  AGT: "3233"  # GRENET ANNE\n'
    '  ALE: "0"  # LEMAITRE Alexandra\n'
    "salles:\n  h005: \"H.005\"\n"
    "types_seance:\n  TD: 4\n  TP: 6\n"
    "modules:\n  WR101: \"TSB0101\"\n"
)


@pytest.fixture
def config_grenet(etat):  # noqa: F811
    (etat.config_dir / "celcat.yaml").write_text(CELCAT_YAML, encoding="utf-8")
    revision.incrementer("test-intervenant")
    return etat


def _creer(client, **corps):
    return client.post("/reference/enseignants", json=corps)


def _titres(reponse) -> list[str]:
    return [a["titre"] for a in reponse.json()["detail"]["avertissements"]]


# ---------------------------------------------------------------------------
# Création : persistée, tracée, visible partout
# ---------------------------------------------------------------------------


def test_creation_complete_visible_partout(admin, config_grenet) -> None:  # noqa: F811
    avant = revision.actuelle().numero
    r = _creer(admin, nom="  Zoé   Martin-Dupont ", code=" zmd ", code_celcat="40999", email=" Zoe.Martin@Univ.test ")
    assert r.status_code == 201, r.text
    corps = r.json()
    assert (corps["code"], corps["nom"], corps["email"], corps["code_celcat"]) == (
        "ZMD", "Zoé Martin-Dupont", "zoe.martin@univ.test", "40999",
    )
    assert corps["message"] == "Intervenant créé." and corps["revision"] > avant

    # Persisté dans le volume, avec la trace.
    fiche = surcharges_reference.intervenants()["ZMD"]
    assert fiche["nom"] == "Zoé Martin-Dupont" and fiche["cree_par"].startswith("test-admin-") and fiche["cree_le"]
    lignes = [l for l in surcharges_reference.journal() if l["cle"] == "ZMD"]
    assert {(l["famille"], l["champ"]) for l in lignes} >= {
        ("intervenants", "creation"), ("enseignants", "email"), ("enseignants", "code_celcat"),
    }
    assert all(l["par"].startswith("test-admin-") for l in lignes)

    # Comme une entrée de `enseignants_supplementaires.yaml`.
    assert enseignants_declares(config_grenet.config_dir)["ZMD"] == "Zoé Martin-Dupont"
    assert "ZMD" in codes_enseignants_connus(config_grenet), "« Nouvelle séance » doit accepter ce code"
    assert load_teacher_contacts(config_grenet.config_dir)["ZMD"] == "zoe.martin@univ.test"

    etat_app = admin.get("/app-state").json()
    assert etat_app["teacherLabels"]["ZMD"] == "Zoé Martin-Dupont", "liste de « Nouvelle séance » et annuaire"
    assert etat_app["teacherEmails"]["ZMD"] == "zoe.martin@univ.test"
    assert "ZMD" not in etat_app["surchargesReference"]["enseignants"], "son mail n'est pas « modifié » : il est à lui"
    cree = etat_app["intervenantsAppli"]["ZMD"]
    assert cree["cree_par"].startswith("test-admin-") and cree["nb_seances"] == 0

    v1 = {e["code"]: e for e in admin.get("/api/v1/enseignants").json()}
    assert v1["ZMD"]["nom"] == "Zoé Martin-Dupont" and v1["ZMD"]["nb_seances"] == 0

    # Code Celcat : la même écriture que l'onglet Codes Celcat, lue par le plan.
    assert load_celcat_config(config_grenet.config_dir).enseignants["ZMD"] == "40999"
    assert mappings.table("enseignants")["ZMD"] == "40999"
    ligne = next(
        l for l in admin.get("/reference/codes-celcat").json()["familles"]["enseignants"]["lignes"] if l["cle"] == "ZMD"
    )
    assert (ligne["code"], ligne["origine"], ligne["libelle"]) == ("40999", "appli", "Zoé Martin-Dupont")


def test_persiste_apres_rechargement_de_l_etat(admin, config_grenet) -> None:  # noqa: F811
    assert _creer(admin, nom="Paul Nouveau", code="PNO").status_code == 201
    chemin = surcharges_reference._path()
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    assert brut["intervenants"]["PNO"]["nom"] == "Paul Nouveau"
    # Relu depuis le disque (redémarrage, redéploiement : le volume reste).
    chemin.write_text(json.dumps(brut), encoding="utf-8")
    revision.incrementer("test-rechargement")
    assert surcharges_reference.intervenants()["PNO"]["nom"] == "Paul Nouveau"
    assert admin.get("/app-state").json()["teacherLabels"]["PNO"] == "Paul Nouveau"
    # Sans code Celcat saisi : manquant, pas inventé.
    assert "PNO" not in load_celcat_config(config_grenet.config_dir).enseignants


def test_une_seance_peut_etre_creee_pour_lui(admin, config_grenet) -> None:  # noqa: F811
    """La raison d'être : pouvoir lui créer sa PREMIÈRE séance — la
    validation de « Nouvelle séance » (`_enseignants_valides`) l'accepte."""
    from fastapi import HTTPException

    from cal_iut.api.main import _enseignants_valides

    with pytest.raises(HTTPException):
        _enseignants_valides(config_grenet, ["PNO"])
    assert _creer(admin, nom="Paul Nouveau", code="PNO").status_code == 201
    assert _enseignants_valides(config_grenet, [" pno "]) == ["PNO"]


# ---------------------------------------------------------------------------
# Garde-fous
# ---------------------------------------------------------------------------


def test_cas_reel_anne_grenet_agr_3233(admin, config_grenet) -> None:  # noqa: F811
    r = _creer(admin, nom="Anne Grenet", code="AGR", code_celcat="3233")
    assert r.status_code == 409, r.text
    titres = _titres(r)
    assert "AGR est Gram AMBROISE dans Celcat" in titres
    assert "3233 est déjà AGT (GRENET ANNE)" in titres
    assert "Cette personne existe peut-être déjà sous le code AGT" in titres
    par_type = {a["type"]: a for a in r.json()["detail"]["avertissements"]}
    assert "c'est peut-être la même personne ?" in par_type["code_celcat_pris"]["message"]
    assert "Ce code Celcat est déjà celui de AGT (GRENET ANNE)" in par_type["code_celcat_pris"]["message"]
    assert par_type["code_celcat_pris"]["bloquant"] and par_type["code_celcat_pris"]["code_existant"] == "AGT"
    assert "38321" in par_type["code_dans_celcat"]["message"], "dire sous quel identifiant partirait la paie"
    # Un code Celcat déjà pris ne se force pas.
    assert _creer(admin, nom="Anne Grenet", code="AGR", code_celcat="3233", confirmer=True).status_code == 409
    assert not surcharges_reference.intervenants() and "AGR" not in mappings.table("enseignants")


def test_code_present_dans_celcat_pour_une_autre_personne_se_confirme(admin, config_grenet) -> None:  # noqa: F811
    r = _creer(admin, nom="Alexis Leroy", code="ALE")
    assert r.status_code == 409
    assert _titres(r) == ["ALE est LEMAITRE Alexandra dans Celcat"]
    assert not r.json()["detail"]["avertissements"][0]["bloquant"]
    assert r.json()["detail"]["suggestion_code"], "proposer un code libre"
    assert not surcharges_reference.intervenants()
    ok = _creer(admin, nom="Alexis Leroy", code="ALE", confirmer=True)
    assert ok.status_code == 201, ok.text
    assert [a["type"] for a in ok.json()["avertissements_confirmes"]] == ["code_dans_celcat"]


def test_meme_personne_que_le_commentaire_celcat_pas_d_avertissement(admin, config_grenet) -> None:  # noqa: F811
    """AGR sous le nom de Gram Ambroise : c'est LUI, son identifiant du
    fichier lui revient — rien à confirmer."""
    r = _creer(admin, nom="Ambroise Gram", code="AGR")
    assert r.status_code == 201, r.text
    assert load_celcat_config(config_grenet.config_dir).enseignants["AGR"] == "38321"


def test_nom_ressemblant_accents_casse_ordre(admin, config_grenet) -> None:  # noqa: F811
    assert noms_proches("Anne Grenet", "GRENET ANNE")
    assert noms_proches("Anne-Sophie Diehl", "DIEHL ANNE SOPHIE")
    assert noms_proches("Hélène Dupré", "dupre helene")
    assert not noms_proches("Anne Grenet", "Anne Martin")
    r = _creer(admin, nom="MARINÉ riguet", code="MRG")
    assert r.status_code == 409
    avert = r.json()["detail"]["avertissements"]
    assert [a["titre"] for a in avert] == ["Cette personne existe peut-être déjà sous le code MRI"]
    assert avert[0]["fiche"] and avert[0]["code_existant"] == "MRI", "lien vers sa fiche"
    assert _creer(admin, nom="MARINÉ riguet", code="MRG", confirmer=True).status_code == 201


def test_code_celcat_deja_mappe_refuse_meme_confirme(admin, config_grenet) -> None:  # noqa: F811
    r = _creer(admin, nom="Paul Neuf", code="PNF", code_celcat="111", confirmer=True)
    assert r.status_code == 409
    assert _titres(r) == ["111 est déjà MRI (RIGUET Marine)"]
    # Sans le code Celcat, rien ne s'oppose.
    assert _creer(admin, nom="Paul Neuf", code="PNF").status_code == 201


@pytest.mark.parametrize(
    ("corps", "statut", "extrait"),
    [
        ({"nom": "Marine Autre", "code": "mri"}, 409, "déjà pris"),
        ({"nom": "Kyllian Autre", "code": "KBR"}, 409, "déjà pris"),
        ({"nom": "", "code": "XYZ"}, 400, "nom complet"),
        ({"nom": "Paul Neuf", "code": ""}, 400, "obligatoire"),
        ({"nom": "Paul Neuf", "code": "P1"}, 400, "2 à 4 lettres"),
        ({"nom": "Paul Neuf", "code": "PAULN"}, 400, "2 à 4 lettres"),
        ({"nom": "Paul Neuf", "code": "PNF", "email": "pas-une-adresse"}, 400, "adresse mail valide"),
        ({"nom": "Paul Neuf", "code": "PNF", "email": "Marine.Riguet@univ.test"}, 409, "déjà celle de"),
        ({"nom": "Paul Neuf", "code": "PNF", "code_celcat": "abc"}, 400, "identifiant Celcat"),
        ({"nom": "Paul Neuf", "code": "PNF", "code_celcat": "0"}, 400, "identifiant Celcat"),
    ],
)
def test_refus(admin, config_grenet, corps, statut, extrait) -> None:  # noqa: F811
    r = _creer(admin, **corps)
    assert r.status_code == statut, r.text
    assert extrait in r.json()["detail"]
    assert not surcharges_reference.intervenants()
    assert not mappings.table("enseignants")


def test_code_deja_cree_dans_l_appli_refuse(admin, config_grenet) -> None:  # noqa: F811
    assert _creer(admin, nom="Paul Nouveau", code="PNO").status_code == 201
    r = _creer(admin, nom="Pauline Nouvelle", code="pno")
    assert r.status_code == 409 and "déjà pris par Paul Nouveau" in r.json()["detail"]


def test_verification_en_direct_sans_ecriture(admin, config_grenet) -> None:  # noqa: F811
    r = admin.post("/reference/enseignants/verifier", json={"nom": "Anne Grenet", "code": "agr", "code_celcat": "3233"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["code"] == "AGR" and not corps["peut_creer"] and not corps["erreurs"]
    assert {a["type"] for a in corps["avertissements"]} == {"code_dans_celcat", "code_celcat_pris", "nom_proche"}
    assert corps["suggestion_code"] and corps["suggestion_code"] not in {"AGR", "AGT"}
    vide = admin.post("/reference/enseignants/verifier", json={"nom": "", "code": "MRI"}).json()
    assert {e["champ"] for e in vide["erreurs"]} == {"nom", "code"}
    assert next(e for e in vide["erreurs"] if e["champ"] == "code")["code_existant"] == "MRI"
    assert not surcharges_reference.intervenants()


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------


def test_reserve_aux_administrateurs(edit, lecteur, config_grenet) -> None:  # noqa: F811
    for client in (edit, lecteur):
        assert _creer(client, nom="Paul Nouveau", code="PNO").status_code == 403
        assert client.post("/reference/enseignants/verifier", json={"nom": "P N", "code": "PNO"}).status_code == 403
        assert client.delete("/reference/enseignants/PNO").status_code == 403
    assert not surcharges_reference.intervenants()


def test_public_ne_voit_pas_l_auteur(admin, config_grenet) -> None:  # noqa: F811
    from cal_iut.api.main import expurger_payload, payload_app_state

    assert _creer(admin, nom="Paul Nouveau", code="PNO").status_code == 201
    assert payload_app_state()["intervenantsAppli"]["PNO"]["cree_par"]
    assert expurger_payload(payload_app_state())["intervenantsAppli"] == {}


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------


def test_suppression_sans_seance(admin, config_grenet) -> None:  # noqa: F811
    assert _creer(admin, nom="Zoé Martin", code="ZMA", code_celcat="40999", email="zoe@univ.test").status_code == 201
    r = admin.delete("/reference/enseignants/zma")
    assert r.status_code == 200, r.text
    assert "Zoé Martin" in r.json()["message"]
    assert "ZMA" not in surcharges_reference.intervenants()
    assert "ZMA" not in load_teacher_contacts(config_grenet.config_dir)
    assert "ZMA" not in mappings.table("enseignants")
    assert "ZMA" not in admin.get("/app-state").json()["teacherLabels"]
    assert any(l["champ"] == "suppression" and l["cle"] == "ZMA" for l in surcharges_reference.journal())
    # Recréable ensuite.
    assert _creer(admin, nom="Zoé Martin", code="ZMA").status_code == 201


def test_suppression_refusee_avec_seance_ou_hors_appli(admin, config_grenet) -> None:  # noqa: F811
    assert _creer(admin, nom="Paul Nouveau", code="PNO").status_code == 201
    seance = _seance("pno1", "WR101", "Culture numérique", "but1-td-ab", "PNO")
    config_grenet.sessions.append(seance)
    config_grenet.sessions_by_id[seance.id] = seance
    revision.incrementer("test-seance-pno")
    assert admin.get("/app-state").json()["intervenantsAppli"]["PNO"]["nb_seances"] == 1
    r = admin.delete("/reference/enseignants/PNO")
    assert r.status_code == 409 and "1 séance" in r.json()["detail"]
    assert "PNO" in surcharges_reference.intervenants()
    # Un enseignant de la configuration ne se supprime pas ici.
    assert admin.delete("/reference/enseignants/MRI").status_code == 404
