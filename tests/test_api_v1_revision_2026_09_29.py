"""Révision de l'état, caches ETag/304, compression, et API v1 en lecture.

Demande utilisateur (29/09/2026) : « une api entière pour exposer les données
et faire en sorte de limiter les connexions au serveur ». Constat de départ :
`/app-state` renvoyait ≈ 590 Ko de JSON non compressé, recalculé en ≈ 150 ms
à CHAQUE appel, sans aucun moyen pour un client de savoir si quelque chose
avait changé ; les flux .ics répondaient `no-store`, donc jamais de 304.

Ce que ces tests protègent :
- une écriture avance la révision, et une lecture ne l'avance pas ;
- un client qui a déjà la bonne version reçoit un 304 vide ;
- la variante publique (lien perso) et la variante complète (compte) ne se
  servent JAMAIS l'une à la place de l'autre depuis le cache ;
- `/api/v1` est protégé comme le reste, et le contrôle de couverture d'auth
  voit bien ses routes (FastAPI ne les aplatit plus dans `app.routes`).
"""

from __future__ import annotations

import gzip
import threading
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import cache_http, revision
from cal_iut.api.main import _GZipSaufMcp, _routes_effectives, _verifier_couverture_auth, app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")


def _seance(sid: str, groupe: str, prof: str, type_: SessionType = SessionType.TD) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=type_,
        sequence_order=1, group_ids=[groupe], teacher_codes=[prof],
    )


def _place(s: SessionToPlace, week: int, day: int, slot: int, room: str | None = None) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
        room_id=room, room_label=room.upper() if room else None,
    )


@pytest.fixture
def etat():
    """Trois séances : un TD de `but1-td-ab`, un CM de la promo BUT1 (qui
    concerne aussi `but1-td-ab` et ses TP) et une séance d'un autre TD."""
    etat = get_state()
    ancien = {
        cle: getattr(etat, cle)
        for cle in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar", "current_run_id",
            "teacher_availability", "teacher_duos", "corrections", "courses", "config_dir",
            "student_presences", "filter_semestre", "filter_parcours", "semestre_group",
        )
    }
    td = _seance("td1", "but1-td-ab", "MRI")
    cm = _seance("cm1", "but1-promo", "KBR", SessionType.CM)
    autre = _seance("autre1", "but1-td-cd", "JSA")
    etat.sessions = [td, cm, autre]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [_place(td, 10, 0, 0, "h005"), _place(cm, 10, 1, 1, "h018"), _place(autre, 10, 2, 2)]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.student_presences = []
    etat.config_dir = ROOT / "data" / "config"
    etat.filter_semestre = "S1"
    etat.filter_parcours = None
    etat.semestre_group = None
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


@pytest.fixture
def client(etat, db_isole) -> TestClient:
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="edit")
    return c


# ---------------------------------------------------------------------------
# Révision
# ---------------------------------------------------------------------------


def test_la_revision_est_monotone_et_sure_entre_threads() -> None:
    depart = revision.actuelle().numero
    vus: list[int] = []
    verrou = threading.Lock()

    def _ecrire() -> None:
        for _ in range(200):
            numero = revision.incrementer("test").numero
            with verrou:
                vus.append(numero)

    threads = [threading.Thread(target=_ecrire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(vus)) == len(vus) == 1600, "deux écritures ne doivent jamais partager un numéro"
    assert min(vus) > depart
    assert revision.actuelle().numero >= max(vus)


def test_une_sonde_qui_change_avance_la_revision() -> None:
    valeur = {"v": 1}
    revision.enregistrer_sonde("test-sonde", lambda: valeur["v"])
    try:
        premiere = revision.actuelle().numero
        assert revision.actuelle().numero == premiere, "sonde inchangée : révision inchangée"
        valeur["v"] = 2
        assert revision.actuelle().numero > premiere
    finally:
        with revision._verrou:
            revision._sondes.pop("test-sonde", None)
            revision._dernieres_valeurs.pop("test-sonde", None)


def test_la_revision_avance_apres_un_patch_de_placement(client) -> None:
    avant = client.get("/api/v1/version").json()["revision"]
    creneau = client.get("/placements/td1/creneaux-libres").json()["creneaux"][0]
    reponse = client.patch("/placements/td1", json={
        "week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"],
    })
    assert reponse.status_code == 200, reponse.text
    assert client.get("/api/v1/version").json()["revision"] > avant


