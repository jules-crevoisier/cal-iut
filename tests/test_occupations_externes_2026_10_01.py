"""Occupations HORS MMI lues dans Celcat — demande de Kyllian Bresson du
01/10/2026 : « Lecture de Celcat pour vérifier les disponibilités des salles
et des enseignants ».

Sans Celcat réel : les relevés sont construits sur la FORME des réponses
`udlTimetables.load` / `udlResources.load` (champs de
`tests/fixtures/celcat_udl_load.json`, `lecture.evenement_depuis_rpc`,
`rpc.CHAMPS_CLIENT` pour `deptName`), servis par `occupations.PageSimulee`.

Trois évènements de référence :
- un cours du département TC avec Anthony Froli (AFR), lundi 10h00-12h30 ;
- une réunion de l'administration dans H.018 (« Amphi 3 MMI ») ;
- un de NOS évènements (notes = identifiant de séance) — à ignorer.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import occupations_externes as oe
from cal_iut.api import revision, v1_vues
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import occupations as occ
from cal_iut.ingestion.config_loader import load_groups, load_rooms
from cal_iut.models.entities import SessionType, Teacher
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
CAL = build_default_calendar_2026_2027()

# Dates du relevé simulé (année 2026-2027 : indice 0 du masque = lundi 17/08).
LUNDI_28_09 = date(2026, 9, 28)
LUNDI_REF = date(2026, 8, 17)


def _masque(*jours: date) -> str:
    indices = {(j - timedelta(days=j.weekday()) - LUNDI_REF).days // 7 for j in jours}
    return "".join("Y" if i in indices else "N" for i in range(54))


# ── Relevé simulé (forme réelle des réponses RPC) ───────────────────────

AMPHI_ID = 1604428  # H.018 / Amphi 3 MMI, relevé le 04-05/09/2026
AFR_ID = 603948
DEPTS = [
    {"id": 610029, "name": "T_MMI T29", "unique_name": "T_MMI T29"},
    {"id": 610027, "name": "T_TC T27", "unique_name": "T_TC T27"},
    {"id": 610001, "name": "Direction IUT", "unique_name": "DIR"},
]


def _evenement_tc_afr(*jours: date) -> dict:
    """Le département TC programme AFR le lundi de 10h00 à 12h30.

    Heures telles qu'un navigateur réglé sur Paris les sérialise : le pivot
    du 31/12/1899 porte le fuseau historique (+00:09:21)."""
    return {
        "event_id": 1950001, "day_of_week": 0,
        "start_time": "1899-12-31T09:50:39.000Z", "end_time": "1899-12-31T12:20:39.000Z",
        "evCatName": "[CM]", "event_cat_id": 430, "dept_id": 610027, "deptName": "T_TC T27",
        "rooms": [{"id": 1600101, "name": "A.101"}],
        "modules": [{"id": 1590001, "name": "Marketing digital", "unique_name": "TSTC101"}],
        "staff": [{"id": AFR_ID, "name": "FROLI Anthony", "unique_name": "37948"}],
        "groups": [{"id": 1700001, "name": "BUT TC S1 CM - 2026", "unique_name": "6TC1CM"}],
        "weeks": _masque(*jours), "protected": "N", "global_event": "N", "suspended": "N", "notes": None,
    }


def _reunion_amphi(*jours: date) -> dict:
    """Réservation de H.018 par l'administration : catégorie sans crochets,
    ni matière, ni enseignant, ni groupe. Mardi 14h00-17h00."""
    return {
        "event_id": 1950002, "day_of_week": 1,
        "start_time": "1899-12-31T13:50:39.000Z", "end_time": "1899-12-31T16:50:39.000Z",
        "evCatName": "Réunion", "event_cat_id": 460, "dept_id": 610001,
        "rooms": [{"id": AMPHI_ID, "name": "Amphi 3 MMI"}], "modules": [], "staff": [], "groups": [],
        "event_name": "Conseil de département", "weeks": _masque(*jours),
        "protected": "N", "global_event": "N", "suspended": "N",
    }


def _notre_cm(*jours: date) -> dict:
    """UN DE NOS évènements : écrit par cal-iut (`notes` = session_id)."""
    return {
        "event_id": 1931666, "day_of_week": 0,
        "start_time": "1899-12-31T07:50:39.000Z", "end_time": "1899-12-31T09:20:39.000Z",
        "evCatName": "[CM]", "event_cat_id": 430, "dept_id": 610029, "deptName": "T_MMI T29",
        "rooms": [{"id": AMPHI_ID, "name": "Amphi 3 MMI"}],
        "modules": [{"id": 601106, "name": "WR106 Expression Comm.", "unique_name": "TSBZ2106"}],
        "staff": [{"id": AFR_ID, "name": "FROLI Anthony", "unique_name": "37948"}],
        "groups": [{"id": 1661971, "name": "BUT MMI S1 CM - 2024", "unique_name": "6TSBZ1CM"}],
        "weeks": _masque(*jours), "protected": "N", "global_event": "N", "suspended": "N",
        "notes": "WR106-S1-CM-1",
    }


def _cours_mmi_saisi_main(*jours: date) -> dict:
    """Cours MMI saisi à la main par l'équipe (pas de notes) : le planning
    l'a déjà, la comparaison s'occupe des écarts — pas une occupation externe."""
    brut = _notre_cm(*jours)
    return {**brut, "event_id": 1931700, "notes": None, "day_of_week": 2,
            "groups": [{"id": 1661972, "name": "BUT MMI S1 TD AB - 2024"}]}


def _ferie() -> dict:
    return {"event_id": 1665591, "day_of_week": 6, "start_time": None, "end_time": None,
            "evCatName": "Jour férié", "rooms": [{"id": AMPHI_ID, "name": "Amphi 3 MMI"}], "modules": [],
            "staff": [], "groups": [], "weeks": "Y" * 54, "protected": "Y", "global_event": "Y", "suspended": "N"}


def _donnees_simulees(*jours: date) -> dict:
    return {
        "ressources": {
            "604": [{"id": AMPHI_ID, "name": "Amphi 3 MMI", "unique_name": "1700AR_018"},
                    {"id": 1600101, "name": "A.101", "unique_name": "1700AR_101"}],
            "603": [{"id": AFR_ID, "name": "FROLI Anthony", "unique_name": "37948"},
                    {"id": 603001, "name": "RIGUET Marine", "unique_name": "34044"}],
            "610": DEPTS,
        },
        "evenements": [
            _evenement_tc_afr(*jours), _reunion_amphi(*jours), _notre_cm(*jours),
            _cours_mmi_saisi_main(*jours), _ferie(),
        ],
    }


def _releve(jours: tuple[date, ...], filtre: list[str]) -> occ.ResultatReleve:
    page = occ.PageSimulee(_donnees_simulees(*jours))
    cfg = occ.ConfigOccupations(pause_s=0)
    ressources = occ.ressources_depuis_config(cfg, CONFIG, filtre=filtre)
    return occ.relever(page, cfg, ressources, ctx=occ.ContexteNous(), du=date(2026, 9, 28), au=date(2027, 7, 31),
                       journal=lambda _l: None)


# ── Lecture (sidecar) ────────────────────────────────────────────────────


def test_heure_reelle_retire_le_fuseau_historique_de_paris() -> None:
    assert occ.heure_reelle("1899-12-31T09:50:39.000Z") == "10:00"
    assert occ.heure_reelle("1899-12-31T12:20:39.000Z") == "12:30"
    # Navigateur en UTC (conteneur) : déjà juste.
    assert occ.heure_reelle("1899-12-31T10:00:00.000Z") == "10:00"
    # `lire_reponse` (new Date(1899,11,31,10,0)) et chaîne simple.
    assert occ.heure_reelle("1899-12-31T10:00:00") == "10:00"
    assert occ.heure_reelle("10:15") == "10:15"


def test_le_releve_garde_le_cours_tc_d_afr_et_ignore_nos_evenements() -> None:
    res = _releve((LUNDI_28_09,), ["AFR", "H018"])
    afr = [e for e in res.evenements if e["type"] == "enseignant"]
    assert [(e["code"], e["date"], e["debut"], e["fin"], e["departement"]) for e in afr] == [
        ("AFR", "2026-09-28", "10:00", "12:30", "TC"),
    ]
    assert afr[0]["intitule"] == "Marketing digital" and afr[0]["event_id"] == 1950001
    assert afr[0]["departement_nom"] == "T_TC T27"
    salle = [e for e in res.evenements if e["type"] == "salle"]
    assert [(e["code"], e["date"], e["debut"], e["fin"], e["categorie"]) for e in salle] == [
        ("h018", "2026-09-29", "14:00", "17:00", "Réunion"),
    ]
    assert salle[0]["departement"] == "Direction IUT"
    assert all(e["event_id"] != 1931666 for e in res.evenements), "notre CM (notes = session_id) est ignoré"
    assert all(e["event_id"] != 1931700 for e in res.evenements), "cours MMI saisi à la main : ignoré"
    assert res.ignores.get("écrit par cal-iut (notes)") == 2  # AFR et H.018
    assert res.ignores.get("cours d'un groupe MMI") == 2
    assert res.ignores.get("jour férié") == 1


def test_le_journal_de_synchronisation_suffit_a_reconnaitre_nos_evenements() -> None:
    brut = {**_notre_cm(LUNDI_28_09), "notes": None, "groups": [], "dept_id": None, "deptName": None}
    cfg = occ.ConfigOccupations()
    assert occ.motif_a_nous(brut, occ.ContexteNous(), cfg) is None, "sans indice, il serait externe"
    assert occ.motif_a_nous(brut, occ.ContexteNous(event_ids={1931666}), cfg) == "écrit par cal-iut (journal)"


def test_requetes_groupees_par_lots_jamais_une_par_creneau() -> None:
    page = occ.PageSimulee(_donnees_simulees(LUNDI_28_09))
    cfg = occ.ConfigOccupations(pause_s=0, lot=10)
    ressources = occ.ressources_depuis_config(cfg, CONFIG)
    occ.relever(page, cfg, ressources, ctx=occ.ContexteNous(), du=date(2026, 9, 28), au=date(2027, 7, 31),
                journal=lambda _l: None)
    chargements = [p for m, p in page.appels if m == "udlTimetables.load"]
    salles = sum(1 for r in ressources if r.type == "salle")
    enseignants = sum(1 for r in ressources if r.type == "enseignant")
    assert len(chargements) <= -(-salles // 10) + -(-enseignants // 10) + 2
    assert sum(1 for m, _ in page.appels if m == "udlResources.load") == 3  # salles, personnel, départements


def test_un_releve_filtre_n_ecrase_pas_le_fichier(tmp_path) -> None:
    page = occ.PageSimulee(_donnees_simulees(LUNDI_28_09))
    sorties: list[str] = []
    occ.executer(page, cfg=occ.ConfigOccupations(pause_s=0), filtre=["H018"], ecrire_fichier=True,
                 config_dir=CONFIG, chemin=tmp_path / "f.json", sortie=sorties.append,
                 du=date(2026, 9, 28), au=date(2027, 7, 31))
    assert not (tmp_path / "f.json").exists()
    assert any("ignoré" in s for s in sorties)


def test_cli_en_mode_simule(tmp_path, capsys) -> None:
    """`cal-iut celcat occupations --ressource AFR --simulation …` : ce que
    l'admin lancera dans le sidecar, rejoué sans réseau."""
    from cal_iut.cli import main

    fichier = tmp_path / "releve.json"
    fichier.write_text(json.dumps(_donnees_simulees(LUNDI_28_09)), encoding="utf-8")
    code = main(["celcat", "occupations", "--ressource", "AFR", "--du", "2026-09-28", "--au", "2027-07-31",
                 "--simulation", str(fichier)])
    sortie = capsys.readouterr().out
    assert code == 0
    assert "enseignant AFR" in sortie and "1 occupation(s) hors MMI" in sortie
    assert "lun. 28/09/2026 10:00–12:30 · TC · [CM] · Marketing digital" in sortie
    assert "Amphi 3 MMI" not in sortie, "filtré sur AFR"


