"""Compléter une information de référence manquante depuis l'appli.

Demande utilisateur (29/09/2026) : « quand on a un email manquant, peut-être
un numéro de salle Celcat manquant, etc., il faut pouvoir ajouter l'info et
l'enregistrer ». Ce que ces tests protègent :

- `GET /reference/manques` (et `GET /api/v1/manques`) liste TOUT ce qui
  manque — mail, nom et code Celcat d'enseignant, code Celcat et type de
  salle, intitulé et code Celcat de matière, identifiant Celcat de groupe,
  salle d'une séance —, sans jamais exposer une valeur ;
- chaque route valide (format, entité connue, doublon d'adresse), respecte
  les droits (`edit` ; Celcat `admin`), persiste dans le volume
  (`data/state/`, jamais `data/config/`), avance la révision et journalise ;
- la surcouche est fusionnée SOUS la config au chargement : elle comble un
  manque, la config garde le dernier mot.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import custom_rooms, revision
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import mappings
from cal_iut.celcat.mapping import load_celcat_config
from cal_iut.ingestion import surcharges_reference
from cal_iut.ingestion.config_loader import load_groups, load_teacher_contacts
from cal_iut.ingestion.enseignants import enseignants_declares
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")


def _seance(sid: str, cours: str, nom: str, groupe: str, prof: str, type_: SessionType = SessionType.TD) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=cours, course_name=nom, semestre="S1", parcours="BUT1", annee="BUT1",
        session_type=type_, sequence_order=1, group_ids=[groupe], teacher_codes=[prof],
    )


def _place(s: SessionToPlace, week: int, day: int, slot: int, room: str | None = None) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
        room_id=room, room_label=room.upper() if room else None,
    )


def _config(racine: Path) -> Path:
    """Copie de la vraie config, avec des tables Celcat et des contacts
    minimaux et connus — rien de `data/config/` n'est jamais écrit."""
    config = racine / "data" / "config"
    shutil.copytree(ROOT / "data" / "config", config)
    (config / "teacher_contacts.yaml").write_text("contacts:\n  MRI: marine.riguet@univ.test\n", encoding="utf-8")
    (config / "celcat.yaml").write_text(
        "enseignants:\n  MRI: \"111\"\n  KBR: \"0\"\n"
        "salles:\n  h005: \"H.005\"\n"
        "types_seance:\n  TD: 4\n  TP: 6\n"
        "modules:\n  WR101: \"TSB0101\"\n",
        encoding="utf-8",
    )
    # TSB0199 : un code relevé LIBRE — TSB0101 est déjà celui de WR101, et
    # deux cours ne partagent pas un module (`api/codes_celcat.py`, 30/09/2026).
    (config / "celcat_matieres.yaml").write_text('"TSB0101": 1\n"TSB0199": 3\n', encoding="utf-8")
    (config / "celcat_groupes.yaml").write_text('"BUT MMI S1 TD AB": 1\n', encoding="utf-8")
    return config


@pytest.fixture
def etat(tmp_path):
    """MRI (mail et code Celcat connus), KBR (ni l'un ni l'autre, code « 0 »),
    JSA (sans nom, sans mail, sans code). Salles : h005 (Celcat connu), h018
    (sans correspondance), « annexe » ajoutée à la main (type imposé)."""
    etat = get_state()
    cles = (
        "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar", "current_run_id",
        "teacher_availability", "teacher_duos", "corrections", "courses", "config_dir",
        "student_presences", "filter_semestre", "filter_parcours", "semestre_group",
    )
    ancien = {cle: getattr(etat, cle) for cle in cles}
    td = _seance("td1", "WR101", "Culture numérique", "but1-td-ab", "MRI")
    cm = _seance("cm1", "WR101", "Culture numérique", "but1-promo", "KBR", SessionType.CM)
    autre = _seance("autre1", "WR101", "Culture numérique", "but1-td-cd", "JSA")
    muette = _seance("wrx1", "WRX99", "", "but1-td-ab", "MRI")
    etat.sessions = [td, cm, autre, muette]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        _place(td, 10, 0, 0, "h005"), _place(cm, 10, 1, 1, "h018"), _place(autre, 10, 2, 2),
        _place(muette, 10, 3, 3, "annexe"),
    ]
    annexe = Room(id="annexe", label="Annexe", capacity=30, room_type=RoomType.STANDARD)
    custom_rooms.add_custom_room(annexe)
    etat.groups = GROUPES
    etat.rooms = [
        Room(id="h005", label="H.005", capacity=15, room_type=RoomType.TP_STANDARD),
        Room(id="h018", label="H.018", capacity=150, room_type=RoomType.AMPHI),
        annexe,
    ]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.student_presences = []
    etat.config_dir = _config(tmp_path)
    etat.filter_semestre = "S1"
    etat.filter_parcours = None
    etat.semestre_group = None
    revision.incrementer("test-reference")
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _compte(role: str) -> TestClient:
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role=role)
    return c