def test_une_lecture_ou_une_simulation_n_avance_pas_la_revision(client) -> None:
    avant = client.get("/api/v1/version").json()["revision"]
    client.get("/app-state")
    client.get("/timetable")
    # `/validate` est un POST, mais une simulation : aucune écriture. Il part
    # à chaque survol pendant un glisser-déposer — l'avancer ferait tout
    # recharger à tous les onglets ouverts pour rien.
    client.post("/placements/td1/validate", json={"week": 10, "day": 3, "slot": 0})
    assert client.get("/api/v1/version").json()["revision"] == avant


def test_le_filet_middleware_avance_la_revision_sur_une_ecriture_reussie(client) -> None:
    avant = client.get("/api/v1/version").json()["revision"]
    assert client.post("/taches", json={"titre": "Vérifier la salle"}).status_code == 200
    apres = client.get("/api/v1/version").json()["revision"]
    assert apres > avant
    # Une écriture REFUSÉE (422) ne change rien de visible.
    assert client.post("/taches", json={}).status_code == 422
    assert client.get("/api/v1/version").json()["revision"] == apres


# ---------------------------------------------------------------------------
# ETag / 304
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chemin", ["/app-state", "/meta", "/timetable?group_id=but1-td-ab", "/api/v1/version",
                                    "/api/v1/seances?groupe=but1-td-ab", "/api/v1/export"])
def test_etag_puis_304_sans_corps(client, chemin) -> None:
    premiere = client.get(chemin)
    assert premiere.status_code == 200, premiere.text
    etag = premiere.headers["etag"]
    assert etag.startswith('W/"')
    assert premiere.headers["cache-control"] == "private, no-cache"

    seconde = client.get(chemin, headers={"If-None-Match": etag})
    assert seconde.status_code == 304
    assert seconde.content == b""
    assert seconde.headers["etag"] == etag


def test_l_etag_change_apres_une_ecriture(client) -> None:
    etag = client.get("/app-state").headers["etag"]
    client.post("/taches", json={"titre": "Nouvelle tâche"})
    reponse = client.get("/app-state", headers={"If-None-Match": etag})
    assert reponse.status_code == 200
    assert reponse.headers["etag"] != etag


def test_un_etat_remplace_a_la_main_n_est_pas_masque_par_le_cache(client, etat) -> None:
    """Sonde d'identité (`main._empreinte_etat`) : un état réassigné sans
    passer par l'API ne doit pas laisser le cache resservir l'ancien."""
    avant = client.get("/timetable").json()
    etat.timetable = [p for p in etat.timetable if p.session_id != "autre1"]
    apres = client.get("/timetable").json()
    assert len(apres["placements"]) == len(avant["placements"]) - 1


def test_flux_ics_revalide_en_304(client) -> None:
    anonyme = TestClient(app)
    premiere = anonyme.get("/ics/prof/MRI.ics?t=MRI")
    assert premiere.status_code == 200
    assert premiere.headers["cache-control"] == "no-cache"
    assert "BEGIN:VCALENDAR" in premiere.text
    seconde = anonyme.get("/ics/prof/MRI.ics?t=MRI", headers={"If-None-Match": premiere.headers["etag"]})
    assert seconde.status_code == 304
    assert seconde.content == b""

    groupe = anonyme.get("/ics/groupe/but1-td-ab.ics?t=but1-td-ab")
    assert groupe.status_code == 200
    assert anonyme.get(
        "/ics/groupe/but1-td-ab.ics?t=but1-td-ab", headers={"If-None-Match": groupe.headers["etag"]}
    ).status_code == 304