def test_cli_ecrit_le_fichier_complet(tmp_path, capsys) -> None:
    from cal_iut.cli import main

    fichier = tmp_path / "releve.json"
    fichier.write_text(json.dumps(_donnees_simulees(LUNDI_28_09)), encoding="utf-8")
    assert main(["celcat", "occupations", "--du", "2026-09-28", "--au", "2027-07-31", "--ecrire-fichier",
                 "--simulation", str(fichier)]) == 0
    capsys.readouterr()
    doc = json.loads(occ.chemin_fichier().read_text(encoding="utf-8"))
    assert doc["periode"] == {"du": "2026-09-28", "au": "2027-07-31"}
    assert {(e["type"], e["code"]) for e in doc["evenements"]} == {("enseignant", "AFR"), ("salle", "h018")}
    assert any(r["code"] == "h018" and r["trouvee"] and r["celcat_id"] == AMPHI_ID for r in doc["ressources"])
    assert doc["releve_le"] and doc["erreur"] is None


def test_un_echec_garde_le_releve_precedent() -> None:
    occ.enregistrer({"releve_le": "2026-10-01T06:00:00+00:00", "evenements": [{"type": "salle", "code": "h018"}]})
    occ.enregistrer_echec("Celcat injoignable : VPN")
    lu = occ.lire()
    assert lu.erreur == "Celcat injoignable : VPN" and len(lu.evenements) == 1