@pytest.fixture
def edit(etat, db_isole) -> TestClient:
    return _compte("edit")


@pytest.fixture
def admin(etat, db_isole) -> TestClient:
    return _compte("admin")


@pytest.fixture
def lecteur(etat, db_isole) -> TestClient:
    return _compte("read_only")


def _ids(client: TestClient) -> set[str]:
    reponse = client.get("/reference/manques")
    assert reponse.status_code == 200, reponse.text
    return {m["id"] for m in reponse.json()["manques"]}


# ---------------------------------------------------------------------------
# La liste des manques
# ---------------------------------------------------------------------------


def test_la_liste_couvre_chaque_famille(lecteur) -> None:
    corps = lecteur.get("/reference/manques").json()
    ids = {m["id"] for m in corps["manques"]}
    attendus = {
        "enseignant:KBR:email", "enseignant:JSA:email", "enseignant:JSA:nom",
        "enseignant:KBR:code_celcat", "enseignant:JSA:code_celcat",
        "salle:h018:code_celcat", "salle:annexe:code_celcat", "salle:annexe:type",
        "cours:WRX99:intitule", "cours:WRX99:code_celcat",
        "groupe:BUT MMI S1 CM:id_celcat", "groupe:BUT MMI S1 TD CD:id_celcat",
        "seance:autre1:salle",
    }
    assert attendus <= ids, attendus - ids
    # Ce qui est connu n'y est pas.
    assert not {"enseignant:MRI:email", "enseignant:MRI:code_celcat", "salle:h005:code_celcat",
                "cours:WR101:intitule", "cours:WR101:code_celcat", "groupe:BUT MMI S1 TD AB:id_celcat"} & ids
    assert corps["total"] == len(corps["manques"])
    assert sum(corps["par_gravite"].values()) == corps["total"]


def test_gravite_droits_et_ecran(lecteur) -> None:
    par_id = {m["id"]: m for m in lecteur.get("/reference/manques").json()["manques"]}
    mail = par_id["enseignant:KBR:email"]
    assert (mail["gravite"], mail["role_requis"], mail["ecran"]) == ("bloque_envoi_liens", "edit", {"vue": "prof", "prof": "KBR"})
    assert mail["nb_seances"] == 1 and mail["usage"] == "1 séance placée"
    celcat = par_id["salle:h018:code_celcat"]
    assert (celcat["gravite"], celcat["role_requis"]) == ("bloque_celcat", "admin")
    # Identifiants internes Celcat : listés, mais pas saisissables dans l'appli.
    assert par_id["groupe:BUT MMI S1 CM:id_celcat"]["role_requis"] is None
    assert "celcat_groupes.yaml" in par_id["groupe:BUT MMI S1 CM:id_celcat"]["ou_completer"]
    assert par_id["cours:WRX99:intitule"]["gravite"] == "cosmetique"
    assert par_id["seance:autre1:salle"]["ecran"] == {"vue": "promo", "sem": 10, "jour": 2}
    # Le plus grave d'abord.
    gravites = [m["gravite"] for m in lecteur.get("/reference/manques").json()["manques"]]
    assert gravites == sorted(gravites, key=["bloque_celcat", "bloque_envoi_liens", "cosmetique"].index)


def test_aucune_valeur_n_est_exposee(lecteur) -> None:
    # Les manques seuls : la révision (horodatage en millisecondes) pourrait
    # contenir « 111 » par hasard.
    texte = json.dumps(lecteur.get("/reference/manques").json()["manques"], ensure_ascii=False)
    assert "marine.riguet@univ.test" not in texte
    assert "111" not in texte and "TSB0101" not in texte


