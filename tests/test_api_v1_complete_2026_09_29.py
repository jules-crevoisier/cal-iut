"""API v1 complète : tout ce que montrent les écrans, en lecture.

Demande utilisateur (29/09/2026) : « niveau API on est bon ? on peut exposer
toutes les infos et documenter ». Ce que ces tests protègent :

- chaque nouvel endpoint répond sur l'état de test, porte un ETag, répond
  304 à `If-None-Match`, refuse un appel sans compte ET un lien public `?t=` ;
- les droits de l'appli sont repris tels quels : doublons au rôle `edit`,
  Celcat au rôle `admin`, « À traiter » sans doublons pour `read_only` ;
- aucune donnée de compte ne sort (auteur d'une tâche = adresse du compte) ;
- les vues calculées (`api/v1_vues.py`) donnent les MÊMES nombres que le
  frontend (`annuaires.ts`, `todo.ts`) sur les mêmes fixtures ;
- le schéma OpenAPI est limité à v1 et n'est plus public.
"""

from __future__ import annotations

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient
from test_api_v1_revision_2026_09_29 import (  # noqa: F401 — fixtures partagées
    _place,
    _seance,
    client,
    etat,
)

from cal_iut.api import main as api_main
from cal_iut.api import v1, v1_vues
from cal_iut.api.main import app
from cal_iut.models.entities import Room, RoomType, SessionType, TeacherAvailability

NOUVEAUX = [
    "/api/v1/seances/non-placees",
    "/api/v1/a-traiter",
    "/api/v1/controles/doublons",
    "/api/v1/contraintes",
    "/api/v1/enseignants/MRI/contraintes",
    "/api/v1/charges",
    "/api/v1/charges?semaine=10",
    "/api/v1/modifications",
    "/api/v1/taches",
    "/api/v1/calendrier",
    "/api/v1/calendrier?semaine=10",
    "/api/v1/celcat/etat",
    "/api/v1/cours/WR101",
    "/api/v1/openapi.json",
    "/api/v1/docs",
]


@pytest.fixture
def admin(etat, db_isole) -> TestClient:  # noqa: F811
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="admin")
    return c


@pytest.fixture
def lecteur(etat, db_isole) -> TestClient:  # noqa: F811
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="read_only")
    return c


# ---------------------------------------------------------------------------
# Accès : compte obligatoire, lien public refusé, ETag / 304
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chemin", NOUVEAUX)
def test_sans_compte_401(etat, db_isole, chemin) -> None:  # noqa: F811
    assert TestClient(app).get(chemin).status_code == 401


@pytest.mark.parametrize("chemin", NOUVEAUX)
def test_un_lien_public_n_ouvre_pas_les_nouveaux_endpoints(etat, db_isole, chemin) -> None:  # noqa: F811
    separateur = "&" if "?" in chemin else "?"
    reponse = TestClient(app).get(f"{chemin}{separateur}t=MRI")
    assert reponse.status_code == 401, f"{chemin}?t= rend {reponse.status_code}"


@pytest.mark.parametrize("chemin", [c for c in NOUVEAUX if not c.endswith("/docs")])
def test_etag_puis_304(admin, chemin) -> None:
    premiere = admin.get(chemin)
    assert premiere.status_code == 200, premiere.text
    etag = premiere.headers["etag"]
    seconde = admin.get(chemin, headers={"If-None-Match": etag})
    assert seconde.status_code == 304
    assert seconde.content == b""


def test_une_cle_api_lit_les_nouveaux_endpoints(client) -> None:  # noqa: F811
    token = client.post("/auth/mcp-keys").json()["token"]
    anonyme = TestClient(app)
    for chemin in ("/api/v1/a-traiter", "/api/v1/charges", "/api/v1/contraintes", "/api/v1/openapi.json"):
        assert anonyme.get(chemin, headers={"Authorization": f"Bearer {token}"}).status_code == 200, chemin


# ---------------------------------------------------------------------------
# Droits : ceux de l'appli
# ---------------------------------------------------------------------------


def test_doublons_reserves_au_role_edit(lecteur, client) -> None:  # noqa: F811
    assert lecteur.get("/api/v1/controles/doublons").status_code == 403
    assert client.get("/api/v1/controles/doublons").status_code == 200