def test_if_none_match_tolere_listes_et_prefixe_faible() -> None:
    class _Req:
        def __init__(self, valeur: str) -> None:
            self.headers = {"if-none-match": valeur}

    etag = cache_http.etag_pour("x")
    assert cache_http.correspond(_Req(etag), etag)
    assert cache_http.correspond(_Req(etag.removeprefix("W/")), etag), "un proxy peut retirer le W/"
    assert cache_http.correspond(_Req(f'"autre", {etag}'), etag)
    assert cache_http.correspond(_Req("*"), etag)
    assert not cache_http.correspond(_Req('W/"autre"'), etag)


# ---------------------------------------------------------------------------
# Variantes publique / complète : jamais l'une à la place de l'autre
# ---------------------------------------------------------------------------


def test_la_variante_publique_ne_fuit_pas_depuis_le_cache_de_la_complete(client) -> None:
    complet = client.get("/app-state")
    assert complet.json()["teacherEmails"], "la config de test porte des adresses — sinon ce test ne prouve rien"

    public = TestClient(app).get("/app-state?t=MRI")
    assert public.status_code == 200
    assert public.json()["teacherEmails"] == {}
    assert public.json()["seancesNonPlacees"] == []
    assert public.headers["etag"] != complet.headers["etag"]

    # Même révision, ETag de la variante COMPLÈTE présenté sur la variante
    # publique : surtout pas un 304 (le navigateur resservirait sa copie
    # complète, adresses comprises, à qui ne doit pas la voir... et
    # inversement).
    croise = TestClient(app).get("/app-state?t=MRI", headers={"If-None-Match": complet.headers["etag"]})
    assert croise.status_code == 200
    assert croise.json()["teacherEmails"] == {}


def test_la_variante_complete_ne_recoit_pas_la_version_expurgee_mise_en_cache(client) -> None:
    public = TestClient(app).get("/app-state?t=MRI")
    assert public.json()["teacherEmails"] == {}
    complet = client.get("/app-state")
    assert complet.json()["teacherEmails"]


def test_une_cle_api_recoit_la_variante_complete(client) -> None:
    """`accounts.get_current_user` ne lit que le cookie : une clé `Bearer`
    recevait jusqu'ici la version expurgée."""
    token = client.post("/auth/mcp-keys").json()["token"]
    reponse = TestClient(app).get("/app-state", headers={"Authorization": f"Bearer {token}"})
    assert reponse.status_code == 200
    assert reponse.json()["teacherEmails"]


def test_v1_reservee_aux_comptes_sauf_la_version(client) -> None:
    """Un lien perso public (`?t=`) ne lit que ce qu'affiche sa page (audit
    du 29/09/2026, P0-2) : l'API v1 est pour les comptes et les clés API. Seul
    le numéro de révision, que les pages publiques sondent, lui est ouvert."""
    complet = client.get("/api/v1/enseignants").json()
    assert any(e["email"] for e in complet)
    anonyme = TestClient(app)
    assert anonyme.get("/api/v1/enseignants?t=MRI").status_code == 401
    assert anonyme.get("/api/v1/version?t=MRI").status_code == 200


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


def test_app_state_part_compresse(client) -> None:
    reponse = client.get("/app-state", headers={"Accept-Encoding": "gzip"})
    assert reponse.headers.get("content-encoding") == "gzip"
    assert "Accept-Encoding" in reponse.headers.get("vary", "")
    assert reponse.json()["rows"], "httpx décompresse : le contenu reste lisible"


def test_une_route_non_cachee_est_compressee_par_le_middleware(client) -> None:
    reponse = client.get("/placements/manquantes", headers={"Accept-Encoding": "gzip"})
    assert reponse.status_code == 200
    if len(reponse.content) >= 1000:
        assert reponse.headers.get("content-encoding") == "gzip"


