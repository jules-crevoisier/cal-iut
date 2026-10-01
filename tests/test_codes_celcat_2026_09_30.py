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
    assert _put(admin, "salles", "h018", "H.104").status_code == 200
    assert revision.actuelle().numero > avant
    entree = mappings.charger()["salles"]["h018"]
    assert entree["valeur"] == "H.104" and entree["ajoute_par"].startswith("test-admin-") and entree["ajoute_le"]
    assert (entree["valeur_avant"], entree["valeur_fichier"]) == (None, None)
    assert _put(admin, "salles", "h018", "Amphi 3 MMI").status_code == 200
    assert mappings.charger()["salles"]["h018"]["valeur_avant"] == "H.104"
    ligne = surcharges_reference.journal()[0]
    assert (ligne["famille"], ligne["cle"], ligne["champ"], ligne["avant"], ligne["apres"]) == (
        "salles", "h018", "code_celcat", "H.104", "Amphi 3 MMI",
    )
    vue = _ligne(admin, "salles", "h018")
    assert (vue["origine"], vue["valeur_avant"], vue["modifiable"], vue["peut_revenir"]) == ("appli", "H.104", True, True)


def test_un_code_connu_est_verrouille(admin, etat) -> None:  # noqa: F811
    """« Il faut pouvoir modifier QUE ceux qu'on n'a pas » (30/09/2026)."""
    refus = _put(admin, "salles", "h005", "H.006")
    assert refus.status_code == 409 and "Code déjà connu (fichier de configuration) : H.005" in refus.json()["detail"]
    # Même verrou par les autres chemins d'écriture (une seule fonction).
    assert admin.put("/reference/salles/h005", json={"code_celcat": "H.006"}).status_code == 409
    assert admin.put("/celcat/mappings", json={"famille": "salles", "cle": "h005", "valeur": "H.006"}).status_code == 409
    assert admin.put("/reference/enseignants/MRI", json={"code_celcat": "222"}).status_code == 409
    assert _delete(admin, "salles", "h005").status_code == 404, "rien de saisi : rien à retirer"
    assert not any(mappings.charger().values())
    vue = _ligne(admin, "salles", "h005")
    assert (vue["origine"], vue["origine_detail"], vue["modifiable"], vue["peut_revenir"]) == (
        "fichier", "celcat.yaml", False, False,
    )


def test_revenir_a_manquant(admin, etat) -> None:  # noqa: F811
    assert _put(admin, "salles", "h018", "H.104").status_code == 200
    reponse = _delete(admin, "salles", "h018")
    assert reponse.status_code == 200, reponse.text
    assert (reponse.json()["code"], reponse.json()["origine"]) == (None, "manquant")
    assert "h018" not in load_celcat_config(etat.config_dir).salles
    assert _delete(admin, "salles", "h018").status_code == 404, "plus rien à retirer"
    ligne = surcharges_reference.journal()[0]
    assert (ligne["avant"], ligne["apres"]) == ("H.104", None)
    assert _ligne(admin, "salles", "h018")["origine"] == "manquant"


def test_une_saisie_ancienne_sur_un_code_connu_reste_appliquee_en_lecture_seule(admin, etat) -> None:  # noqa: F811
    """Avant le verrou, on pouvait corriger un code du fichier : la saisie
    reste appliquée (rien ne casse), signalée, et seulement retirable."""
    mappings.definir("salles", "h005", "H.006", par="ancien@iut")
    assert _entree(etat, "td1").salle == "H.006", "toujours appliquée"
    vue = _ligne(admin, "salles", "h005")
    assert (vue["origine"], vue["code"], vue["code_connu"], vue["modifiable"], vue["peut_revenir"]) == (
        "appli", "H.006", "H.005", False, True,
    )
    assert "H.005" in vue["avertissement"]
    assert _put(admin, "salles", "h005", "H.104").status_code == 409
    reponse = _delete(admin, "salles", "h005")
    assert (reponse.json()["code"], reponse.json()["origine"]) == ("H.005", "fichier")
    assert _entree(etat, "td1").salle == "H.005"


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