def test_celcat_reserve_aux_admins_et_sans_secret(client, admin) -> None:  # noqa: F811
    assert client.get("/api/v1/celcat/etat").status_code == 403
    reponse = admin.get("/api/v1/celcat/etat")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert set(corps) >= {"saisie_active", "worker_ok", "compteurs", "file"}
    texte = reponse.text.lower()
    for interdit in ("mot_de_passe", "password", "utilisateur", "/data/", "@"):
        assert interdit not in texte


def test_a_traiter_sans_doublons_pour_un_lecteur(lecteur, client, etat) -> None:  # noqa: F811
    _creer_doublon_enseignant(etat)
    edit = client.get("/api/v1/a-traiter")
    lecture = lecteur.get("/api/v1/a-traiter")
    assert edit.json()["doublons_inclus"] is True
    assert any(p["nature"] == "doublon" for p in edit.json()["points"])
    assert lecture.json()["doublons_inclus"] is False
    assert not any(p["nature"] == "doublon" for p in lecture.json()["points"])
    assert "doublon" not in {n["id"] for n in lecture.json()["natures"]}
    assert edit.headers["etag"] != lecture.headers["etag"], "le rôle fait partie de la clé de cache"


# ---------------------------------------------------------------------------
# Contenu
# ---------------------------------------------------------------------------


def _creer_doublon_enseignant(etat) -> None:  # noqa: F811
    """Une 2e séance de MRI sur le même créneau que `td1` (semaine 10, lundi, 8h)."""
    double = _seance("td2", "but1-td-cd", "MRI")
    etat.sessions = [*etat.sessions, double]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [*etat.timetable, _place(double, 10, 0, 0, "h006")]


def test_seances_non_placees(client, etat) -> None:  # noqa: F811
    orpheline = _seance("np1", "but1-td-ab", "KBR", SessionType.TP)
    etat.sessions = [*etat.sessions, orpheline]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    corps = client.get("/api/v1/seances/non-placees").json()
    assert corps["total"] == 1
    seance = corps["seances"][0]
    assert seance["id"] == "np1" and seance["type"] == "TP" and seance["enseignants"] == ["KBR"]
    assert seance["groupes"] == ["but1-td-ab"] and seance["duree_creneaux"] == 1
    assert client.get("/api/v1/seances/non-placees?parcours=BUT2").json()["total"] == 0
    assert client.get("/api/v1/seances/non-placees?enseignant=KBR").json()["total"] == 1

    points = client.get("/api/v1/a-traiter?nature=non-placee").json()["points"]
    assert [p["titre"] for p in points] == ["WR101 — Culture numérique"]
    assert points[0]["gravite"] == "a_corriger" and points[0]["semaine"] is None


def test_a_traiter_sans_salle_et_filtre_semaine(client) -> None:  # noqa: F811
    corps = client.get("/api/v1/a-traiter").json()
    sans_salle = [p for p in corps["points"] if p["nature"] == "sans-salle"]
    assert [p["seance_id"] for p in sans_salle] == ["autre1"]
    assert sans_salle[0]["semaine"] == 10 and sans_salle[0]["jour_nom"] == "mercredi"
    assert sans_salle[0]["date"] and sans_salle[0]["debut"] == "11:00"
    assert corps["total"] == corps["a_corriger"] + corps["a_revoir"]
    autre_semaine = client.get("/api/v1/a-traiter?semaine=3&nature=sans-salle").json()
    assert autre_semaine["points"] == []
    assert client.get("/api/v1/a-traiter?gravite=a_revoir").json()["a_corriger"] == 0


def test_doublons(client, etat) -> None:  # noqa: F811
    _creer_doublon_enseignant(etat)
    corps = client.get("/api/v1/controles/doublons").json()
    assert corps["total"] == 1
    d = corps["doublons"][0]
    assert d["type"] == "enseignant" and d["semaine"] == 10 and d["debut"] == "08:00"
    assert {s["seance_id"] for s in d["seances"]} == {"td1", "td2"}
    assert client.get("/api/v1/controles/doublons?semaine=3").json()["total"] == 0


