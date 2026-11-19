"""Onglet « Enseignants & vacataires » (01/10/2026).

Demande de Kyllian Bresson (responsable) : la liste de tous les enseignants
et vacataires — prénom, nom, diminutif, code Celcat, mail, téléphone, type
(Enseignant | Vacataire) —, modifiable, « stockée dans la structure de
données existante ». Ce que ces tests protègent :

- la dérivation prénom / nom depuis le nom complet, sur les cas réels de la
  feuille des contraintes et de la maquette ;
- prénom, nom, téléphone et type vivent dans `data/state/references.json`
  (surcharges de référence : trace, révision, « Revenir à la valeur du
  fichier »), et le nom affiché partout devient « Prénom NOM » ;
- le téléphone : format français ou international, rangé en E.164, servi
  aux rôles `edit` et `admin` SEULEMENT — jamais dans `/app-state` (aucune
  variante), jamais dans l'API v1, jamais pour `read_only` ni `api` ;
- le type et les prénom / nom séparés dans `/api/v1/enseignants` ;
- « Nouvel intervenant » avec téléphone et type.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_completer_reference_2026_09_29 import (  # noqa: F401 — fixtures partagées
    ROOT,
    admin,
    edit,
    etat,
    lecteur,
)

from cal_iut.api import revision
from cal_iut.api.main import app
from cal_iut.ingestion import identite_enseignants as ident
from cal_iut.ingestion import surcharges_reference

TELEPHONE = "06 12 34 56 78"
TELEPHONE_E164 = "+33612345678"


@pytest.fixture
def noms(etat):  # noqa: F811
    """La vraie feuille des contraintes (Marine Riguet = MRI, Kyllian Bresson
    = KBR) à côté de la config de test."""
    racine = Path(etat.config_dir).parent.parent
    (racine / "contraintes").mkdir(exist_ok=True)
    shutil.copy(ROOT / "contraintes" / "05_enseignants_contraintes.json", racine / "contraintes")
    revision.incrementer("test-enseignants-vacataires")
    return etat


def _ligne(client: TestClient, code: str) -> dict:
    r = client.get("/reference/enseignants")
    assert r.status_code == 200, r.text
    return next(l for l in r.json()["lignes"] if l["code"] == code)


# ---------------------------------------------------------------------------
# Prénom / nom : dérivés du nom complet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("complet", "attendu"),
    [
        ("Thomas CASTELLENGO", ("Thomas", "CASTELLENGO")),
        ("KYLLIAN BRESSON", ("Kyllian", "BRESSON")),
        ("Anne-Laure  Perrone", ("Anne-Laure", "PERRONE")),
        ("Anne-Laure  Perrone ", ("Anne-Laure", "PERRONE")),
        ("ANNE-LAURE PERRONE", ("Anne-Laure", "PERRONE")),
        ("Barthélémy TOMASINA", ("Barthélémy", "TOMASINA")),
        ("Alexia Petit-Halajko", ("Alexia", "PETIT-HALAJKO")),
        ("Jean-Marc DE LA TOUR", ("Jean-Marc", "DE LA TOUR")),
        ("Marie de la Tour", ("Marie", "DE LA TOUR")),
        ("Kévin Ngo", ("Kévin", "NGO")),
        ("ÉLODIE ÉCHARD", ("Élodie", "ÉCHARD")),
        ("Nino", ("", "NINO")),
        ("", ("", "")),
    ],
)
def test_separer_nom(complet: str, attendu: tuple[str, str]) -> None:
    assert ident.separer_nom(complet) == attendu


def test_un_nom_qui_n_est_que_le_code_ne_donne_ni_prenom_ni_nom() -> None:
    assert ident.separer_nom("MRI", "MRI") == ("", "")
    assert ident.separer_nom("mri", "MRI") == ("", "")


def test_tous_les_noms_reels_se_separent() -> None:
    """Feuille officielle et maquette : chaque nom donne un prénom ET un nom,
    et recomposé, il redonne les mêmes mots."""
    feuille = json.loads((ROOT / "contraintes" / "05_enseignants_contraintes.json").read_text(encoding="utf-8"))
    noms = [e["nom_complet"] for e in feuille]
    maquette = json.loads((ROOT / "contraintes" / "maquette.json").read_text(encoding="utf-8"))
    for cours in maquette:
        for t in [cours.get("lead") or {}] + list(cours.get("profs") or []):
            if t.get("code") and t.get("code") not in ("NOBODY", "XXX") and t.get("prenom") and t.get("nom"):
                noms.append(f"{t['prenom']} {t['nom']}")
    assert len(noms) > 40
    for complet in noms:
        prenom, nom = ident.separer_nom(complet)
        assert prenom and nom, complet
        assert ident.recomposer(prenom, nom).lower() == " ".join(complet.split()).lower(), complet


def test_maquette_et_feuille_donnent_le_meme_prenom_nom() -> None:
    """« KYLLIAN BRESSON » (maquette) et « Kyllian Bresson » (feuille) : la
    même personne, les mêmes colonnes."""
    assert ident.separer_nom("KYLLIAN BRESSON") == ident.separer_nom("Kyllian Bresson")
    assert ident.separer_nom("Thomas CASTELLENGO") == ident.separer_nom("Thomas Castellengo")


# ---------------------------------------------------------------------------
# Téléphone et type : validation, normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("saisie", "e164", "affiche"),
    [
        ("06 12 34 56 78", "+33612345678", "06 12 34 56 78"),
        ("06.12.34.56.78", "+33612345678", "06 12 34 56 78"),
        ("0612345678", "+33612345678", "06 12 34 56 78"),
        ("06-12-34-56-78", "+33612345678", "06 12 34 56 78"),
        ("+33 6 12 34 56 78", "+33612345678", "06 12 34 56 78"),
        ("+33 (0)6 12 34 56 78", "+33612345678", "06 12 34 56 78"),
        ("0033 3 25 42 46 46", "+33325424646", "03 25 42 46 46"),
        ("tel:+33325424646", "+33325424646", "03 25 42 46 46"),
        ("+44 20 7946 0958", "+442079460958", "+442079460958"),
        ("+262 692 12 34 56", "+262692123456", "+262692123456"),
    ],
)
def test_telephone_valide(saisie: str, e164: str, affiche: str) -> None:
    assert ident.normaliser_telephone(saisie) == e164
    assert ident.formater_telephone(e164) == affiche


@pytest.mark.parametrize(
    "saisie",
    ["", "06 12 34 56", "6 12 34 56 78", "00 1", "+33 06 12 34 56 78", "+33 6 12 34 56", "06 12 34 56 7a",
     "+0 123 456 789", "+1 234", "bonjour"],
)
def test_telephone_invalide(saisie: str) -> None:
    with pytest.raises(ValueError):
        ident.normaliser_telephone(saisie)


def test_type() -> None:
    assert ident.normaliser_type("Vacataire") == "vacataire"
    assert ident.normaliser_type(" ENSEIGNANT ") == "enseignant"
    for faux in ("", "titulaire", "à préciser"):
        with pytest.raises(ValueError):
            ident.normaliser_type(faux)


# ---------------------------------------------------------------------------
# L'annuaire : une seule source
# ---------------------------------------------------------------------------


def test_annuaire_liste_les_enseignants_de_l_appli(edit, noms) -> None:  # noqa: F811
    corps = edit.get("/reference/enseignants").json()
    libelles = edit.get("/app-state").json()["teacherLabels"]
    assert [l["code"] for l in corps["lignes"]] == sorted(libelles), "la liste de l'annuaire, rien d'autre"
    mri = next(l for l in corps["lignes"] if l["code"] == "MRI")
    assert (mri["prenom"], mri["nom"], mri["nom_complet"]) == ("Marine", "RIGUET", "Marine Riguet")
    assert mri["email"] == "marine.riguet@univ.test"
    assert mri["type"] is None and mri["telephone"] is None, "aucune source : à préciser"
    assert mri["code_celcat"]["code"] == "111" and mri["code_celcat"]["origine"] == "fichier"
    assert mri["nb_seances"] == 2
    assert corps["peut_modifier"] is True and corps["admin"] is False and corps["telephone_visible"] is True
    c = corps["compteurs"]
    assert c["a_preciser"] == c["total"] == len(libelles) and c["enseignants"] == c["vacataires"] == 0


# ---------------------------------------------------------------------------
# Prénom / nom corrigés : surcharge, trace, nom affiché, retour au fichier
# ---------------------------------------------------------------------------


def test_corriger_le_prenom_recompose_le_nom_affiche_partout(edit, noms) -> None:  # noqa: F811
    avant = revision.actuelle().numero
    r = edit.put("/reference/enseignants/MRI", json={"prenom": "  marine-alice "})
    assert r.status_code == 200, r.text
    assert r.json()["valeurs"] == {"prenom": "Marine-Alice"} and r.json()["revision"] > avant

    etat_app = edit.get("/app-state").json()
    assert etat_app["teacherLabels"]["MRI"] == "Marine-Alice RIGUET"
    assert etat_app["teacherIdentites"]["MRI"] == {"prenom": "Marine-Alice", "nom": "RIGUET", "type": None}
    marque = etat_app["surchargesReference"]["enseignants"]["MRI"]["prenom"]
    assert marque["valeur"] == "Marine-Alice" and marque["origine"] == "Marine"
    assert marque["modifie_par"].startswith("test-edit-")
    v1 = {e["code"]: e for e in edit.get("/api/v1/enseignants").json()}
    assert (v1["MRI"]["nom"], v1["MRI"]["prenom"], v1["MRI"]["nom_famille"]) == ("Marine-Alice RIGUET", "Marine-Alice", "RIGUET")
    ligne = _ligne(edit, "MRI")
    assert ligne["prenom"] == "Marine-Alice" and ligne["surcharges"]["prenom"]["origine"] == "Marine"

    # Trace : qui, quand, valeur d'avant ET valeur du fichier.
    trace = [l for l in surcharges_reference.journal() if l["cle"] == "MRI" and l["champ"] == "prenom"][0]
    assert trace["apres"] == "Marine-Alice" and trace["avant"] is None and trace["valeur_fichier"] == "Marine"
    assert trace["par"].startswith("test-edit-")

    # Le nom de famille, à part, rangé en capitales.
    assert edit.put("/reference/enseignants/MRI", json={"nom_famille": "Riguet-Durand"}).status_code == 200
    assert edit.get("/app-state").json()["teacherLabels"]["MRI"] == "Marine-Alice RIGUET-DURAND"

    # « Revenir à la valeur du fichier », champ par champ.
    r = edit.delete("/reference/enseignants/MRI/prenom")
    assert r.status_code == 200, r.text
    assert edit.get("/app-state").json()["teacherLabels"]["MRI"] == "Marine RIGUET-DURAND"
    assert edit.delete("/reference/enseignants/MRI/nom_famille").status_code == 200
    etat_app = edit.get("/app-state").json()
    assert etat_app["teacherLabels"]["MRI"] == "Marine Riguet", "sans correction : le nom du fichier, inchangé"
    assert "MRI" not in etat_app["surchargesReference"]["enseignants"]
    assert edit.delete("/reference/enseignants/MRI/prenom").status_code == 404


def test_ressaisir_la_valeur_du_fichier_ne_cree_pas_de_surcharge(edit, noms) -> None:  # noqa: F811
    assert edit.put("/reference/enseignants/KBR", json={"prenom": "Kyllian", "nom_famille": "bresson"}).status_code == 200
    assert surcharges_reference.origine("enseignants", "KBR", "prenom") is None
    assert surcharges_reference.origine("enseignants", "KBR", "nom_famille") is None
    assert edit.get("/app-state").json()["teacherLabels"]["KBR"] == "Kyllian Bresson"


def test_le_nom_complet_ressaisi_passe_devant_prenom_et_nom(edit, noms) -> None:  # noqa: F811
    assert edit.put("/reference/enseignants/MRI", json={"prenom": "Mary"}).status_code == 200
    assert edit.put("/reference/enseignants/MRI", json={"nom": "Marine Riguet-Lambert"}).status_code == 200
    etat_app = edit.get("/app-state").json()
    assert etat_app["teacherLabels"]["MRI"] == "Marine Riguet-Lambert"
    assert etat_app["teacherIdentites"]["MRI"]["prenom"] == "Marine"
    assert etat_app["teacherIdentites"]["MRI"]["nom"] == "RIGUET-LAMBERT"


def test_prenom_ou_nom_vide_refuse(edit, noms) -> None:  # noqa: F811
    for corps in ({"prenom": "  "}, {"nom_famille": "123"}):
        r = edit.put("/reference/enseignants/MRI", json=corps)
        assert r.status_code == 400, corps
    assert surcharges_reference.origine("enseignants", "MRI", "prenom") is None


def test_les_flux_ics_portent_le_nom_corrige(noms) -> None:
    """`_noms_enseignants` (flux .ics) recompose comme l'écran."""
    from cal_iut.api.main import _noms_enseignants

    surcharges_reference.definir("enseignants", "TCA", "prenom", "Tom")
    prof = SimpleNamespace(code="TCA", prenom="Thomas", nom="CASTELLENGO")
    state = SimpleNamespace(courses=[SimpleNamespace(lead=prof, profs=[])])
    assert _noms_enseignants(state) == {"TCA": "Tom CASTELLENGO"}