# ---------------------------------------------------------------------------
# v2 (30/09/2026) : « sans code (voulu) » et codes de la maquette
# ---------------------------------------------------------------------------


def _sans_code(client, famille: str, cle: str, motif: str):
    return client.put("/reference/codes-celcat/sans-code", json={"famille": famille, "cle": cle, "motif": motif})


def test_sans_code_voulu_ne_bloque_plus_et_rien_ne_part(admin, etat) -> None:  # noqa: F811
    assert _sans_code(admin, "cours", "WRX99", " ").status_code == 400, "motif obligatoire"
    assert _sans_code(admin, "cours", "WR101", "pas de code").status_code == 409, "a déjà un code"
    ok = _sans_code(admin, "cours", "wrx99", "Visite, pas une matière")
    assert ok.status_code == 200, ok.text
    assert ok.json()["origine"] == "voulu"

    vue = _ligne(admin, "cours", "WRX99")
    assert (vue["origine"], vue["origine_detail"], vue["motif_sans_code"]) == ("voulu", "appli", "Visite, pas une matière")
    assert vue["peut_retirer_sans_code"] and not vue["modifiable"]
    assert vue["saisi_par"].startswith("test-admin-")
    familles = _familles(admin)
    assert (familles["cours"]["sans_code"], familles["cours"]["voulus"]) == (0, 1)
    # Plus un manque, plus un blocage : « non envoyée (voulu) », rien ne part.
    assert "cours:WRX99:code_celcat" not in {m["id"] for m in admin.get("/reference/manques").json()["manques"]}
    plan = admin.get("/celcat/plan?semaines=10").json()
    assert "module WRX99 sans code Celcat" not in plan["motifs_blocage"]
    assert plan["non_envoyees"] == 1
    assert list(plan["motifs_non_envoi"]) == ["module WRX99 sans code Celcat, voulu : Visite, pas une matière"]
    assert _ligne_plan(admin, "wrx1")["action"] == "non_envoyee"
    entree = _entree(etat, "wrx1")
    assert entree.non_envoyee and not entree.prete and entree.code_module is None
    # Un code ne se saisit pas par-dessus : il faut retirer le statut.
    assert _put(admin, "cours", "WRX99", "TSB0199").status_code == 409
    # Tracé.
    ligne = surcharges_reference.journal()[0]
    assert (ligne["cle"], ligne["champ"], ligne["apres"]) == ("WRX99", "sans_code_voulu", "Visite, pas une matière")

    retrait = admin.delete("/reference/codes-celcat/sans-code", params={"famille": "cours", "cle": "WRX99"})
    assert retrait.status_code == 200 and retrait.json()["origine"] == "manquant"
    assert _motifs(admin).get("module WRX99 sans code Celcat") == 1, "de nouveau un blocage à corriger"
    assert admin.delete("/reference/codes-celcat/sans-code", params={"famille": "cours", "cle": "WRX99"}).status_code == 404


def test_sans_code_voulu_du_fichier_est_en_lecture_seule(admin, lecteur, etat) -> None:  # noqa: F811
    chemin = etat.config_dir / "celcat.yaml"
    chemin.write_text(
        chemin.read_text(encoding="utf-8") + 'sans_code_voulu:\n  cours:\n    WRX99: "Décidé avec Kyllian"\n',
        encoding="utf-8",
    )
    vue = _ligne(admin, "cours", "WRX99")
    assert (vue["origine"], vue["origine_detail"], vue["peut_retirer_sans_code"]) == ("voulu", "celcat.yaml", False)
    refus = admin.delete("/reference/codes-celcat/sans-code", params={"famille": "cours", "cle": "WRX99"})
    assert refus.status_code == 409 and "celcat.yaml" in refus.json()["detail"]
    assert _ligne(lecteur, "cours", "WRX99")["motif_sans_code"] == "Décidé avec Kyllian"
    assert _sans_code(lecteur, "cours", "WRX99", "x y z").status_code == 403