# ── Conversion vers nos créneaux ─────────────────────────────────────────


@pytest.mark.parametrize(("debut", "fin", "attendu"), [
    ("10:00", "12:30", [1, 2]),  # 9h30-11h et 11h-12h30
    ("08:00", "09:30", [0]),
    ("12:30", "14:00", []),  # pause déjeuner : ne mord sur rien
    ("09:00", "09:40", [0, 1]),
    ("13:50", "15:20", [3]),
    ("08:00", "18:30", [0, 1, 2, 3, 4, 5]),
    ("11:00", "11:04", []),  # sous la tolérance
])
def test_creneaux_chevauches(debut, fin, attendu) -> None:
    assert oe.creneaux_chevauches(debut, fin) == attendu


def test_message_exact_enseignant_et_salle() -> None:
    e = {"date": "2026-09-28", "debut": "10:00", "fin": "12:30", "departement": "TC"}
    assert oe.message_enseignant("Anthony Froli", e) == (
        "Enseignant indisponible — Anthony Froli est déjà programmé dans le département TC sur ce créneau "
        "(lundi 28/09, 10h00–12h30, Celcat)."
    )
    r = {"date": "2026-09-29", "debut": "14:00", "fin": "17:00", "departement": "", "intitule": "Conseil"}
    assert oe.message_salle("H.018", r) == (
        "Salle indisponible — H.018 est réservée dans Celcat sur ce créneau (administration, Conseil, "
        "mardi 29/09, 14h00–17h00)."
    )
    assert "(département TC, Marketing" in oe.message_salle("H.018", {**r, "departement": "TC", "intitule": "Marketing"})