# ---------------------------------------------------------------------------
# Téléphone : données personnelles
# ---------------------------------------------------------------------------


def test_telephone_enregistre_normalise_et_trace(edit, noms) -> None:  # noqa: F811
    r = edit.put("/reference/enseignants/MRI", json={"telephone": TELEPHONE})
    assert r.status_code == 200, r.text
    assert r.json()["valeurs"] == {"telephone": TELEPHONE_E164}
    ligne = _ligne(edit, "MRI")
    assert ligne["telephone"] == TELEPHONE_E164 and ligne["telephone_affiche"] == TELEPHONE
    assert ligne["surcharges"]["telephone"]["modifie_par"].startswith("test-edit-")
    trace = [l for l in surcharges_reference.journal() if l["cle"] == "MRI" and l["champ"] == "telephone"][0]
    assert trace["apres"] == TELEPHONE_E164 and trace["par"].startswith("test-edit-")
    assert edit.get("/reference/enseignants").json()["compteurs"]["sans_telephone"] == len(
        edit.get("/app-state").json()["teacherLabels"]
    ) - 1

    r = edit.put("/reference/enseignants/MRI", json={"telephone": "06 12"})
    assert r.status_code == 400 and "téléphone" in r.json()["detail"]
    assert _ligne(edit, "MRI")["telephone"] == TELEPHONE_E164, "un refus ne touche à rien"

    assert edit.delete("/reference/enseignants/MRI/telephone").status_code == 200
    assert _ligne(edit, "MRI")["telephone"] is None