def test_code_de_la_maquette_preenregistre_et_verrouille(admin, etat) -> None:  # noqa: F811
    """Un cours sans code dans le fichier, dont la maquette porte un code
    relevé : le code part vers Celcat sans aucune saisie."""
    assert _motifs(admin).get("module WRX99 sans code Celcat") == 1
    (etat.config_dir / "celcat_modules_maquette.yaml").write_text(
        'modules:\n  WRX99: {code: "TSB0199", origine: "maquette"}\n', encoding="utf-8"
    )
    assert "module WRX99 sans code Celcat" not in _motifs(admin)
    assert _entree(etat, "wrx1").code_module == "TSB0199"
    assert not any("module" in b for b in _ligne_plan(admin, "wrx1")["bloquants"])
    vue = _ligne(admin, "cours", "WRX99")
    assert (vue["code"], vue["origine"], vue["origine_detail"], vue["modifiable"]) == (
        "TSB0199", "maquette", "maquette", False,
    )
    refus = _put(admin, "cours", "WRX99", "TSB0101")
    assert refus.status_code == 409 and "Code déjà connu (maquette)" in refus.json()["detail"]
    assert _familles(admin)["cours"]["maquette"] == 1


def test_le_fichier_passe_devant_la_maquette_et_le_voulu_aussi(etat) -> None:  # noqa: F811
    (etat.config_dir / "celcat_modules_maquette.yaml").write_text(
        'modules:\n  WR101: {code: "TSB0199", origine: "maquette"}\n'
        '  WRX99: {code: "TSB0199", origine: "maquette"}\n',
        encoding="utf-8",
    )
    chemin = etat.config_dir / "celcat.yaml"
    chemin.write_text(chemin.read_text(encoding="utf-8") + 'sans_code_voulu:\n  cours:\n    WRX99: "non"\n', encoding="utf-8")
    cfg = load_celcat_config(etat.config_dir)
    assert cfg.modules["WR101"] == "TSB0101" and cfg.origines["cours"]["WR101"] == "fichier"
    assert "WRX99" not in cfg.modules and cfg.sans_code["cours"]["WRX99"]["source"] == "fichier"


def test_le_worker_retire_une_seance_non_envoyee_sans_la_bloquer(etat) -> None:  # noqa: F811
    from types import SimpleNamespace

    from cal_iut.celcat import logs, nuit

    chemin = etat.config_dir / "celcat.yaml"
    chemin.write_text(chemin.read_text(encoding="utf-8") + 'sans_code_voulu:\n  cours:\n    WRX99: "non"\n', encoding="utf-8")
    entree = _entree(etat, "wrx1")
    job = {"action": "create", "session_id": "wrx1", "semaine": 10}
    a_retirer: list[dict] = []
    bilan = SimpleNamespace(ignores=[])
    assert nuit._retirer_si_non_envoyee(job, "wrx1", entree, a_retirer, bilan)
    assert a_retirer == [job], "retiré de la file : il ne partira jamais"
    kinds = {ligne.get("kind") for ligne in logs.tous()}
    assert "non_envoye" in kinds and "blocked" not in kinds
    # Le crochet immédiat (placement) ne la signale pas comme un échec.
    from cal_iut.celcat import ops

    assert ops._non_envoye_voulu(etat.sessions_by_id["wrx1"]).startswith("module WRX99 sans code Celcat, voulu")
    assert ops._non_envoye_voulu(etat.sessions_by_id["td1"]) is None


# ── Règles de préenregistrement depuis la maquette (`celcat/codes_maquette.py`)