@pytest.mark.anyio
async def test_mcp_n_est_jamais_compresse() -> None:
    """Le transport MCP peut répondre en flux ; on n'y touche pas."""
    corps = b"x" * 5000

    async def _app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": corps})

    envoye: list[dict] = []

    async def _send(message):
        envoye.append(message)

    async def _receive():
        return {"type": "http.request", "body": b""}

    enveloppe = _GZipSaufMcp(_app)
    scope = {"type": "http", "path": "/mcp", "method": "POST", "headers": [(b"accept-encoding", b"gzip")]}
    await enveloppe(scope, _receive, _send)
    assert envoye[-1]["body"] == corps

    envoye.clear()
    await enveloppe({**scope, "path": "/app-state"}, _receive, _send)
    assert gzip.decompress(envoye[-1]["body"]) == corps


# ---------------------------------------------------------------------------
# API v1 — authentification et contenu
# ---------------------------------------------------------------------------


def test_couverture_auth_complete_et_routes_v1_visibles() -> None:
    assert _verifier_couverture_auth() == []
    chemins = {c for c, _ in _routes_effectives(app.routes) if c}
    assert "/api/v1/version" in chemins, "le contrôle de couverture doit voir les routes d'un routeur inclus"


@pytest.mark.parametrize("chemin", ["/api/v1/version", "/api/v1/seances", "/api/v1/export", "/api/v1/enseignants"])
def test_v1_sans_authentification_renvoie_401(etat, chemin) -> None:
    assert TestClient(app).get(chemin).status_code == 401


def test_v1_accepte_une_cle_api(client) -> None:
    token = client.post("/auth/mcp-keys").json()["token"]
    reponse = TestClient(app).get("/api/v1/seances", headers={"Authorization": f"Bearer {token}"})
    assert reponse.status_code == 200, reponse.text


def test_v1_seances_d_un_groupe_inclut_le_cm_de_sa_promo(client) -> None:
    corps = client.get("/api/v1/seances?groupe=but1-td-ab").json()
    ids = {s["id"] for s in corps["seances"]}
    assert ids == {"td1", "cm1"}
    td = next(s for s in corps["seances"] if s["id"] == "td1")
    assert td["debut"] == "08:00" and td["fin"] == "09:30"
    assert td["jour_nom"] == "lundi"
    assert td["date"] and td["date"][:4] == "2026"
    assert td["salle_id"] == "h005"


def test_v1_seances_filtres_dates_et_pagination(client) -> None:
    toutes = client.get("/api/v1/seances").json()
    assert toutes["total"] == 3
    page = client.get("/api/v1/seances?limite=1&decalage=1").json()
    assert page["total"] == 3 and len(page["seances"]) == 1
    assert page["seances"][0]["id"] == toutes["seances"][1]["id"]

    lundi = next(s for s in toutes["seances"] if s["id"] == "td1")["date"]
    du_lundi = client.get(f"/api/v1/seances?du={lundi}&au={lundi}").json()
    assert [s["id"] for s in du_lundi["seances"]] == ["td1"]


def test_v1_salles_libres_ecarte_les_salles_occupees(client, etat) -> None:
    from cal_iut.models.entities import Room, RoomType

    etat.rooms = [
        Room(id="h005", label="H.005", capacity=30, room_type=RoomType.TP_STANDARD),
        Room(id="h006", label="H.006", capacity=30, room_type=RoomType.TP_STANDARD),
    ]
    corps = client.get("/api/v1/salles/libres?semaine=10&jour=0&creneau=0").json()
    assert [s["id"] for s in corps["libres"]] == ["h006"]
    assert any(o["salle_id"] == "h005" and o["seance_id"] == "td1" for o in corps["occupees"])


def test_v1_semaines_et_creneaux(client) -> None:
    creneaux = client.get("/api/v1/creneaux").json()
    assert len(creneaux["creneaux"]) == 6 and creneaux["creneaux"][3]["debut"] == "14:00"
    semaines = client.get("/api/v1/semaines").json()
    assert semaines[0]["semaine"] == 0
    assert {s["statut"] for s in semaines} <= {"passee", "en_cours", "future"}


def test_v1_ressource_inconnue_404(client) -> None:
    assert client.get("/api/v1/enseignants/ZZZ").status_code == 404
    assert client.get("/api/v1/groupes/inconnu/seances").status_code == 404