def test_contraintes_et_verdict(client, etat) -> None:  # noqa: F811
    # MRI déclare le lundi 8h interdit — `td1` y est placée.
    etat.teacher_availability = [TeacherAvailability(teacher_code="MRI", forbidden_slots=[(0, 0)])]
    corps = client.get("/api/v1/contraintes").json()
    mri = next(e for e in corps["enseignants"] if e["code"] == "MRI")
    assert mri["verdict"] == "ecarts" and mri["nb_ecarts"] == 1
    assert mri["creneaux_interdits"] == [{"jour": 0, "creneau": 0}]
    assert mri["ecarts"][0]["cours_code"] == "WR101" and mri["ecarts"][0]["semaine"] == 10
    assert corps["enseignants"][0]["code"] == "MRI", "les écarts d'abord, comme l'écran"
    assert all(r["statut"] in ("respectee", "echec") for r in corps["regles"])

    seul = client.get("/api/v1/enseignants/MRI/contraintes").json()
    assert seul["verdict"] == "ecarts"
    assert client.get("/api/v1/enseignants/ZZZ/contraintes").status_code == 404

    contrainte = client.get("/api/v1/a-traiter?nature=contrainte").json()["points"]
    assert [p["enseignants"] for p in contrainte] == [["MRI"]]


def test_charges(client) -> None:  # noqa: F811
    corps = client.get("/api/v1/charges?semaine=10").json()
    kbr = next(e for e in corps["enseignants"] if e["code"] == "KBR")
    assert kbr["heures_semaine"] == 1.5 and kbr["heures_semestre"] == 1.5
    assert kbr["heures_par_semaine"] == {"10": 1.5}
    td = next(g for g in corps["groupes"] if g["id"] == "but1-td-ab")
    assert td["heures_semaine"] == 3.0, "son TD et le CM de sa promo"
    assert client.get("/api/v1/charges").json()["enseignants"][0]["heures_semaine"] is None


def test_charges_salles_fusions_et_reservations(client, etat) -> None:  # noqa: F811
    etat.rooms = [
        Room(id="h005", label="H.005", capacity=30, room_type=RoomType.TP_STANDARD),
        Room(id="h018", label="H.018", capacity=150, room_type=RoomType.AMPHI),
    ]
    salles = {s["id"]: s for s in client.get("/api/v1/charges?semaine=10").json()["salles"]}
    assert salles["h005"]["creneaux_occupes"] == 1
    assert salles["h005"]["taux"] == pytest.approx(1 / 30)


def test_modifications_suit_le_diff(client, monkeypatch) -> None:  # noqa: F811
    from cal_iut.api.schemas import DiffEntryResponse, DiffResponse

    entree = DiffEntryResponse(
        session_id="td1", course_code="WR101", solver_week=10, solver_day=1, solver_slot=2,
        current_week=10, current_day=0, current_slot=0, changed=True, locked=True,
    )
    monkeypatch.setattr(api_main, "_calculer_diff", lambda _r: DiffResponse(
        run_id=1, total=3, changed_count=1, entries=[entree],
    ))
    corps = client.get("/api/v1/modifications").json()
    assert corps["nb_modifiees"] == 1 and corps["total_suivies"] == 3
    m = corps["modifications"][0]
    assert m["generation"]["jour_nom"] == "mardi" and m["actuelle"]["debut"] == "08:00"
    assert m["verrouillee"] is True and m["cours_nom"] == "Culture numérique"
    assert client.get("/api/v1/modifications?semaine=4").json()["modifications"] == []


def test_taches_sans_adresse_de_compte(client) -> None:  # noqa: F811
    assert client.post("/taches", json={"titre": "Vérifier H.018", "enseignant_code": "KBR"}).status_code == 200
    reponse = client.get("/api/v1/taches")
    assert [t["titre"] for t in reponse.json()] == ["Vérifier H.018"]
    assert "cree_par" not in reponse.json()[0]
    assert "@" not in reponse.text
    assert client.get("/api/v1/taches?colonne=fait").json() == []
    assert len(client.get("/api/v1/taches?enseignant=KBR").json()) == 1


def test_calendrier(client) -> None:  # noqa: F811
    corps = client.get("/api/v1/calendrier").json()
    assert set(corps) == {
        "jours_sans_cours", "evenements_jour", "evenements_creneau", "jours_sae", "reservations_salles",
        "periodes_institutionnelles",
    }
    assert corps["periodes_institutionnelles"], "le calendrier de l'université est toujours là"
    filtre = client.get("/api/v1/calendrier?semaine=10").json()
    assert all(j["semaine"] == 10 for j in filtre["jours_sans_cours"] + filtre["evenements_jour"])


