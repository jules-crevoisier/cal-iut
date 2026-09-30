"""Onglet « Codes Celcat » de Référence (30/09/2026).

Demande utilisateur : « un onglet, quelque part où on pouvait renseigner les
codes Celcat pour les cours et les salles aussi [...] Que l'utilisateur
puisse enregistrer les codes comme ça et ils sont enregistrés pour Celcat. »

Ce que ces tests protègent :

- `GET /reference/codes-celcat` liste TOUTES les entités du planning par
  famille (cours, salles, enseignants, groupes), avec le code qui part vers
  Celcat, son origine (fichier / saisi dans l'appli / manquant) et le nombre
  de séances — lisible par tout compte actif, l'auteur d'une saisie
  seulement pour un administrateur ;
- une saisie est validée par famille (format), refusée si le code est déjà
  celui d'une autre entité (sauf salle fusionnée / sa moitié), tracée (qui,
  quand, valeur d'avant, valeur du fichier), réservée aux administrateurs ;
- « Revenir à la valeur du fichier » retire la saisie ;
- DE BOUT EN BOUT, par famille : sans code la séance est bloquée ; code
  saisi, le plan Celcat et le worker portent ce code ; effacé, on revient au
  fichier ;
- les groupes restent en lecture seule (identifiant interne).
"""

from __future__ import annotations

from test_completer_reference_2026_09_29 import (  # noqa: F401 — fixtures partagées
    admin,
    edit,
    etat,
    lecteur,
)

from cal_iut.api import revision
from cal_iut.celcat import mappings
from cal_iut.celcat.mapping import entrees_pour_state, load_celcat_config
from cal_iut.ingestion import surcharges_reference
from cal_iut.models.entities import Room, RoomType


def _familles(client, famille: str | None = None) -> dict:
    url = "/reference/codes-celcat" + (f"?famille={famille}" if famille else "")
    reponse = client.get(url)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["familles"]


def _ligne(client, famille: str, cle: str) -> dict:
    return next(l for l in _familles(client)[famille]["lignes"] if l["cle"] == cle)


def _put(client, famille: str, cle: str, code: str):
    return client.put("/reference/codes-celcat", json={"famille": famille, "cle": cle, "code": code})


def _delete(client, famille: str, cle: str):
    return client.delete("/reference/codes-celcat", params={"famille": famille, "cle": cle})


def _motifs(client) -> dict[str, int]:
    return client.get("/celcat/plan?semaines=10").json()["motifs_blocage"]


# ---------------------------------------------------------------------------
# La liste, par famille
# ---------------------------------------------------------------------------


def test_la_liste_couvre_toutes_les_entites_de_chaque_famille(lecteur) -> None:  # noqa: F811
    familles = _familles(lecteur)
    assert set(familles) == {"cours", "salles", "enseignants", "groupes"}

    cours = {l["cle"]: l for l in familles["cours"]["lignes"]}
    assert (cours["WR101"]["code"], cours["WR101"]["origine"], cours["WR101"]["nb_seances"]) == ("TSB0101", "fichier", 3)
    assert (cours["WRX99"]["code"], cours["WRX99"]["origine"], cours["WRX99"]["nb_seances"]) == (None, "manquant", 1)
    assert cours["WR101"]["semestre"] == "S1" and cours["WR101"]["parcours"] == "BUT1"

    salles = {l["cle"]: l for l in familles["salles"]["lignes"]}
    assert set(salles) == {"h005", "h018", "annexe"}
    assert (salles["h005"]["code"], salles["h005"]["origine"]) == ("H.005", "fichier")
    assert salles["h018"]["origine"] == "manquant" and salles["h018"]["capacite"] == 150
    assert salles["h018"]["type_salle"] == "amphi"

    ens = {l["cle"]: l for l in familles["enseignants"]["lignes"]}
    assert {"MRI", "KBR", "JSA"} <= set(ens)
    assert (ens["MRI"]["code"], ens["MRI"]["origine"]) == ("111", "fichier")
    # « 0 » dans le fichier : pas un code.
    assert (ens["KBR"]["code"], ens["KBR"]["origine"]) == (None, "manquant")

    groupes = {l["cle"]: l for l in familles["groupes"]["lignes"]}
    assert (groupes["BUT MMI S1 TD AB"]["code"], groupes["BUT MMI S1 TD AB"]["origine"]) == ("1", "fichier")
    assert groupes["BUT MMI S1 CM"]["origine"] == "manquant"
    assert "celcat_groupes.yaml" in groupes["BUT MMI S1 CM"]["note"]

    # Compteurs par famille : les pastilles des sous-onglets.
    assert familles["cours"]["sans_code"] == 1 and familles["cours"]["sans_code_bloquants"] == 1
    assert familles["salles"]["sans_code"] == 2
    assert familles["enseignants"]["total"] == len(familles["enseignants"]["lignes"])