# ── Backend : placement, salles, générateur, À traiter ──────────────────

SEMAINE = 9  # lundi 09/11/2026 : semaine future (aujourd'hui = 01/10/2026)
LUNDI = CAL.teaching_mondays[SEMAINE]
MARDI = LUNDI + timedelta(days=1)


def _ecrire_releve(*, age_heures: float = 1.0, evenements: list[dict] | None = None) -> None:
    releve_le = (datetime.now(UTC) - timedelta(hours=age_heures)).isoformat()
    occ.enregistrer({
        "version": 1, "releve_le": releve_le, "base": "URCA_2026",
        "periode": {"du": "2026-09-28", "au": "2027-07-31"},
        "ressources": [
            {"type": "enseignant", "code": "AFR", "libelle": "Anthony Froli", "celcat": "37948",
             "celcat_id": AFR_ID, "trouvee": True},
            {"type": "salle", "code": "h018", "libelle": "H.018 (Amphi MMI)", "celcat": "Amphi 3 MMI",
             "celcat_id": AMPHI_ID, "trouvee": True},
        ],
        "evenements": evenements if evenements is not None else [
            {"type": "enseignant", "code": "AFR", "libelle": "Anthony Froli", "date": LUNDI.isoformat(),
             "debut": "10:00", "fin": "12:30", "departement": "TC", "departement_nom": "T_TC T27",
             "categorie": "[CM]", "intitule": "Marketing digital", "groupes": ["BUT TC S1 CM - 2026"],
             "enseignants": ["FROLI Anthony"], "salles": ["A.101"], "event_id": 1950001},
            {"type": "salle", "code": "h018", "libelle": "H.018 (Amphi MMI)", "date": MARDI.isoformat(),
             "debut": "14:00", "fin": "17:00", "departement": "", "departement_nom": "Direction IUT",
             "categorie": "Réunion", "intitule": "Conseil de département", "groupes": [], "enseignants": [],
             "salles": ["Amphi 3 MMI"], "event_id": 1950002},
        ],
        "ignores": {"écrit par cal-iut (notes)": 1}, "requetes": 6, "erreur": None,
    })
    oe.invalider()


def _seance(sid: str, prof: str, groupe: str, type_: SessionType, prenom: str = "", nom: str = "") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Culture numérique", semestre="S1", parcours="BUT1",
        annee="BUT1", session_type=type_, sequence_order=1, group_ids=[groupe], teacher_codes=[prof],
        teachers=[Teacher(code=prof, prenom=prenom, nom=nom)] if prenom else [],
    )


def _place(s: SessionToPlace, week: int, day: int, slot: int, room: str | None) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes), room_id=room, room_label=None,
    )


@pytest.fixture
def etat():
    etat = get_state()
    cles = ("sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar", "current_run_id",
            "teacher_availability", "teacher_duos", "corrections", "courses", "config_dir", "student_presences",
            "filter_semestre", "filter_parcours", "semestre_group", "room_rules", "room_reservations")
    ancien = {c: getattr(etat, c) for c in cles}
    td = _seance("td-afr", "AFR", "but1-td-ab", SessionType.TD, "Anthony", "Froli")
    cm = _seance("cm-kbr", "KBR", "but1-promo", SessionType.CM)
    etat.sessions = [td, cm]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [_place(td, SEMAINE, 2, 0, "h101"), _place(cm, SEMAINE, 3, 0, "h018")]
    etat.groups = load_groups(CONFIG)
    etat.rooms = load_rooms(CONFIG)
    for p in etat.timetable:
        salle = next(r for r in etat.rooms if r.id == p.room_id)
        p.room_label = salle.label
    etat.room_rules = []
    etat.room_reservations = {}
    etat.calendar = CAL
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.student_presences = []
    etat.config_dir = CONFIG
    etat.filter_semestre = "S1"
    etat.filter_parcours = None
    etat.semestre_group = None
    oe.invalider()
    yield etat
    for c, v in ancien.items():
        setattr(etat, c, v)
    oe.invalider()


@pytest.fixture
def client(etat, db_isole) -> TestClient:
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="edit")
    return c


MESSAGE_AFR = (
    "Enseignant indisponible — Anthony Froli est déjà programmé dans le département TC sur ce créneau "
    f"(lundi {LUNDI.strftime('%d/%m')}, 10h00–12h30, Celcat)."
)


def test_deplacer_sur_une_occupation_externe_passe_avec_un_avertissement(client) -> None:
    """Jules, 02/10/2026 : « que ça se mette en contrainte molle, donc que ça
    affiche si on veut changer et mettre un créneau qui est occupé ». Avant :
    un conflit, refusé sans « Forcer »."""
    _ecrire_releve()
    v = client.post("/placements/td-afr/validate", json={"week": SEMAINE, "day": 0, "slot": 2}).json()
    assert v["valid"] is True and MESSAGE_AFR in v["soft_warnings"]
    assert MESSAGE_AFR not in v["hard_conflicts"] and MESSAGE_AFR not in v["blocking_conflicts"]
    # 8h-9h30 : aucune occupation, rien à signaler.
    v = client.post("/placements/td-afr/validate", json={"week": SEMAINE, "day": 0, "slot": 0}).json()
    assert not any("Celcat" in m for m in v["hard_conflicts"] + v["soft_warnings"])
    r = client.patch("/placements/td-afr", json={"week": SEMAINE, "day": 0, "slot": 1})  # sans forcer
    assert r.status_code == 200, r.text