def test_cours_detail_avec_progression(client) -> None:  # noqa: F811
    corps = client.get("/api/v1/cours/WR101").json()
    assert {e["seance_id"] for e in corps["progression"]} == {"td1", "cm1", "autre1"}
    assert all(e["placee"] for e in corps["progression"])
    assert "progression_definie" in corps["declinaisons"][0]


def test_seance_porte_le_drapeau_evenement(client) -> None:  # noqa: F811
    seances = client.get("/api/v1/seances").json()["seances"]
    assert all(s["evenement"] is False for s in seances)


def test_export_complet_sans_donnee_de_compte(client) -> None:  # noqa: F811
    client.post("/taches", json={"titre": "Tâche d'export"})
    corps = client.get("/api/v1/export").json()
    for cle in ("seances_non_placees", "contraintes", "calendrier", "modifications", "taches"):
        assert cle in corps
    assert corps["taches"][0]["titre"] == "Tâche d'export"
    assert "example.test" not in client.get("/api/v1/export").text, "aucune adresse de compte"


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_schema_openapi_limite_a_v1(client) -> None:  # noqa: F811
    schema = client.get("/api/v1/openapi.json").json()
    assert schema["paths"] and all(p.startswith("/api/v1/") for p in schema["paths"])
    assert "/api/v1/a-traiter" in schema["paths"]
    assert "/api/v1/docs" not in schema["paths"]
    assert schema["components"]["securitySchemes"]["cleApi"]["scheme"] == "bearer"
    assert {t["name"] for t in schema["tags"]} >= {"v1 · contrôles", "v1 · statistiques"}
    exemple = schema["paths"]["/api/v1/charges"]["get"]["responses"]["200"]["content"]["application/json"]
    assert "example" in exemple
    page = client.get("/api/v1/docs")
    assert page.status_code == 200 and "/api/v1/openapi.json" in page.text


def test_le_schema_de_toute_l_appli_n_est_plus_public(etat, db_isole) -> None:  # noqa: F811
    anonyme = TestClient(app)
    for chemin in ("/openapi.json", "/docs", "/redoc"):
        reponse = anonyme.get(chemin)
        assert reponse.status_code == 404 or '"openapi"' not in reponse.text, chemin


# ---------------------------------------------------------------------------
# Limitation de débit
# ---------------------------------------------------------------------------


def test_v1_est_couverte_par_le_limiteur(client, monkeypatch) -> None:  # noqa: F811
    # Compteurs neufs : le limiteur est un singleton en mémoire, et la clé
    # (`compte:<id>`) se répète d'une base isolée à l'autre — les requêtes des
    # tests précédents de la même minute faisaient échouer celui-ci au hasard.
    from cal_iut.api import limiteur

    monkeypatch.setattr(limiteur, "limiteur", limiteur.Limiteur())
    monkeypatch.setattr(v1, "LIMITE_V1", (3, 60.0))
    for _ in range(3):
        assert client.get("/api/v1/version").status_code == 200
    refus = client.get("/api/v1/version")
    assert refus.status_code == 429
    assert int(refus.headers["retry-after"]) > 0


# ---------------------------------------------------------------------------
# Vues calculées : mêmes nombres que le frontend (fixtures de annuaires.test.ts
# et todo.test.ts, recopiées telles quelles)
# ---------------------------------------------------------------------------


def _payload(**surcharges) -> dict:
    base = {
        "groupLabels": {}, "groupKind": {}, "groupCohort": {}, "groupIsFc": {}, "groupParcours": {},
        "weekLabels": ["S1"], "weekDates": ["2026-01-05"],
        "weekRows": [{"monday": "2026-01-05", "label": "S1", "blocked": False, "weekIndex": 0}],
        "weekStatus": [{"week": 0, "status": "current"}], "rows": [], "teachers": [], "teacherLabels": {},
        "teacherEmails": {}, "ruleChecks": [], "rooms": [], "courses": [], "seancesNonPlacees": [],
    }
    base.update(surcharges)
    return base


def _row(id_: str, **surcharges) -> dict:
    return {"id": id_, "w": 0, "d": 0, "s": 0, "c": "XX000", "n": "Cours", "t": "CM", "g": [], "te": [],
            "r": "A100", "ev": False, "dur": 1, "locked": False, "custom": False, **surcharges}


