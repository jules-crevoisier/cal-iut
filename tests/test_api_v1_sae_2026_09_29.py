"""API v1 — SAE : journées SAE et cours de SAE (29/09/2026).

Demande utilisateur : « les SAE ne sont pas présentes dans l'API » — 712
séances WS* de maquette, dont 17 seulement placées, et aucune trace des 695
autres (l'écran « À placer » les écarte volontairement). Précision : « il y
a des COURS qui sont dans les SAE, mais il y a aussi des JOURNÉES de SAE —
il faut différencier les deux ; les cours de SAE ne peuvent être QUE dans les
journées SAE normalement, à part exception ».

Ce que ces tests protègent :
- `/api/v1/sae/journees` : les journées réservées, telles que la Vue Promo
  les affiche (`saeRows`), avec leur origine et les cours placés ce jour-là ;
- `/api/v1/sae` : chaque cours de SAE de la maquette apparaît UNE fois,
  placé ou non placé ;
- un cours de SAE placé dans une journée SAE n'est pas signalé, hors journée
  il est une anomalie, sauf exception déclarée (`solver_scheduled_sae`) ;
- `sae` / `dans_journee_sae` sur les séances, filtre `/seances?sae=`,
  `/seances/non-placees?inclure_sae=true`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_api_v1_revision_2026_09_29 import client, etat  # noqa: F401 — fixtures partagées

from cal_iut.api.main import app
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom


def _ws(sid: str, code: str, groupe: str, *, parcours: str = "BUT1", semestre: str = "S1") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name=f"SAE {code}", semestre=semestre, parcours=parcours,
        annee=parcours[:4], session_type=SessionType.TD, sequence_order=1, group_ids=[groupe], teacher_codes=["KBR"],
    )


def _poser(s: SessionToPlace, week: int, day: int, slot: int = 0) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes), room_id=None, room_label=None,
    )


def _semaine_du(client, lundi: str) -> int:  # noqa: F811
    return next(s["semaine"] for s in client.get("/api/v1/semaines").json() if s["lundi"] == lundi)


@pytest.fixture
def sae(client, etat):  # noqa: F811
    """WS101 (BUT1, journée SAE officielle le mardi 20/10/2026) : un cours posé
    ce jour-là, un autre posé un lundi ordinaire, un troisième non placé ; et
    WSA501D (BUT3-DEV-FC, placée par la génération) posée hors journée."""
    dans = _ws("ws-dans", "WS101", "but1-td-ab")
    hors = _ws("ws-hors", "WS101", "but1-td-ab")
    absente = _ws("ws-absente", "WS101", "but1-td-cd")
    solveur = _ws("wsa-solveur", "WSA501D", "but3-dev-fc-promo", parcours="BUT3-DEV-FC", semestre="S5")
    etat.sessions = [*etat.sessions, dans, hors, absente, solveur]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    semaine = _semaine_du(client, "2026-10-19")
    etat.timetable = [
        *etat.timetable, _poser(dans, semaine, 1), _poser(hors, semaine, 0), _poser(solveur, semaine, 0, 2),
    ]
    return semaine


CHEMINS_SAE = ["/api/v1/sae", "/api/v1/sae/journees", "/api/v1/sae/periodes", "/api/v1/sae/WS101"]


@pytest.mark.parametrize("chemin", CHEMINS_SAE)
def test_sae_exige_un_compte(etat, db_isole, chemin) -> None:  # noqa: F811
    anonyme = TestClient(app)
    assert anonyme.get(chemin).status_code == 401
    assert anonyme.get(f"{chemin}?t=MRI").status_code == 401


@pytest.mark.parametrize("chemin", CHEMINS_SAE)
def test_sae_etag_304(client, sae, chemin) -> None:  # noqa: F811
    premiere = client.get(chemin)
    assert premiere.status_code == 200, premiere.text
    assert client.get(chemin, headers={"If-None-Match": premiere.headers["etag"]}).status_code == 304


def test_journees_sae(client, sae) -> None:  # noqa: F811
    corps = client.get("/api/v1/sae/journees?parcours=BUT1").json()
    journee = next(j for j in corps["journees"] if j["date"] == "2026-10-20")
    assert journee["semaine"] == sae and journee["jour"] == 1 and journee["journee_entiere"]
    assert journee["creneaux"] == [0, 1, 2, 3, 4, 5]
    ws101 = next(r for r in journee["sae"] if r["code"] == "WS101")
    assert ws101["origine"] == "calendrier_officiel"
    assert [s["id"] for s in journee["seances"]] == ["ws-dans"]
    # `null` : SAE au parcours introuvable, qui concerne tout le monde (même
    # règle que les flux .ics).
    assert {j["parcours"] for j in corps["journees"]} <= {"BUT1", None}
    assert sum(corps["par_parcours"].values()) == corps["total"]

    filtre = client.get("/api/v1/sae/journees?du=2026-10-20&au=2026-10-20").json()
    assert {j["date"] for j in filtre["journees"]} == {"2026-10-20"}
    assert all(j["semaine"] == sae for j in client.get(f"/api/v1/sae/journees?semaine={sae}").json()["journees"])


def test_journee_ajoutee_par_correction_locale(client, sae, etat) -> None:  # noqa: F811
    """Le jeudi 24/09/2026 de WSA501C n'est pas au calendrier officiel : il est
    ajouté par `sae_corrections.yaml` (disponibilités du vacataire), avec son
    motif."""
    wsa = _ws("wsa501c-1", "WSA501C", "but3-creacom-fc-td-gh", parcours="BUT3-CREACOM-FC", semestre="S5")
    etat.sessions = [*etat.sessions, wsa]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    corps = client.get("/api/v1/sae/journees?du=2026-09-24&au=2026-09-24&parcours=BUT3-CREACOM-FC").json()
    ref = next(r for j in corps["journees"] for r in j["sae"] if r["code"] == "WSA501C")
    assert ref["origine"] == "correction_locale" and ref["motif"]


def test_cours_de_sae_dans_et_hors_journee(client, sae) -> None:  # noqa: F811
    corps = client.get("/api/v1/sae").json()
    ws101 = next(e for e in corps["sae"] if e["code"] == "WS101")
    par_id = {s["id"]: s for s in ws101["seances"]}
    assert par_id["ws-dans"]["dans_journee_sae"] is True and par_id["ws-dans"]["anomalie"] is False
    assert par_id["ws-dans"]["journee_sae"] == "BUT1|2026-10-20"
    assert par_id["ws-hors"]["dans_journee_sae"] is False
    assert par_id["ws-hors"]["anomalie"] is True and par_id["ws-hors"]["exception"] is False
    assert [a["id"] for a in corps["anomalies"]] == ["ws-hors"]
    assert (ws101["nb_dans_journee_sae"], ws101["nb_anomalies"]) == (1, 1)
    assert "2026-10-20" in {j["date"] for j in ws101["jours_reserves"]}
    assert ws101["encadrants"], "le référent déclaré au calendrier des SAE"


def test_exception_declaree_non_signalee_mais_marquee(client, sae) -> None:  # noqa: F811
    corps = client.get("/api/v1/sae?parcours=BUT3-DEV-FC").json()
    wsa = next(e for e in corps["sae"] if e["code"] == "WSA501D")
    assert wsa["planifiee_par_solveur"] is True
    seance = wsa["seances"][0]
    assert seance["dans_journee_sae"] is False
    assert seance["exception"] is True and seance["anomalie"] is False
    assert "solver_scheduled_sae" in seance["motif_exception"]
    assert corps["nb_anomalies"] == 0 and corps["nb_exceptions"] == 1


def test_chaque_cours_de_sae_apparait_une_fois(client, sae, etat) -> None:  # noqa: F811
    corps = client.get("/api/v1/sae").json()
    vus = [s["id"] for e in corps["sae"] for s in e["seances"] + e["non_placees"]]
    attendus = {s.id for s in etat.sessions if s.course_code.upper().startswith("WS")}
    assert sorted(vus) == sorted(attendus)
    assert corps["nb_placees"] + corps["nb_non_placees"] == corps["nb_seances_maquette"] == len(attendus)
    absente = next(m for e in corps["sae"] for m in e["non_placees"] if m["id"] == "ws-absente")
    assert absente["statut"] == "hors_solveur" and absente["sae"] is True and absente["raison"]


def test_une_sae_par_code(client, sae) -> None:  # noqa: F811
    corps = client.get("/api/v1/sae/WS101").json()
    assert corps["code"] == "WS101" and [d["parcours"] for d in corps["declinaisons"]] == ["BUT1"]
    assert client.get("/api/v1/sae/WS999").status_code == 404


def test_filtre_semaine_des_sae(client, sae) -> None:  # noqa: F811
    corps = client.get(f"/api/v1/sae?semaine={sae}").json()
    assert {e["code"] for e in corps["sae"]} >= {"WS101"}
    assert all(s["semaine"] == sae for e in corps["sae"] for s in e["seances"])
    assert all(j["semaine"] == sae for e in corps["sae"] for j in e["jours_reserves"])


def test_seances_marquees_sae(client, sae) -> None:  # noqa: F811
    toutes = client.get("/api/v1/seances").json()["seances"]
    td1 = next(s for s in toutes if s["id"] == "td1")
    assert td1["sae"] is False and td1["dans_journee_sae"] is None
    ids_sae = {s["id"] for s in client.get("/api/v1/seances?sae=true").json()["seances"]}
    assert ids_sae == {"ws-dans", "ws-hors", "wsa-solveur"}
    assert not ids_sae & {s["id"] for s in client.get("/api/v1/seances?sae=false").json()["seances"]}
    assert next(s for s in toutes if s["id"] == "ws-dans")["dans_journee_sae"] is True


def test_non_placees_inclure_sae(client, sae) -> None:  # noqa: F811
    defaut = client.get("/api/v1/seances/non-placees").json()
    assert "ws-absente" not in {s["id"] for s in defaut["seances"]}, "comme l'écran « À placer »"
    avec = client.get("/api/v1/seances/non-placees?inclure_sae=true").json()
    seance = next(s for s in avec["seances"] if s["id"] == "ws-absente")
    assert seance["statut"] == "hors_solveur" and seance["sae"] is True


def test_cours_et_export_portent_les_sae(client, sae) -> None:  # noqa: F811
    cours = {c["code"]: c for c in client.get("/api/v1/cours").json()}
    assert cours["WR101"]["sae"] is False
    export = client.get("/api/v1/export").json()
    assert set(export["sae"]) == {"periodes", "journees", "cours"}
    assert {e["code"] for e in export["sae"]["cours"]} >= {"WS101", "WSA501D"}
    assert export["sae"]["journees"] and export["sae"]["periodes"]


def test_periodes_identiques_aux_evenements_ics(client, sae, etat) -> None:  # noqa: F811
    """Même source que les flux .ics : pour un parcours, mêmes UID, mêmes
    débuts et fins que les évènements journée entière SAE du flux."""
    from cal_iut.api.main import _ics_all_day_sae_items

    for parcours in ("BUT1", "BUT3-DEV-FI"):
        ics = sorted((i.key, i.date_start, i.date_end, i.title) for i in _ics_all_day_sae_items(etat, parcours))
        api = client.get(f"/api/v1/sae/periodes?parcours={parcours}").json()
        assert ics, "le flux doit porter des SAE — sinon ce test ne prouve rien"
        assert sorted((p["id"], p["date_debut"], p["date_fin"], p["titre"]) for p in api) == ics

    # Et dans le flux .ics réel d'un groupe BUT1 : chaque période y figure.
    flux = TestClient(app).get("/ics/groupe/but1-td-ab.ics?t=but1-td-ab").text
    for p in client.get("/api/v1/sae/periodes?parcours=BUT1").json():
        assert p["description"] in flux


def test_une_periode_ne_se_coupe_pas_au_week_end(client, sae) -> None:  # noqa: F811
    for p in client.get("/api/v1/sae/periodes").json():
        assert p["jours"][0] == p["date_debut"] and p["jours"][-1] == p["date_fin"]
        assert p["nb_jours"] == len(p["jours"])


def test_une_correction_sae_fait_avancer_la_revision(etat) -> None:  # noqa: F811
    """`sae_corrections.yaml` et `contraintes/09_dates_sae.json` sont des
    sondes de révision : les modifier change l'ETag de `/api/v1/export`."""
    from cal_iut.api import main

    surveilles = {c.name for c in main._fichiers_de_configuration()}
    assert {"sae_corrections.yaml", "09_dates_sae.json", "sae_teacher_phases.yaml"} <= surveilles