def test_regles_maquette_exact_corrige_m_vers_c_et_manquants() -> None:
    from types import SimpleNamespace as C

    from cal_iut.celcat import codes_maquette

    cours = [
        C(code="WR201", parcours="BUT1", codelement="TSBZ2M01"),
        C(code="WRA401M", parcours="BUT2-CREACOM-FC", codelement="TSBZD01M"),
        C(code="WRX401M", parcours="BUT2-DEV-FI", codelement="TSBZX01M"),  # pas CREACOM
        C(code="WR999", parcours="BUT1", codelement="TSBZ9999"),  # non relevé
        C(code="WS1PJ", parcours="BUT1", codelement="TSBZ15PJ"),  # voulu
        C(code="WR101", parcours="BUT1", codelement="TSBZ1M01"),  # déjà au fichier
        C(code="WR202", parcours="BUT1", codelement="TSBZ1M99"),  # code déjà pris
        C(code="WR100BU", parcours="BUT1", codelement=None),
    ]
    releve = {c: "" for c in ("TSBZ2M01", "TSBZD01C", "TSBZD01D", "TSBZX01C", "TSBZ15PJ", "TSBZ1M01", "TSBZ1M99")}
    retenus, manquants, exclus = codes_maquette.calculer(
        cours, modules_fichier={"WR101": "TSBZ1M01", "WR102": "TSBZ1M99"}, sans_code_voulu={"WS1PJ"}, releve=releve
    )
    assert exclus == []
    assert {r.cours: (r.code, r.origine) for r in retenus} == {
        "WR201": ("TSBZ2M01", "maquette"),
        "WRA401M": ("TSBZD01C", "maquette (corrigé M→C)"),
    }
    assert {c for c, _ in manquants} == {"WRX401M", "WR999", "WR202", "WR100BU"}


def test_la_config_reelle_preenregistre_la_maquette_et_les_voulus() -> None:
    """Le fichier généré est cohérent : codes relevés, aucun doublon avec
    celcat.yaml, rien pour un cours « sans code (voulu) »."""
    from pathlib import Path

    import yaml

    from cal_iut.celcat import codes_maquette

    config = Path(__file__).resolve().parents[1] / "data" / "config"
    data = yaml.safe_load((config / "celcat.yaml").read_text(encoding="utf-8"))
    voulus = set(data["sans_code_voulu"]["cours"])
    # WR100BU a quitté « sans code (voulu) » le 01/10/2026 : il part sans
    # module, par la règle `regles_envoi.cours` (Kyllian Bresson).
    assert voulus == {"WS1PJ", "WS3PJ", "WSA3PRJ", "WS5PJ", "WSA5PRJ", "COR", "PCA", "PRP", "RC", "RN", "RRI"}
    maquette = codes_maquette.lire(config)
    releve = codes_maquette.releve_des_matieres(config)
    fichier = {str(v).upper() for v in data["modules"].values()}
    assert maquette, "codes de la maquette préenregistrés"
    assert all(e["code"] in releve for e in maquette.values())
    assert not {e["code"] for e in maquette.values()} & fichier
    assert not set(maquette) & voulus
    assert len({e["code"] for e in maquette.values()}) == len(maquette)
    cfg = load_celcat_config(config)
    assert (cfg.modules["WR201"], cfg.origines["cours"]["WR201"]) == ("TSBZ2M01", "maquette")
    assert (cfg.modules["WRA401M"], cfg.origines["cours"]["WRA401M"]) == ("TSBZD01C", "maquette (corrigé M→C)")
    assert "WR100BU" not in cfg.modules and "WR100BU" not in cfg.sans_code["cours"]
    assert cfg.regle_sans_module("WR100BU") is not None and "WR100BU" not in maquette
    # Exclus par prudence (un code repris est verrouillé) : restent manquants.
    exclus = codes_maquette.lire_exclus(config)
    assert set(exclus) == {"WRA410C", "WSA611C", "WS103", "WS104", "WS105"}
    assert not set(exclus) & set(maquette)
    assert not {"WRA410C", "WSA611C", "WS103", "WS104", "WS105"} & set(cfg.modules)
    assert set(data["codes_a_confirmer"]["cours"]) == {"WS103", "WS104", "WS105"}
    # Aucun code repris dont le nom Celcat désigne un autre cours.
    for cours, entree in maquette.items():
        corrige = entree["origine"] != "maquette"
        assert not codes_maquette.nom_designe_un_autre_cours(cours, releve.get(entree["code"], ""), corrige=corrige), cours