def test_mode_strict_refuse_sans_forcer(client, monkeypatch) -> None:
    _ecrire_releve()
    monkeypatch.setattr(oe, "config", lambda *_a, **_k: occ.ConfigOccupations(strict=True))
    r = client.patch("/placements/td-afr", json={"week": SEMAINE, "day": 0, "slot": 1, "force": True})
    assert r.status_code == 409
    assert MESSAGE_AFR in r.json()["detail"]["blocking_conflicts"]


def test_salle_reservee_dans_celcat_au_placement(client) -> None:
    _ecrire_releve()
    attendu = (
        "Salle indisponible — H.018 est réservée dans Celcat sur ce créneau (administration, Conseil de "
        f"département, mardi {MARDI.strftime('%d/%m')}, 14h00–17h00)."
    )
    # Choix EXPLICITE de H.018 mardi 14h : un avertissement nommé, le placement passe.
    cible = {"week": SEMAINE, "day": 1, "slot": 3, "room_id": "h018"}
    v = client.post("/placements/cm-kbr/validate", json=cible).json()
    assert v["valid"] is True and attendu in v["soft_warnings"] and attendu not in v["hard_conflicts"]
    assert client.patch("/placements/cm-kbr", json=cible).status_code == 200
    # Changement de salle seul, au même créneau qu'un cours TC : l'avertissement
    # demande confirmation (comme une capacité insuffisante), puis passe.
    _ecrire_releve(evenements=[{
        "type": "salle", "code": "h018", "date": (LUNDI + timedelta(days=3)).isoformat(), "debut": "08:00",
        "fin": "09:30", "departement": "TC", "categorie": "[CM]", "intitule": "Marketing", "event_id": 1,
    }])
    client.patch("/placements/cm-kbr", json={"week": SEMAINE, "day": 3, "slot": 0, "room_id": "h101"})
    r = client.patch("/placements/cm-kbr/salle", json={"room_id": "h018"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert any("Salle indisponible — H.018" in m for m in detail["soft_warnings"])
    assert not any("Celcat" in m for m in detail["hard_conflicts"])
    assert client.patch("/placements/cm-kbr/salle", json={"room_id": "h018", "force": True}).status_code == 200


def test_deplacement_sans_salle_imposee_change_de_salle(client, etat) -> None:
    """La salle actuelle est prise dans Celcat : `find_room_for_slot` en
    choisit une autre au lieu de la proposer."""
    _ecrire_releve()
    r = client.patch("/placements/cm-kbr", json={"week": SEMAINE, "day": 1, "slot": 3})
    assert r.status_code == 200, r.text
    assert r.json()["room_id"] != "h018"


def test_find_room_for_slot_ignore_la_salle_reservee(etat) -> None:
    from cal_iut.solver.rooms import find_room_for_slot

    _ecrire_releve()
    cm = etat.sessions_by_id["cm-kbr"]
    reservees = oe.reservations_effectives(etat)
    assert {SEMAINE * 30 + 1 * 6 + s for s in (3, 4)} <= reservees["h018"]
    assert 5 not in {i % 6 for i in reservees["h018"]}, "17h-18h30 n'est pas touché par 14h-17h"
    salle = find_room_for_slot(cm, SEMAINE, 1, 3, etat.timetable, etat.sessions_by_id, etat.rooms, etat.groups,
                               [], prefer_room_id="h018", reserved=reservees)
    assert salle is not None and salle.id != "h018"


def test_salles_libres_v1_exclut_la_salle_celcat(client) -> None:
    _ecrire_releve()
    corps = client.get(f"/api/v1/salles/libres?semaine={SEMAINE}&jour=1&creneau=3").json()
    assert "h018" not in {s["id"] for s in corps["libres"]}
    occupee = next(o for o in corps["occupees"] if o["salle_id"] == "h018")
    assert occupee["motif"] == "celcat" and "Conseil de département" in occupee["detail"]
    corps = client.get(f"/api/v1/salles/libres?semaine={SEMAINE}&jour=1&creneau=5").json()
    assert "h018" in {s["id"] for s in corps["libres"]}


def test_le_solveur_n_utilise_pas_un_creneau_bloque(etat) -> None:
    """Contrainte DURE : CP-SAT ne laisse à AFR ni 9h30 ni 11h ce lundi-là."""
    from ortools.sat.python import cp_model

    from cal_iut.solver.constraints import add_teacher_availability_constraints

    _ecrire_releve()
    dispos = oe.disponibilites_avec_externes(etat, [])
    regle = next(a for a in dispos if a.teacher_code == "AFR").forbidden_date_slots[0]
    assert (regle.date, regle.slots) == (LUNDI.isoformat(), [1, 2]) and "TC" in regle.note
    seance = etat.sessions_by_id["td-afr"]
    semaines = SEMAINE + 1
    modele = cp_model.CpModel()
    depart = modele.new_int_var(SEMAINE * 30, semaines * 30 - 1, "s")
    add_teacher_availability_constraints(modele, [seance], {seance.id: depart}, dispos, semaines,
                                         calendar=CAL, week_offset=0)
    possibles: set[int] = set()

    class _Collecte(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            possibles.add(self.value(depart))

    solveur = cp_model.CpSolver()
    solveur.parameters.enumerate_all_solutions = True
    solveur.solve(modele, _Collecte())
    lundi = SEMAINE * 30
    assert lundi + 1 not in possibles and lundi + 2 not in possibles
    assert {lundi, lundi + 3} <= possibles


def test_a_traiter_et_parite_v1(client, etat) -> None:
    _ecrire_releve()
    # Une séance DÉJÀ placée sur l'occupation externe d'AFR.
    etat.timetable[0].day, etat.timetable[0].slot = 0, 1
    revision.incrementer("test")
    corps = client.get("/api/v1/a-traiter?nature=occupation-externe").json()
    assert [p["seance_id"] for p in corps["points"]] == ["td-afr"]
    point = corps["points"][0]
    assert point["detail"] == MESSAGE_AFR and point["gravite"] == "a_revoir", "contrainte molle : à revoir, pas à corriger"
    assert point["cle"] == "oe|td-afr|enseignant|AFR" and point["titre"] == "WR101 — Culture numérique"
    nature = next(n for n in corps["natures"] if n["id"] == "occupation-externe")
    assert nature["nombre"] == 1
    payload = client.get("/app-state").json()
    assert payload["occupationsExternes"]["conflits"][0]["message"] == MESSAGE_AFR
    occupations = payload["occupationsExternes"]["occupations"]
    assert {"t": "enseignant", "code": "AFR", "w": SEMAINE, "d": 0, "s": [1, 2]}.items() <= occupations[0].items()


# Même fixture que `frontend/src/utils/todo.occupations.test.ts`.
CONFLIT = {
    "seance_id": "td-afr", "course_code": "WR101", "nom": "Culture numérique", "type": "TD",
    "semaine": 9, "jour": 0, "creneau": 1, "groupes": ["but1-td-ab"], "enseignants": ["AFR"],
    "ressource_type": "enseignant", "ressource": "AFR",
    "message": "Enseignant indisponible — Anthony Froli est déjà programmé dans le département TC sur ce créneau "
               "(lundi 09/11, 10h00–12h30, Celcat).",
}


def test_forme_du_point_comme_le_frontend() -> None:
    payload = {"groupParcours": {"but1-td-ab": "BUT1"}, "occupationsExternes": {"conflits": [CONFLIT]}}
    assert v1_vues.points_a_traiter(payload) == [{
        "nature": "occupation-externe", "gravite": "a_revoir", "cle": "oe|td-afr|enseignant|AFR",
        "titre": "WR101 — Culture numérique", "detail": CONFLIT["message"], "semaine": 9, "jour": 0, "creneau": 1,
        "parcours": ["BUT1"], "enseignants": ["AFR"], "nombre": 1, "seance_id": "td-afr",
    }]


def test_api_v1_occupations_externes_etag(client) -> None:
    _ecrire_releve()
    r = client.get("/api/v1/occupations-externes?ressource=AFR")
    assert r.status_code == 200
    corps = r.json()
    assert corps["total"] == 1 and corps["perime"] is False
    o = corps["occupations"][0]
    assert (o["libelle"], o["semaine"], o["jour"], o["creneaux"], o["departement"]) == (
        "Anthony Froli", SEMAINE, 0, [1, 2], "TC")
    assert client.get("/api/v1/occupations-externes?ressource=AFR",
                      headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_un_nouveau_releve_avance_la_revision(client) -> None:
    avant = revision.actuelle().numero
    _ecrire_releve()
    assert revision.actuelle().numero > avant


def test_fichier_absent_aucune_contrainte(client) -> None:
    assert not occ.chemin_fichier().exists()
    payload = client.get("/app-state").json()["occupationsExternes"]
    assert payload["absent"] is True and payload["occupations"] == [] and payload["conflits"] == []
    r = client.post("/placements/td-afr/validate", json={"week": SEMAINE, "day": 0, "slot": 1}).json()
    assert not any("Celcat" in m for m in r["hard_conflicts"])


def test_fichier_perime_les_contraintes_restent(client) -> None:
    _ecrire_releve(age_heures=9)
    payload = client.get("/app-state").json()["occupationsExternes"]
    assert payload["perime"] is True and payload["absent"] is False
    r = client.post("/placements/td-afr/validate", json={"week": SEMAINE, "day": 0, "slot": 1}).json()
    assert MESSAGE_AFR in r["soft_warnings"], "relevé ancien : l'avertissement reste (contrainte molle depuis le 02/10/2026)"


def test_ecran_admin_et_relire_maintenant(etat, db_isole) -> None:
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="edit")
    assert c.get("/celcat/occupations-externes").status_code == 403
    admin = TestClient(app)
    creer_compte_actif_et_connecter(admin, role="admin")
    _ecrire_releve()
    corps = admin.get("/celcat/occupations-externes").json()
    assert {(r["code"], r["nombre"]) for r in corps["ressources"]} == {("AFR", 1), ("h018", 1)}
    assert corps["demandeEnCours"] is False
    assert admin.post("/celcat/occupations-externes/rafraichir").json()["demande"] is True
    # Activé le 02/10/2026, après les essais sur le vrai Celcat
    # (docs/A-TESTER-SUR-CELCAT.md) : la demande est prise au passage suivant.
    assert corps["lectureActive"] is True and occ.demande_en_cours() and occ.releve_du()
    import dataclasses

    # Coupé (`actif: false`) : la demande reste notée mais le robot ne relit pas.
    assert not occ.releve_du(dataclasses.replace(occ.charger_config(), actif=False))
    assert occ.consommer_demande() and not occ.demande_en_cours()


def test_un_lien_public_ne_recoit_pas_les_occupations() -> None:
    from cal_iut.api.main import _CLES_PRIVEES_PAYLOAD

    assert "occupationsExternes" in _CLES_PRIVEES_PAYLOAD


# ── Sûreté : jamais d'écriture, rien sans relevé ─────────────────────────


def test_la_lecture_n_appelle_que_des_methodes_de_lecture() -> None:
    page = occ.PageSimulee(_donnees_simulees(LUNDI_28_09))
    cfg = occ.ConfigOccupations(pause_s=0)
    occ.relever(page, cfg, occ.ressources_depuis_config(cfg, CONFIG), ctx=occ.ContexteNous(),
                du=date(2026, 9, 28), au=date(2027, 7, 31), journal=lambda _l: None)
    assert {m for m, _ in page.appels} == {"udlResources.load", "udlTimetables.load"}


def test_aucun_module_de_lecture_n_importe_l_ecriture() -> None:
    import ast

    interdits = {"cal_iut.celcat.ecriture", "cal_iut.celcat.modification", "cal_iut.celcat.suppression",
                 "cal_iut.celcat.nuit", "cal_iut.celcat.driver"}
    for fichier in ("src/cal_iut/celcat/occupations.py", "src/cal_iut/celcat/session_lecture.py"):
        arbre = ast.parse((ROOT / fichier).read_text(encoding="utf-8"))
        importes = {n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)}
        noms = {a.name for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert not importes & interdits, fichier
        assert not noms & {"enregistrer_evenement", "supprimer_evenement_rpc", "preparer_evenement"}, fichier
        assert "save" not in (ROOT / fichier).read_text(encoding="utf-8").replace("ensure", ""), fichier
    session = (ROOT / "src/cal_iut/celcat/session_lecture.py").read_text(encoding="utf-8")
    assert "role=nav.ROLE_LECTURE" in session and "ROLE_ECRITURE" not in session


@pytest.mark.parametrize("contenu", [None, []])
def test_sans_releve_ou_releve_vide_rien_ne_change(etat, contenu) -> None:
    """Fichier absent, ou relevé sans occupation : le générateur reçoit
    EXACTEMENT les mêmes disponibilités, l'affectation les mêmes salles
    réservées, et aucun conflit n'apparaît."""
    if contenu is not None:
        _ecrire_releve(evenements=contenu)
    base = list(etat.teacher_availability)
    assert oe.disponibilites_avec_externes(etat, base) is base
    assert oe.reservations_effectives(etat) is etat.room_reservations
    td = etat.sessions_by_id["td-afr"]
    assert oe.conflits_enseignant(etat, td, SEMAINE, 0, 1) == []
    assert oe.conflits_salle(etat, td, "h018", SEMAINE, 1, 3) == []
    assert oe.seances_en_conflit(etat) == []
    assert oe.pour_payload(etat)["occupations"] == []


def test_les_amphis_partages_sont_surveilles_en_priorite() -> None:
    cfg = occ.charger_config(CONFIG)
    assert cfg.salles_prioritaires[:3] == ["h018", "amphi1_tc_gea", "amphi2_gmp_geii"]
    salles = {"h103": "H.103", "h018": "Amphi 3 MMI", "amphi1_tc_gea": "Amphi 1 TC/GEA",
              "amphi2_gmp_geii": "Amphi 2 GMP/GEII"}
    ressources = occ.ressources_a_surveiller(cfg, salles_celcat=salles, enseignants_celcat={})
    assert [r.code for r in ressources][:3] == ["h018", "amphi1_tc_gea", "amphi2_gmp_geii"]
    # Même quand `salles` est une liste qui ne les nomme pas.
    cfg.salles = ["h103"]
    codes = {r.code for r in occ.ressources_a_surveiller(cfg, salles_celcat=salles, enseignants_celcat={})}
    assert codes == {"h103", "h018", "amphi1_tc_gea", "amphi2_gmp_geii"}


# ── Passage du sidecar (scripts/celcat_instantane.py) ────────────────────


def _script_instantane():
    import importlib.util

    spec = importlib.util.spec_from_file_location("celcat_instantane_script", ROOT / "scripts" / "celcat_instantane.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_le_passage_du_sidecar_ne_touche_pas_au_reseau_si_tout_est_frais(monkeypatch, capsys) -> None:
    from cal_iut.celcat import instantane

    script = _script_instantane()
    monkeypatch.setattr(script, "worker_en_pause", lambda: False)
    instantane.enregistrer([], groupes=[])
    _ecrire_releve()
    monkeypatch.setattr("sys.argv", ["celcat_instantane.py"])
    assert script.principal() == 0
    assert "rien à faire" in capsys.readouterr().out


def test_relire_maintenant_declenche_le_passage(monkeypatch, capsys) -> None:
    """Instantané frais, mais « Relire maintenant » demandé : le passage part
    (ici il s'arrête faute de CELCAT_URL — aucun réseau en test) et consomme
    la demande."""
    from cal_iut.celcat import instantane

    script = _script_instantane()
    monkeypatch.setattr(script, "worker_en_pause", lambda: False)
    monkeypatch.setattr(script, "RACINE", ROOT / "inexistant")  # pas de .env lu
    monkeypatch.delenv("CELCAT_URL", raising=False)
    monkeypatch.setattr(script.occupations, "charger_config", lambda *_a: occ.ConfigOccupations())
    instantane.enregistrer([], groupes=[])
    _ecrire_releve()
    occ.demander()
    monkeypatch.setattr("sys.argv", ["celcat_instantane.py"])
    assert script.principal() == 2
    assert not occ.demande_en_cours(), "la demande est consommée"


def test_un_conflit_porte_ses_champs_separes(client, etat) -> None:
    """Retour de Jules du 02/10/2026 sur l'écran des occupations : « c'est
    illisible ». Les conflits n'arrivaient qu'en une phrase ; la vue
    « Occupé ailleurs » les met en tableau (quand, ce qui bloque, occupé par),
    il lui faut les champs un par un. La phrase reste, pour « À traiter »."""
    _ecrire_releve()
    etat.timetable[0].day, etat.timetable[0].slot = 0, 1  # td-afr sur le cours TC d'AFR
    etat.timetable[1].day, etat.timetable[1].slot = 1, 3  # cm-kbr en H.018 pendant la réunion
    revision.incrementer("test")
    conflits = {c["seance_id"]: c for c in client.get("/app-state").json()["occupationsExternes"]["conflits"]}
    afr = conflits["td-afr"]
    assert afr["message"] == MESSAGE_AFR
    assert {
        "ressource_libelle": "Anthony Froli", "date": LUNDI.isoformat(), "debut": "10:00", "fin": "12:30",
        "departement": "TC", "categorie": "[CM]", "intitule": "Marketing digital",
    }.items() <= afr.items()
    salle = conflits["cm-kbr"]
    assert (salle["ressource_type"], salle["ressource"]) == ("salle", "h018")
    assert {"date": MARDI.isoformat(), "debut": "14:00", "fin": "17:00", "departement": ""}.items() <= salle.items()
    assert salle["ressource_libelle"].startswith("H.018")


def test_le_passe_est_ignore(client, etat, monkeypatch) -> None:
    """Jules, 02/10/2026 : « on s'en fiche des choses qui sont passées ». Une
    occupation d'hier ne s'affiche plus, ne prévient plus, ne compte plus."""
    _ecrire_releve()
    etat.timetable[0].day, etat.timetable[0].slot = 0, 1  # td-afr sur le cours TC d'AFR du lundi
    etat.timetable[1].day, etat.timetable[1].slot = 1, 3  # cm-kbr en H.018 pendant la réunion du mardi
    revision.incrementer("test")
    avant = client.get("/app-state").json()["occupationsExternes"]
    assert {c["seance_id"] for c in avant["conflits"]} == {"td-afr", "cm-kbr"}

    monkeypatch.setattr(oe, "_aujourdhui", lambda: MARDI)  # le lundi est passé
    oe.invalider()
    revision.incrementer("test")
    apres = client.get("/app-state").json()["occupationsExternes"]
    assert {o["date"] for o in apres["occupations"]} == {MARDI.isoformat()}
    assert {c["seance_id"] for c in apres["conflits"]} == {"cm-kbr"}
    v = client.post("/placements/td-afr/validate", json={"week": SEMAINE, "day": 0, "slot": 2}).json()
    assert not any("Celcat" in m for m in v["soft_warnings"] + v["hard_conflicts"])
    assert client.get("/api/v1/occupations-externes").json()["total"] == 1


def test_le_generateur_et_le_lissage_evitent_toujours_ces_creneaux(etat) -> None:
    """Molle pour une personne qui place à la main ; les outils automatiques,
    eux, continuent d'éviter un enseignant ou une salle pris ailleurs."""
    _ecrire_releve()
    dispos = {a.teacher_code: a for a in oe.disponibilites_avec_externes(etat, [])}
    assert [r.date for r in dispos["AFR"].forbidden_date_slots] == [LUNDI.isoformat()]
    assert {SEMAINE * 30 + 1 * 6 + s for s in (3, 4)} <= oe.reservations_effectives(etat)["h018"]