def _numeros(texte: str) -> bool:
    return any(x in texte for x in ("612345678", "12 34 56 78", "12.34.56.78"))


def test_le_telephone_ne_sort_jamais_ailleurs(edit, admin, lecteur, noms) -> None:  # noqa: F811
    assert edit.put("/reference/enseignants/MRI", json={"telephone": TELEPHONE}).status_code == 200
    revision.incrementer("test-telephone")

    # Payload complet (tout compte), lien public, API v1 connectée et publique.
    for client in (edit, admin, lecteur):
        assert not _numeros(client.get("/app-state").text)
        assert not _numeros(client.get("/api/v1/enseignants").text)
        assert not _numeros(client.get("/api/v1/enseignants/MRI").text)
    public = TestClient(app)
    assert not _numeros(public.get("/app-state?t=MRI").text)
    assert public.get("/api/v1/enseignants?t=MRI").status_code == 401

    # Lecture seule : la liste, sans téléphone.
    corps = lecteur.get("/reference/enseignants").json()
    assert corps["telephone_visible"] is False and corps["peut_modifier"] is False
    assert corps["compteurs"]["sans_telephone"] is None
    assert not _numeros(json.dumps(corps))
    mri = next(l for l in corps["lignes"] if l["code"] == "MRI")
    assert mri["telephone"] is None and "telephone" not in mri["surcharges"]
    assert mri["email"] == "marine.riguet@univ.test", "le reste reste visible"

    # Administrateur : visible.
    assert _ligne(admin, "MRI")["telephone"] == TELEPHONE_E164