def test_compte_obligatoire(etat, db_isole) -> None:
    anonyme = TestClient(app)
    assert anonyme.get("/reference/manques").status_code == 401
    assert anonyme.get("/reference/manques?t=MRI").status_code == 401
    assert anonyme.put("/reference/enseignants/KBR/contact", json={"email": "k@univ.test"}).status_code == 401


# ---------------------------------------------------------------------------
# Mail d'un enseignant
# ---------------------------------------------------------------------------


def test_ajouter_un_mail_le_normalise_le_persiste_et_avance_la_revision(edit, etat) -> None:
    avant = revision.actuelle().numero
    reponse = edit.put("/reference/enseignants/kbr/contact", json={"email": "  Kyllian.Bresson@Univ.TEST "})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["valeurs"] == {"email": "kyllian.bresson@univ.test"}
    assert corps["revision"] > avant
    assert revision.actuelle().numero > avant

    # Persisté dans le volume, daté, avec son auteur — jamais dans la config.
    brut = json.loads(surcharges_reference._path().read_text(encoding="utf-8"))
    entree = brut["enseignants"]["KBR"]["email"]
    assert entree["valeur"] == "kyllian.bresson@univ.test"
    assert entree["modifie_par"].startswith("test-edit-") and entree["modifie_le"]
    assert "KBR" not in (etat.config_dir / "teacher_contacts.yaml").read_text(encoding="utf-8")

    # Relu par le chargeur (état rechargé), par /app-state et par la liste.
    assert load_teacher_contacts(etat.config_dir)["KBR"] == "kyllian.bresson@univ.test"
    assert edit.get("/app-state").json()["teacherEmails"]["KBR"] == "kyllian.bresson@univ.test"
    assert "enseignant:KBR:email" not in _ids(edit)

    ligne = surcharges_reference.journal()[0]
    assert (ligne["famille"], ligne["cle"], ligne["champ"], ligne["avant"], ligne["apres"]) == (
        "enseignants", "KBR", "email", None, "kyllian.bresson@univ.test",
    )


@pytest.mark.parametrize("adresse", ["", "kyllian", "kyllian@", "@univ.test", "k b@univ.test", "k@univ", "k@@univ.test", "k@univ..test"])
def test_un_mail_mal_forme_est_refuse(edit, adresse) -> None:
    reponse = edit.put("/reference/enseignants/KBR/contact", json={"email": adresse})
    assert reponse.status_code == 400, adresse
    assert not surcharges_reference._path().exists(), "rien d'écrit sur un refus"


def test_un_mail_deja_attribue_est_refuse(edit) -> None:
    reponse = edit.put("/reference/enseignants/KBR/contact", json={"email": "MARINE.riguet@univ.test"})
    assert reponse.status_code == 409
    assert "MRI" in reponse.json()["detail"]
    # Doublon avec une adresse saisie dans l'appli, pas seulement du fichier.
    assert edit.put("/reference/enseignants/KBR/contact", json={"email": "k@univ.test"}).status_code == 200
    assert edit.put("/reference/enseignants/JSA/contact", json={"email": "K@univ.test"}).status_code == 409
    # Corriger SA propre saisie reste possible.
    assert edit.put("/reference/enseignants/KBR/contact", json={"email": "k@univ.test"}).status_code == 200


def test_un_mail_du_fichier_se_corrige_dans_l_appli_puis_s_efface(edit, etat) -> None:
    """Suite du 29/09/2026 (« go ») : la saisie a le dernier mot sur le
    fichier ; la trace garde la valeur d'avant ET celle du fichier ; DELETE
    rétablit la valeur du fichier."""
    avant = revision.actuelle().numero
    reponse = edit.put("/reference/enseignants/MRI/contact", json={"email": "Marine.R@Univ.test"})
    assert reponse.status_code == 200, reponse.text
    assert load_teacher_contacts(etat.config_dir)["MRI"] == "marine.r@univ.test"
    assert revision.actuelle().numero > avant
    ligne = surcharges_reference.journal()[0]
    assert (ligne["avant"], ligne["apres"], ligne["valeur_fichier"]) == (None, "marine.r@univ.test", "marine.riguet@univ.test")
    assert ligne["par"].startswith("test-edit-")
    # La marque « modifiée dans l'appli » et la valeur d'origine sont servies.
    surcharge = edit.get("/app-state").json()["surchargesReference"]["enseignants"]["MRI"]["email"]
    assert (surcharge["valeur"], surcharge["origine"]) == ("marine.r@univ.test", "marine.riguet@univ.test")
    assert surcharge["modifie_par"].startswith("test-edit-")

    avant = revision.actuelle().numero
    retour = edit.delete("/reference/enseignants/MRI/contact")
    assert retour.status_code == 200, retour.text
    assert load_teacher_contacts(etat.config_dir)["MRI"] == "marine.riguet@univ.test"
    assert revision.actuelle().numero > avant
    ligne = surcharges_reference.journal()[0]
    assert (ligne["avant"], ligne["apres"], ligne["valeur_fichier"]) == ("marine.r@univ.test", None, "marine.riguet@univ.test")
    assert "MRI" not in edit.get("/app-state").json()["surchargesReference"]["enseignants"]
    assert edit.delete("/reference/enseignants/MRI/contact").status_code == 404