def test_lecture_seule_pour_un_non_admin_sans_l_auteur(lecteur, admin) -> None:  # noqa: F811
    assert _put(admin, "enseignants", "KBR", "38999").status_code == 200
    vue_lecteur = _ligne(lecteur, "enseignants", "KBR")
    assert vue_lecteur["origine"] == "appli" and vue_lecteur["code"] == "38999"
    assert vue_lecteur["saisi_le"] and vue_lecteur["saisi_par"] is None, "l'adresse d'un compte reste aux admins"
    assert not vue_lecteur["modifiable"]
    assert not any(f["modifiable"] for f in _familles(lecteur).values())
    vue_admin = _ligne(admin, "enseignants", "KBR")
    assert vue_admin["saisi_par"].startswith("test-admin-") and vue_admin["modifiable"]
    familles = _familles(admin)
    assert familles["cours"]["modifiable"] and not familles["groupes"]["modifiable"]
    assert not any(l["modifiable"] for l in familles["groupes"]["lignes"])


def test_suggestions_et_filtre_par_famille(admin) -> None:  # noqa: F811
    familles = _familles(admin, "salles")
    assert familles["salles"]["lignes"] and not familles["cours"]["lignes"], "seules les lignes de la famille"
    assert familles["cours"]["sans_code"] == 1, "les compteurs des autres restent"
    assert "TSB0199" in familles["cours"]["suggestions"]
    assert "H.005" in familles["salles"]["suggestions"]


def test_compte_obligatoire_et_saisie_admin(etat, db_isole, edit, lecteur) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    from cal_iut.api.main import app

    assert TestClient(app).get("/reference/codes-celcat").status_code == 401
    assert _put(edit, "salles", "h018", "Amphi 3 MMI").status_code == 403
    assert _put(lecteur, "salles", "h018", "Amphi 3 MMI").status_code == 403
    assert _delete(edit, "salles", "h005").status_code == 403
    assert not mappings.charger()["salles"]


# ---------------------------------------------------------------------------
# Validation, doublons, trace
# ---------------------------------------------------------------------------


def test_format_valide_par_famille(admin, etat) -> None:  # noqa: F811
    assert _put(admin, "enseignants", "KBR", "abc").status_code == 400
    assert _put(admin, "enseignants", "KBR", "0").status_code == 400
    refus = _put(admin, "salles", "h018", "H104")
    assert refus.status_code == 400 and "H.104" in refus.json()["detail"]
    assert _put(admin, "cours", "WRX99", "WR101").status_code == 400
    inconnu = _put(admin, "cours", "WRX99", "TSBZ9999")
    assert inconnu.status_code == 400 and "celcat_matieres.yaml" in inconnu.json()["detail"]
    assert _put(admin, "salles", "inconnue", "H.104").status_code == 404
    assert _put(admin, "cours", "WRZZZ", "TSB0199").status_code == 404
    assert not any(mappings.charger().values())
    # Nettoyé : « h.104 » -> « H.104 », « tsb0199 » -> « TSB0199 », clé canonique.
    assert _put(admin, "salles", "H018", "h.104").json()["code"] == "H.104"
    assert load_celcat_config(etat.config_dir).salles["h018"] == "H.104"
    assert _put(admin, "cours", "wrx99", " tsb0199 ").json()["code"] == "TSB0199"