def test_role_api_et_anonyme_n_ont_pas_l_annuaire(etat, db_isole) -> None:  # noqa: F811
    from test_role_api_2026_09_29 import _compte_connecte

    _id, client = _compte_connecte("api")
    assert client.get("/reference/enseignants").status_code == 403
    assert client.put("/reference/enseignants/MRI", json={"telephone": TELEPHONE}).status_code == 403
    assert TestClient(app).get("/reference/enseignants").status_code == 401
    assert TestClient(app).get("/reference/enseignants?t=MRI").status_code in (401, 403)


# ---------------------------------------------------------------------------
# Type : enseignant / vacataire
# ---------------------------------------------------------------------------


def test_type_enregistre_visible_dans_v1(edit, noms) -> None:  # noqa: F811
    r = edit.put("/reference/enseignants/KBR", json={"type": "Vacataire"})
    assert r.status_code == 200 and r.json()["valeurs"] == {"type": "vacataire"}
    assert edit.put("/reference/enseignants/MRI", json={"type": "enseignant"}).status_code == 200
    assert edit.put("/reference/enseignants/MRI", json={"type": "titulaire"}).status_code == 400

    etat_app = edit.get("/app-state").json()
    assert etat_app["teacherIdentites"]["KBR"]["type"] == "vacataire"
    assert etat_app["teacherLabels"]["KBR"] == "Kyllian Bresson", "le type ne touche pas au nom"
    c = edit.get("/reference/enseignants").json()["compteurs"]
    assert (c["enseignants"], c["vacataires"], c["a_preciser"]) == (1, 1, c["total"] - 2)

    v1 = {e["code"]: e for e in edit.get("/api/v1/enseignants").json()}
    assert v1["KBR"]["type"] == "vacataire" and v1["MRI"]["type"] == "enseignant"
    assert v1["KBR"]["prenom"] == "Kyllian" and v1["KBR"]["nom_famille"] == "BRESSON"
    # Lien public : ni type ni identités dans le payload.
    public = TestClient(app)
    assert public.get("/app-state?t=KBR").json()["teacherIdentites"] == {}
    assert public.get("/api/v1/enseignants?t=KBR").status_code == 401, "v1 : comptes seulement"

    assert edit.delete("/reference/enseignants/KBR/type").status_code == 200
    assert edit.get("/app-state").json()["teacherIdentites"]["KBR"]["type"] is None


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------