def test_resaisir_la_valeur_du_fichier_retire_la_surcharge(edit, etat) -> None:
    assert edit.put("/reference/enseignants/MRI/contact", json={"email": "autre@univ.test"}).status_code == 200
    assert edit.put("/reference/enseignants/MRI/contact", json={"email": "MARINE.RIGUET@univ.test"}).status_code == 200
    assert "MRI" not in surcharges_reference.valeurs("enseignants", "email")


def test_effacer_reserve_au_role_edit(lecteur) -> None:
    assert lecteur.delete("/reference/enseignants/MRI/contact").status_code == 403
    assert lecteur.delete("/reference/enseignants/MRI/nom").status_code == 403
    assert lecteur.delete("/reference/cours/WR101/intitule").status_code == 403


def test_enseignant_inconnu(edit) -> None:
    assert edit.put("/reference/enseignants/ZZZ/contact", json={"email": "z@univ.test"}).status_code == 404


def test_lecture_seule_ne_complete_rien(lecteur) -> None:
    assert lecteur.put("/reference/enseignants/KBR/contact", json={"email": "k@univ.test"}).status_code == 403
    assert lecteur.put("/reference/enseignants/JSA", json={"nom": "Jean Sans"}).status_code == 403
    assert lecteur.put("/reference/salles/annexe", json={"capacite": 20}).status_code == 403
    assert lecteur.put("/reference/cours/WRX99", json={"intitule": "Atelier"}).status_code == 403


def test_la_saisie_a_le_dernier_mot_au_chargement(etat, tmp_path) -> None:
    """Saisie dans l'appli, puis une autre adresse arrive dans le fichier au
    déploiement : la saisie reste (marquée à l'écran, effaçable)."""
    surcharges_reference.definir("enseignants", "KBR", "email", "saisie@univ.test", par="x")
    assert load_teacher_contacts(etat.config_dir)["KBR"] == "saisie@univ.test"
    (etat.config_dir / "teacher_contacts.yaml").write_text(
        "contacts:\n  MRI: marine.riguet@univ.test\n  KBR: officielle@univ.test\n", encoding="utf-8"
    )
    assert load_teacher_contacts(etat.config_dir)["KBR"] == "saisie@univ.test"


def test_un_fichier_de_surcharges_illisible_ne_casse_pas_la_lecture(etat) -> None:
    surcharges_reference._path().write_text("{pas du json", encoding="utf-8")
    assert load_teacher_contacts(etat.config_dir) == {"MRI": "marine.riguet@univ.test"}
    # Mis de côté, pas effacé.
    assert list(surcharges_reference._path().parent.glob("references.json.corrompu-*"))


# ---------------------------------------------------------------------------
# Nom et code Celcat d'un enseignant
# ---------------------------------------------------------------------------


def test_completer_un_nom_manquant(edit, etat) -> None:
    reponse = edit.put("/reference/enseignants/JSA", json={"nom": "  Jean   Sans-Nom "})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["valeurs"] == {"nom": "Jean Sans-Nom"}
    assert enseignants_declares(etat.config_dir)["JSA"] == "Jean Sans-Nom"
    assert edit.get("/app-state").json()["teacherLabels"]["JSA"] == "Jean Sans-Nom"
    assert "enseignant:JSA:nom" not in _ids(edit)