def test_un_code_deja_pris_est_refuse(admin, etat) -> None:  # noqa: F811
    refus = _put(admin, "enseignants", "KBR", "111")
    assert refus.status_code == 409 and "MRI" in refus.json()["detail"]
    refus = _put(admin, "cours", "WRX99", "TSB0101")
    assert refus.status_code == 409 and "WR101" in refus.json()["detail"]
    refus = _put(admin, "salles", "h018", "h.005")
    assert refus.status_code == 409 and "h005" in refus.json()["detail"]
    # Même règle par les autres chemins d'écriture (une seule fonction).
    assert admin.put("/reference/enseignants/KBR", json={"code_celcat": "111"}).status_code == 409
    assert admin.put("/celcat/mappings", json={"famille": "enseignants", "cle": "KBR", "valeur": "111"}).status_code == 409
    assert not any(mappings.charger().values())


def test_une_salle_fusionnee_peut_porter_le_code_de_sa_moitie(admin, etat) -> None:  # noqa: F811
    """H.007-008 porte « H.007 » (décision du 31/08/2026) : seul doublon légitime."""
    etat.rooms = [*etat.rooms, Room(
        id="h005_h018", label="H.005-018", capacity=40, room_type=RoomType.COMBINED, combines=["h005", "h018"],
    )]
    ok = _put(admin, "salles", "h005_h018", "H.005")
    assert ok.status_code == 200, ok.text
    assert load_celcat_config(etat.config_dir).salles["h005_h018"] == "H.005"
    assert "Salles réunies" in (_ligne(admin, "salles", "h005_h018")["note"] or "")


def test_la_saisie_est_tracee(admin, etat) -> None:  # noqa: F811
    avant = revision.actuelle().numero
    assert _put(admin, "salles", "h005", "H.006").status_code == 200
    assert revision.actuelle().numero > avant
    entree = mappings.charger()["salles"]["h005"]
    assert entree["valeur"] == "H.006" and entree["ajoute_par"].startswith("test-admin-") and entree["ajoute_le"]
    assert (entree["valeur_avant"], entree["valeur_fichier"]) == ("H.005", "H.005")
    assert _put(admin, "salles", "h005", "H.104").status_code == 200
    assert mappings.charger()["salles"]["h005"]["valeur_avant"] == "H.006"
    ligne = surcharges_reference.journal()[0]
    assert (ligne["famille"], ligne["cle"], ligne["champ"], ligne["avant"], ligne["apres"], ligne["valeur_fichier"]) == (
        "salles", "h005", "code_celcat", "H.006", "H.104", "H.005",
    )
    assert _ligne(admin, "salles", "h005")["valeur_avant"] == "H.006"


def test_saisir_la_valeur_du_fichier_retire_la_saisie(admin, etat) -> None:  # noqa: F811
    assert _put(admin, "salles", "h005", "H.006").json()["origine"] == "appli"
    reponse = _put(admin, "salles", "h005", "H.005")
    assert reponse.status_code == 200 and reponse.json()["origine"] == "fichier"
    assert "h005" not in mappings.charger()["salles"]
    assert _ligne(admin, "salles", "h005")["origine"] == "fichier"


def test_revenir_a_la_valeur_du_fichier(admin, etat) -> None:  # noqa: F811
    assert _put(admin, "salles", "h005", "H.006").status_code == 200
    reponse = _delete(admin, "salles", "h005")
    assert reponse.status_code == 200, reponse.text
    assert (reponse.json()["code"], reponse.json()["origine"]) == ("H.005", "fichier")
    assert load_celcat_config(etat.config_dir).salles["h005"] == "H.005"
    assert _delete(admin, "salles", "h005").status_code == 404, "plus rien à retirer"
    ligne = surcharges_reference.journal()[0]
    assert (ligne["avant"], ligne["apres"]) == ("H.006", "H.005")