def test_droits(edit, admin, lecteur, noms) -> None:  # noqa: F811
    for corps in ({"prenom": "Marine"}, {"nom_famille": "X"}, {"telephone": TELEPHONE}, {"type": "vacataire"}):
        assert lecteur.put("/reference/enseignants/MRI", json=corps).status_code == 403
    assert lecteur.delete("/reference/enseignants/MRI/telephone").status_code == 403
    assert lecteur.get("/reference/enseignants").status_code == 200
    # Code Celcat : administrateurs seulement (inchangé).
    assert edit.put("/reference/enseignants/KBR", json={"code_celcat": "40001"}).status_code == 403
    r = admin.put("/reference/enseignants/JSA", json={"code_celcat": "40001", "type": "vacataire"})
    assert r.status_code == 200, r.text
    assert _ligne(admin, "JSA")["code_celcat"]["code"] == "40001"
    # Le diminutif ne se modifie pas : il n'y a pas de champ pour lui.
    assert edit.put("/reference/enseignants/MRI", json={"code": "MRX"}).status_code == 400
    assert edit.delete("/reference/enseignants/MRI/code").status_code == 422
    assert edit.put("/reference/enseignants/ZZZ", json={"type": "vacataire"}).status_code == 404


# ---------------------------------------------------------------------------
# Nouvel intervenant avec téléphone et type
# ---------------------------------------------------------------------------


def test_nouvel_intervenant_avec_telephone_et_type(admin, noms) -> None:  # noqa: F811
    r = admin.post("/reference/enseignants/verifier", json={"nom": "Zoé Martin", "code": "ZMA", "telephone": "06 12"})
    assert any(e["champ"] == "telephone" for e in r.json()["erreurs"])
    assert admin.post("/reference/enseignants", json={"nom": "Zoé Martin", "code": "ZMA", "type": "stagiaire"}).status_code == 400

    r = admin.post(
        "/reference/enseignants",
        json={"nom": "Zoé MARTIN", "code": "ZMA", "telephone": "+33 6 98 76 54 32", "type": "vacataire"},
    )
    assert r.status_code == 201, r.text
    assert (r.json()["telephone"], r.json()["type"]) == ("+33698765432", "vacataire")
    ligne = _ligne(admin, "ZMA")
    assert (ligne["prenom"], ligne["nom"], ligne["type"], ligne["telephone_affiche"]) == (
        "Zoé", "MARTIN", "vacataire", "06 98 76 54 32",
    )
    assert ligne["cree_dans_appli"] is True
    # Créé avec : pas une « modification » à défaire.
    assert "type" not in admin.get("/app-state").json()["surchargesReference"]["enseignants"].get("ZMA", {})
    # Supprimé : tout part avec lui.
    assert admin.delete("/reference/enseignants/ZMA").status_code == 200
    assert surcharges_reference.origine("enseignants", "ZMA", "telephone") is None


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------


def test_persistance_apres_rechargement(edit, noms) -> None:  # noqa: F811
    corps = {"prenom": "Marine-Alice", "telephone": TELEPHONE, "type": "vacataire"}
    assert edit.put("/reference/enseignants/MRI", json=corps).status_code == 200
    # Sur le disque, dans le volume : `data/state/references.json`.
    doc = json.loads(surcharges_reference._path().read_text(encoding="utf-8"))
    champs = doc["enseignants"]["MRI"]
    assert champs["prenom"]["valeur"] == "Marine-Alice"
    assert champs["telephone"]["valeur"] == TELEPHONE_E164
    assert champs["type"]["valeur"] == "vacataire"
    # Rechargement (nouvelle révision : payload recalculé depuis le disque).
    revision.incrementer("test-rechargement")
    ligne = _ligne(edit, "MRI")
    assert (ligne["prenom"], ligne["type"], ligne["telephone"]) == ("Marine-Alice", "vacataire", TELEPHONE_E164)
    assert ident.surcharges_identite()["MRI"] == {
        "prenom": "Marine-Alice", "type": "vacataire", "telephone": TELEPHONE_E164,
    }