def _prof(code: str, nom: str, **surcharges) -> dict:
    return {"code": code, "name": nom, "violations": [], "hasConstraint": False, **surcharges}


def _salle(id_: str, **surcharges) -> dict:
    return {"id": id_, "label": id_, "capacity": 28, "type": "TD", "equipment": [], "nSessions": 0,
            "placementAuto": True, "combines": [], **surcharges}


def _cours(code: str, nom: str, **surcharges) -> dict:
    return {"code": code, "name": nom, "semestre": "S1", "parcours": "BUT1", "nCM": 0, "nTD": 0, "nTP": 0,
            "nEval": 0, "progressionDefined": False, "teachers": [], "ordonnancement": [], "nPlaced": 0,
            **surcharges}


_DEUX_SEMAINES = {
    "weekLabels": ["S1", "S2"], "weekDates": ["2026-01-05", "2026-01-12"],
    "weekRows": [
        {"monday": "2026-01-05", "label": "S1", "blocked": False, "weekIndex": 0},
        {"monday": "2026-01-12", "label": "S2", "blocked": False, "weekIndex": 1},
    ],
}


def test_heures_occupees_comme_le_frontend() -> None:
    rows = [_row("a"), _row("b"), _row("c", d=1, s=2, dur=2)]
    assert v1_vues.heures_occupees(rows) == 4.5


def test_charges_enseignants_comme_le_frontend() -> None:
    payload = _payload(
        **_DEUX_SEMAINES,
        teacherLabels={"AAA": "Abel Anne", "BBB": "Brun Bea", "CCC": "Col Cid"},
        teachers=[
            _prof("AAA", "Abel Anne", hasConstraint=True),
            _prof("BBB", "Brun Bea", hasConstraint=True, violations=[
                {"course_code": "X", "date": "2026-01-05", "reason": "declared"},
                {"course_code": "X", "date": "2026-01-06", "reason": "sae_supervision"},
            ]),
        ],
        rows=[
            _row("1", te=["AAA"], c="WR101"),
            _row("2", te=["AAA", "BBB"], c="WR102", dur=2),
            _row("3", w=1, te=["AAA"], c="WR101"),
        ],
        seancesNonPlacees=[{"id": "n", "code": "WR103", "nom": "", "type": "TD", "parcours": "", "groupes": [],
                            "profs": ["BBB"]}],
    )
    a, b, c = v1_vues.charges_enseignants(payload, 0)
    assert (a["code"], a["heures_semaine"], a["heures_semestre"], a["nb_matieres"], a["nb_seances"]) == (
        "AAA", 4.5, 6, 2, 3)
    assert (b["code"], b["heures_semaine"], b["heures_semestre"], b["nb_non_placees"]) == ("BBB", 3, 3, 1)
    assert (c["code"], c["heures_semaine"], c["nb_seances"]) == ("CCC", 0, 0)
    assert v1_vues.charges_enseignants(payload, 1)[0]["heures_semaine"] == 1.5
    assert [x["contrainte"] for x in (a, b, c)] == ["respectee", "ecarts", "aucune"]
    assert b["nb_ecarts"] == 1


def test_non_placees_d_un_enseignant_ramenees_au_code() -> None:
    """Écart volontaire documenté : les non placées portent des NOMS."""
    payload = _payload(
        teacherLabels={"MRI": "MARINE RIGUET"},
        seancesNonPlacees=[{"id": "n", "code": "WR1", "nom": "", "type": "TD", "parcours": "", "groupes": [],
                            "profs": ["Marine Riguet"]}],
    )
    assert v1_vues.charges_enseignants(payload, None)[0]["nb_non_placees"] == 1


def test_charges_groupes_comme_le_frontend() -> None:
    payload = _payload(
        groupLabels={"p": "Promo BUT1", "td": "TD AB", "a": "TP A", "b": "TP B"},
        groupKind={"p": "promo", "td": "td", "a": "tp", "b": "tp"},
        groupParcours={"p": "BUT1", "td": "BUT1", "a": "BUT1", "b": "BUT1"},
        groupCohort={"p": ["p"], "td": ["p", "td", "a", "b"], "a": ["p", "td", "a"], "b": ["p", "td", "b"]},
        rows=[_row("cm", s=0, g=["p"]), _row("tpa", s=1, g=["a"]), _row("tpb", s=1, g=["b"])],
    )
    lignes = v1_vues.charges_groupes(payload, 0)
    assert [x["id"] for x in lignes] == ["p", "td", "a", "b"]
    assert [x["heures_semaine"] for x in lignes] == [1.5, 3, 3, 3]