def test_un_nom_connu_se_corrige_et_s_efface(edit, etat) -> None:
    # APH : nom donné par `enseignants_supplementaires.yaml`.
    reponse = edit.put("/reference/enseignants/APH", json={"nom": "Alexia Petit Halajko"})
    assert reponse.status_code == 200, reponse.text
    assert edit.get("/app-state").json()["teacherLabels"]["APH"] == "Alexia Petit Halajko"
    ligne = surcharges_reference.journal()[0]
    assert ligne["valeur_fichier"] == "Alexia Petit-Halajko"
    surcharge = edit.get("/app-state").json()["surchargesReference"]["enseignants"]["APH"]["nom"]
    assert surcharge["origine"] == "Alexia Petit-Halajko"
    assert edit.delete("/reference/enseignants/APH/nom").status_code == 200
    assert edit.get("/app-state").json()["teacherLabels"]["APH"] == "Alexia Petit-Halajko"
    assert edit.put("/reference/enseignants/JSA", json={"nom": "J"}).status_code == 400


def test_le_code_celcat_d_un_enseignant_reste_admin(edit, admin, etat) -> None:
    assert edit.put("/reference/enseignants/KBR", json={"code_celcat": "38999"}).status_code == 403
    assert "KBR" not in load_celcat_config(etat.config_dir).enseignants
    reponse = admin.put("/reference/enseignants/KBR", json={"code_celcat": " 38999 "})
    assert reponse.status_code == 200, reponse.text
    # Même persistance que l'écran Celcat : la surcouche que lit le worker.
    assert load_celcat_config(etat.config_dir).enseignants["KBR"] == "38999"
    assert mappings.charger()["enseignants"]["KBR"]["ajoute_par"].startswith("test-admin-")
    assert "enseignant:KBR:code_celcat" not in _ids(admin)
    assert any(ligne["champ"] == "code_celcat" and ligne["cle"] == "KBR" for ligne in surcharges_reference.journal())


def test_une_requete_refusee_n_ecrit_rien_a_moitie(edit) -> None:
    """Nom valide + code Celcat interdit (rôle edit) : rien n'est écrit."""
    reponse = edit.put("/reference/enseignants/JSA", json={"nom": "Jean Sans", "code_celcat": "1"})
    assert reponse.status_code == 403
    assert "JSA" not in surcharges_reference.valeurs("enseignants", "nom")


# ---------------------------------------------------------------------------
# Salles
# ---------------------------------------------------------------------------


def test_completer_le_type_et_la_capacite_d_une_salle_ajoutee(edit, etat) -> None:
    reponse = edit.put("/reference/salles/annexe", json={"type": "tp_standard", "capacite": 18})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["valeurs"] == {"capacite": 18, "type": "tp_standard"}
    salle = next(r for r in etat.rooms if r.id == "annexe")
    assert (salle.capacity, salle.room_type) == (18, RoomType.TP_STANDARD)
    # Persisté, et relu tel quel au rechargement (`merge_into`).
    relue = next(r for r in custom_rooms.merge_into([]) if r.id == "annexe")
    assert (relue.capacity, relue.room_type) == (18, RoomType.TP_STANDARD)
    assert "annexe" not in custom_rooms.types_imposes()
    assert "salle:annexe:type" not in _ids(edit)


def test_une_salle_du_batiment_ne_se_complete_pas_ici(edit) -> None:
    reponse = edit.put("/reference/salles/h005", json={"capacite": 99})
    assert reponse.status_code == 409
    assert "rooms.yaml" in reponse.json()["detail"]
    assert edit.put("/reference/salles/annexe", json={"type": "salle-de-bal"}).status_code == 400
    assert edit.put("/reference/salles/annexe", json={"capacite": 0}).status_code == 422
    assert edit.put("/reference/salles/inconnue", json={"capacite": 10}).status_code == 404


def test_le_code_celcat_d_une_salle_reste_admin(edit, admin, etat) -> None:
    assert edit.put("/reference/salles/h018", json={"code_celcat": "Amphi 3 MMI"}).status_code == 403
    reponse = admin.put("/reference/salles/h018", json={"code_celcat": "Amphi 3 MMI"})
    assert reponse.status_code == 200, reponse.text
    assert load_celcat_config(etat.config_dir).salles["h018"] == "Amphi 3 MMI"
    assert "salle:h018:code_celcat" not in _ids(admin)