def test_les_groupes_restent_en_lecture_seule(admin) -> None:  # noqa: F811
    refus = _put(admin, "groupes", "BUT MMI S1 CM", "1661971")
    assert refus.status_code == 409 and "celcat_groupes.yaml" in refus.json()["detail"]
    assert _delete(admin, "groupes", "BUT MMI S1 CM").status_code == 409
    assert set(mappings.charger()) == {"salles", "enseignants", "matieres"}


def test_les_manques_menent_a_la_bonne_ligne(lecteur) -> None:  # noqa: F811
    par_id = {m["id"]: m for m in lecteur.get("/reference/manques").json()["manques"]}
    assert par_id["cours:WRX99:code_celcat"]["ecran"] == {
        "vue": "reference", "onglet": "codes-celcat", "famille": "cours", "cle": "WRX99",
    }
    assert par_id["salle:h018:code_celcat"]["ecran"]["famille"] == "salles"
    assert par_id["enseignant:KBR:code_celcat"]["ecran"]["cle"] == "KBR"
    assert par_id["groupe:BUT MMI S1 CM:id_celcat"]["ecran"]["famille"] == "groupes"


# ---------------------------------------------------------------------------
# De bout en bout : pris en compte par le plan et par le worker
# ---------------------------------------------------------------------------


def _entree(etat, session_id: str):  # noqa: F811
    """Ce que construit le worker (`nuit.py` via `entrees_pour_state`)."""
    return entrees_pour_state(etat)[session_id]


def _ligne_plan(client, session_id: str) -> dict:
    plan = client.get("/celcat/plan?semaines=10").json()
    return next(e for e in plan["entrees"] if e["session_id"] == session_id)


def test_bout_en_bout_cours(admin, etat) -> None:  # noqa: F811
    motif = "module WRX99 sans code Celcat"
    assert _motifs(admin).get(motif) == 1
    assert _put(admin, "cours", "WRX99", "TSB0199").status_code == 200
    assert motif not in _motifs(admin)
    assert _entree(etat, "wrx1").code_module == "TSB0199"
    ligne_plan = _ligne_plan(admin, "wrx1")
    assert not any("module" in b for b in ligne_plan["bloquants"]), ligne_plan
    assert _delete(admin, "cours", "WRX99").status_code == 200
    assert _motifs(admin).get(motif) == 1, "effacé : de nouveau bloqué (pas de code dans le fichier)"


def test_bout_en_bout_salles(admin, etat) -> None:  # noqa: F811
    motif = "salle « h018 » sans équivalent Celcat (cf. data/config/celcat.yaml)"
    assert _motifs(admin).get(motif) == 1
    assert _put(admin, "salles", "h018", "Amphi 3 MMI").status_code == 200
    assert motif not in _motifs(admin)
    assert _entree(etat, "cm1").salle == "Amphi 3 MMI"
    assert _ligne_plan(admin, "cm1")["salle"] == "Amphi 3 MMI", "le plan porte le code saisi"
    # Une salle du fichier corrigée puis rétablie : le plan suit.
    assert _put(admin, "salles", "h005", "H.006").status_code == 200
    assert _entree(etat, "td1").salle == "H.006"
    assert _delete(admin, "salles", "h005").status_code == 200
    assert _entree(etat, "td1").salle == "H.005"
    assert _delete(admin, "salles", "h018").status_code == 200
    assert _motifs(admin).get(motif) == 1


def test_bout_en_bout_enseignants(admin, etat) -> None:  # noqa: F811
    motif = "enseignant KBR sans code Celcat"
    assert _motifs(admin).get(motif) == 1
    assert _put(admin, "enseignants", "kbr", "38999").status_code == 200
    assert motif not in _motifs(admin)
    assert _entree(etat, "cm1").code_enseignant == "38999"
    assert _delete(admin, "enseignants", "KBR").status_code == 200
    assert _motifs(admin).get(motif) == 1
    assert _entree(etat, "cm1").code_enseignant is None