def test_charges_cours_comme_le_frontend() -> None:
    payload = _payload(
        courses=[_cours("WR101", "Anglais", nTD=3, nTP=1, nPlaced=2, teachers=["AAA"])],
        rows=[_row("1", c="WR101", te=["BBB"]), _row("2", w=1, c="WR101")],
        seancesNonPlacees=[{"id": "n", "code": "WR101", "nom": "", "type": "TD", "parcours": "BUT1",
                            "groupes": [], "profs": []}],
    )
    ligne = v1_vues.charges_cours(payload, 0)[0]
    assert (ligne["prevues"], ligne["placees"], ligne["non_placees"]) == (4, 2, 1)
    assert (ligne["heures_semaine"], ligne["heures_placees"]) == (1.5, 3)
    assert ligne["enseignants"] == ["AAA", "BBB"]


def test_charges_salles_comme_le_frontend() -> None:
    payload = _payload(
        rooms=[
            _salle("h007", label="H.007"), _salle("h008", label="H.008"),
            _salle("h007_h008", label="H.007-008", combines=["h007", "h008"]),
        ],
        rows=[_row("1", r="H.007-008", dur=2), _row("2", d=1, r="H.007")],
    )
    par_id = {x["id"]: x for x in v1_vues.charges_salles(payload, 0)}
    assert par_id["h007"]["creneaux_occupes"] == 3
    assert par_id["h008"]["creneaux_occupes"] == 2
    assert par_id["h007_h008"]["creneaux_occupes"] == 3
    assert par_id["h007"]["taux"] == pytest.approx(3 / 30)


def test_a_traiter_comme_le_frontend() -> None:
    assert v1_vues.points_a_traiter(_payload()) == []
    points = v1_vues.points_a_traiter(_payload(
        groupLabels={"G1": "TP A"},
        rows=[_row("no-room", c="MATH1", n="Mathématiques", g=["G1"], te=["KBR"], r="", w=2, d=3)],
        teachers=[_prof("KBR", "Lefèvre Kevin", violations=[{"course_code": "MATH1", "week": 1,
                                                              "reason": "declared"}])],
        seancesNonPlacees=[
            {"id": "np1", "code": "WR106", "nom": "Écriture web", "type": "TD", "parcours": "BUT1",
             "groupes": ["G1"], "profs": ["KBR"]},
            {"id": "np2", "code": "WR106", "nom": "Écriture web", "type": "TD", "parcours": "BUT1",
             "groupes": ["G1"], "profs": ["KBR"]},
        ],
    ))
    assert [p["nature"] for p in points] == ["non-placee", "sans-salle", "contrainte"]
    assert points[0]["nombre"] == 2, "deux séances identiques regroupées (« ×2 »)"
    assert points[1]["titre"] == "MATH1 — Mathématiques" and points[1]["detail"] == "CM · TP A"
    assert points[2]["cle"] == "ct|KBR|1-null-null|MATH1"


def test_journee_trouee_a_partir_de_deux_creneaux_vides() -> None:
    payload = _payload(
        groupKind={"a": "tp", "p": "promo"}, groupLabels={"a": "TP A", "p": "Promo"}, groupParcours={"a": "BUT1"},
        rows=[_row("1", g=["a"], s=0), _row("2", g=["a"], s=3), _row("3", g=["p"], s=0), _row("4", g=["p"], s=5)],
    )
    trouees = [p for p in v1_vues.points_a_traiter(payload) if p["nature"] == "trouee"]
    assert [(p["titre"], p["detail"]) for p in trouees] == [("BUT1 · TP A", "2 créneaux vides entre deux cours")]


def test_tri_par_urgence() -> None:
    points = [
        {"semaine": 0, "jour": 1, "creneau": 0}, {"semaine": 2, "jour": 0, "creneau": 0},
        {"semaine": None, "jour": None, "creneau": None}, {"semaine": 1, "jour": 0, "creneau": 0},
    ]
    statuts = {0: "past", 1: "current", 2: "future"}
    assert [p["semaine"] for p in v1_vues.trier_par_urgence(points, statuts)] == [None, 1, 2, 0]