def test_exclusion_nom_celcat_d_un_autre_cours() -> None:
    from types import SimpleNamespace as C

    from cal_iut.celcat import codes_maquette

    releve = {
        "TSBZF51C": "WSA612C Alternance",  # nomme un autre cours
        "TSBZD10C": "WRA410CS Cryptographie",  # discordance de nom
        "TSBZF66C": "WSA666 Projet fin de BUT",  # sans la lettre de parcours : admis
        "TSBZD01C": "WRA401C Anglais",  # variante C d'un corrigé M→C : admis
        "TSBZ2M01": "Anglais",  # pas de code en tête : admis
    }
    cours = [
        C(code="WSA611C", parcours="BUT2-CREACOM-FC", codelement="TSBZF51C"),
        C(code="WRA410C", parcours="BUT2-CREACOM-FC", codelement="TSBZD10C"),
        C(code="WSA666C", parcours="BUT3-CREACOM-FC", codelement="TSBZF66C"),
        C(code="WRA401M", parcours="BUT2-CREACOM-FC", codelement="TSBZD01M"),
        C(code="WR201", parcours="BUT1", codelement="TSBZ2M01"),
    ]
    retenus, manquants, exclus = codes_maquette.calculer(
        cours, modules_fichier={}, sans_code_voulu=set(), releve=releve
    )
    assert {r.cours for r in retenus} == {"WSA666C", "WRA401M", "WR201"}
    assert {(c, code) for c, code, _ in exclus} == {("WSA611C", "TSBZF51C"), ("WRA410C", "TSBZD10C")}
    assert "WSA612C" in next(r for c, _, r in exclus if c == "WSA611C")
    assert manquants == []


def test_exclusion_code_a_confirmer() -> None:
    from types import SimpleNamespace as C

    from cal_iut.celcat import codes_maquette

    retenus, _, exclus = codes_maquette.calculer(
        [C(code="WS103", parcours="BUT1", codelement="TSBZ1353"), C(code="WS101", parcours="BUT1", codelement="TSBZ1151")],
        modules_fichier={}, sans_code_voulu=set(), releve={"TSBZ1353": "WS103 SAE", "TSBZ1151": "WS101 SAE"},
        a_confirmer={"WS103": "à redemander"},
    )
    assert [r.cours for r in retenus] == ["WS101"]
    assert exclus == [("WS103", "TSBZ1353", "à faire confirmer (à redemander)")]


def test_un_code_de_maquette_exclu_reste_manquant_et_saisissable(admin, etat) -> None:  # noqa: F811
    (etat.config_dir / "celcat_modules_maquette.yaml").write_text(
        'modules: {}\nexclus:\n  WRX99: {maquette: "TSB0199", raison: "à faire confirmer (à redemander)"}\n',
        encoding="utf-8",
    )
    assert _motifs(admin).get("module WRX99 sans code Celcat") == 1, "non repris : toujours bloqué"
    vue = _ligne(admin, "cours", "WRX99")
    assert (vue["origine"], vue["code_maquette"], vue["modifiable"]) == ("manquant", "TSB0199", True)
    assert vue["note"] == "Code de la maquette non repris : à faire confirmer (à redemander)."
    assert _put(admin, "cours", "WRX99", "TSB0199").status_code == 200, "un admin le confirme en le saisissant"
    assert _entree(etat, "wrx1").code_module == "TSB0199"