def test_ajouter_une_salle_garde_le_type_choisi_des_autres(edit) -> None:
    """`add_custom_room` resérialisait toutes les salles depuis `Room` : le
    drapeau « type choisi » d'une salle complétée aurait disparu au
    prochain ajout, et le manque serait revenu."""
    assert edit.put("/reference/salles/annexe", json={"type": "standard"}).status_code == 200
    custom_rooms.add_custom_room(Room(id="autre", label="Autre", capacity=10, room_type=RoomType.STANDARD))
    assert custom_rooms.types_imposes() == {"autre"}


# ---------------------------------------------------------------------------
# Intitulé d'une matière
# ---------------------------------------------------------------------------


def test_completer_un_intitule(edit, etat) -> None:
    reponse = edit.put("/reference/cours/WRX99", json={"intitule": "Atelier  libre"})
    assert reponse.status_code == 200, reponse.text
    assert etat.sessions_by_id["wrx1"].course_name == "Atelier libre"
    assert "cours:WRX99:intitule" not in _ids(edit)
    # Corriger sa propre saisie.
    assert edit.put("/reference/cours/WRX99", json={"intitule": "Atelier ouvert"}).status_code == 200
    assert etat.sessions_by_id["wrx1"].course_name == "Atelier ouvert"
    # Rechargement : la maquette redonne un intitulé vide, la saisie revient.
    etat.sessions_by_id["wrx1"].course_name = ""
    surcharges_reference.appliquer_intitules(etat.sessions)
    assert etat.sessions_by_id["wrx1"].course_name == "Atelier ouvert"


def test_un_intitule_de_la_maquette_se_corrige_et_s_efface(edit, etat) -> None:
    assert edit.put("/reference/cours/WR101", json={"intitule": "Culture numérique (S1)"}).status_code == 200
    assert {s.course_name for s in etat.sessions if s.course_code == "WR101"} == {"Culture numérique (S1)"}
    ligne = surcharges_reference.journal()[0]
    assert ligne["valeur_fichier"] == "Culture numérique"
    surcharge = edit.get("/app-state").json()["surchargesReference"]["cours"]["WR101"]["intitule"]
    assert surcharge["origine"] == "Culture numérique"
    assert edit.delete("/reference/cours/WR101/intitule").status_code == 200
    assert {s.course_name for s in etat.sessions if s.course_code == "WR101"} == {"Culture numérique"}
    assert edit.put("/reference/cours/WRX99", json={"intitule": "wrx99"}).status_code == 400
    assert edit.put("/reference/cours/NOPE", json={"intitule": "Rien"}).status_code == 404


def test_les_surcharges_ne_sortent_pas_sur_un_lien_public(edit, etat) -> None:
    assert edit.put("/reference/enseignants/MRI/contact", json={"email": "autre@univ.test"}).status_code == 200
    assert TestClient(app).get("/app-state?t=MRI").json()["surchargesReference"] == {}


# ---------------------------------------------------------------------------
# API v1
# ---------------------------------------------------------------------------


def test_api_v1_manques_meme_liste_etag_et_304(lecteur) -> None:
    reponse = lecteur.get("/api/v1/manques")
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["manques"] == lecteur.get("/reference/manques").json()["manques"]
    etag = reponse.headers["etag"]
    assert lecteur.get("/api/v1/manques", headers={"If-None-Match": etag}).status_code == 304


def test_api_v1_manques_suit_une_ecriture(edit) -> None:
    premiere = edit.get("/api/v1/manques")
    assert edit.put("/reference/enseignants/KBR/contact", json={"email": "k@univ.test"}).status_code == 200
    seconde = edit.get("/api/v1/manques", headers={"If-None-Match": premiere.headers["etag"]})
    assert seconde.status_code == 200
    assert "enseignant:KBR:email" not in {m["id"] for m in seconde.json()["manques"]}
    assert seconde.json()["total"] == premiere.json()["total"] - 1


def test_api_v1_manques_refuse_un_lien_public(etat, db_isole) -> None:
    assert TestClient(app).get("/api/v1/manques?t=MRI").status_code == 401


def test_usage_au_pluriel() -> None:
    from cal_iut.api.reference import _usage

    assert (_usage(0), _usage(1), _usage(36)) == ("aucune séance placée", "1 séance placée", "36 séances placées")
