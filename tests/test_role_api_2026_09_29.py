"""Rôle « Accès API » (`api`) — 29/09/2026.

Demande du responsable du planning : « il faudrait un compte, des droits
exprès, pour ceux qui ont besoin d'un token API : qui ne voit pas les
infos, qui peut juste créer un token, et qui ne voit pas les autres
tokens ».

Modèle (cf. `api/accounts.py::ROLE_API`, `api/main.py::_perimetre_role_api`) :
- `api` est HORS de la hiérarchie read_only < edit < admin :
  `require_role("read_only")` le refuse ;
- par cookie (l'appli) : ses propres clés et la doc de v1, rien d'autre ;
- par clé : `GET /api/v1/*` seulement, avec les droits d'un lecteur ; ni
  routes internes, ni `/mcp`, ni écriture ;
- les clés se gèrent par cookie seulement, chacun ne voit que les siennes.

Les deux tests paramétrés parcourent la liste RÉELLE des routes
(`main._routes_effectives`, routeurs inclus) : une route ajoutée demain sans
y penser reste fermée à ce rôle.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cal_iut.api import accounts, main
from cal_iut.api.main import app

MDP = "Motdepasse123"

_ACCEPT_MCP = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INIT_MCP = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}},
}


# ── Outils ──────────────────────────────────────────────────────────────


def _creer_compte(role: str, status: str = "active") -> tuple[int, str]:
    from cal_iut.api.state import get_state
    from cal_iut.db.models import User
    from cal_iut.db.session import get_db, init_db

    etat = get_state()
    init_db(etat.db_path)
    email = f"test-{role}-{uuid.uuid4().hex[:10]}@example.test"
    db = get_db(etat.db_path)
    try:
        user = User(email=email, password_hash=accounts.hash_password(MDP), role=role, status=status)
        db.add(user)
        db.commit()
        return user.id, email
    finally:
        db.close()


def _connecter(email: str) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/auth/login", json={"email": email, "password": MDP})
    assert r.status_code == 200, r.text
    return client


def _compte_connecte(role: str) -> tuple[int, TestClient]:
    user_id, email = _creer_compte(role)
    return user_id, _connecter(email)


def _cle(client: TestClient, nom: str | None = None) -> dict:
    r = client.post("/auth/mcp-keys", json={"nom": nom} if nom else None)
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _anonyme() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _changer_role(user_id: int, role: str) -> None:
    from cal_iut.api.state import get_state
    from cal_iut.db.accounts_repository import AccountRepository
    from cal_iut.db.session import get_db

    db = get_db(get_state().db_path)
    try:
        repo = AccountRepository(db)
        repo.set_role(repo.get_by_id(user_id), role)
    finally:
        db.close()


def _chemin_concret(chemin: str) -> str:
    # Un entier : `DELETE /auth/mcp-keys/{key_id}` attend un id numérique
    # (un « x » rendrait 422 avant tout contrôle de droit).
    return re.sub(r"\{[^}]+\}", "999999", chemin)


def _routes_protegees() -> list[tuple[str, str]]:
    routes = []
    for chemin, route in main._routes_effectives(app.routes):
        methodes = getattr(route, "methods", None) or set()
        if not chemin or not chemin.startswith(main._PROTECTED_PREFIXES):
            continue
        if chemin.startswith(main._PUBLIC_PREFIXES):
            continue
        for methode in sorted(methodes - {"HEAD", "OPTIONS"}):
            routes.append((methode, chemin))
    return routes


ROUTES = _routes_protegees()

# Ce qu'un cookie `api` atteint — tout le reste : 403.
_COOKIE_OUVERT = {
    ("GET", "/auth/mcp-keys"),
    ("POST", "/auth/mcp-keys"),
    ("DELETE", "/auth/mcp-keys/{key_id}"),
    ("GET", "/api/v1/docs"),
    ("GET", "/api/v1/openapi.json"),
}
# Lectures v1 réservées à un rôle supérieur : une clé `api` lit comme un
# lecteur, elle y prend donc 403 comme une clé `read_only`.
_V1_RESERVEES = {"/api/v1/controles/doublons", "/api/v1/celcat/etat"}


@pytest.fixture(scope="module")
def compte_api(tmp_path_factory):
    """Une base isolée et un compte `api` (cookie + clé) pour tout le module
    — les tests paramétrés en font plus de 300 requêtes."""
    from cal_iut.api.state import get_state
    from cal_iut.db import session as db_session
    from cal_iut.db.session import init_db

    etat = get_state()
    ancien = etat.db_path
    db_session._engine = None
    db_session._SessionLocal = None
    chemin = tmp_path_factory.mktemp("role_api") / "role_api.db"
    init_db(chemin)
    etat.db_path = chemin
    from cal_iut.api.limiteur import limiteur

    limiteur.vider()
    user_id, email = _creer_compte("api")
    cookie = _connecter(email)
    token = _cle(cookie, "script de test")["token"]
    yield {"user_id": user_id, "cookie": cookie, "token": token}
    etat.db_path = ancien
    if db_session._engine:
        db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None


# ── Modèle de droits ────────────────────────────────────────────────────


def test_api_est_hors_de_la_hierarchie() -> None:
    assert accounts.ROLE_API == "api"
    assert "api" not in accounts.ROLE_ORDER
    assert accounts.ROLES == ("read_only", "edit", "admin", "api")


@pytest.mark.parametrize("minimum", ["read_only", "edit", "admin"])
def test_require_role_refuse_le_role_api(minimum) -> None:
    class _Etat:
        user = type("U", (), {"status": "active", "role": "api"})()

    requete = type("R", (), {"state": _Etat()})()
    with pytest.raises(HTTPException) as exc:
        accounts.require_role(minimum)(requete)
    assert exc.value.status_code == 403


# ── Cookie `api` : route par route ──────────────────────────────────────


@pytest.mark.parametrize(("methode", "chemin"), ROUTES)
def test_un_cookie_api_n_ouvre_aucune_route_de_donnees(compte_api, methode, chemin) -> None:
    r = compte_api["cookie"].request(methode, _chemin_concret(chemin))
    if (methode, chemin) in _COOKIE_OUVERT:
        assert r.status_code not in (401, 403), f"{methode} {chemin} devrait être ouvert au cookie api"
    else:
        assert r.status_code == 403, f"{methode} {chemin} rend {r.status_code} à un cookie api"


def test_la_liste_couvre_les_routes_de_donnees_principales() -> None:
    """Garde-fou du test précédent : il voit bien les routes qui comptent."""
    chemins = {c for _, c in ROUTES}
    for attendu in ("/app-state", "/meta", "/timetable", "/export/json", "/legacy", "/api/v1/export",
                    "/api/v1/version", "/auth/mcp-keys", "/admin/users"):
        assert attendu in chemins, attendu


def test_cookie_api_voit_son_compte_et_la_doc(compte_api) -> None:
    client = compte_api["cookie"]
    moi = client.get("/auth/me")
    assert moi.status_code == 200 and moi.json()["role"] == "api"
    assert client.get("/auth/status").json() == {"authenticated": True}
    assert client.get("/api/v1/openapi.json").status_code == 200
    assert client.get("/api/v1/docs").status_code == 200
    # Pas les données de v1 par cookie, pas même la révision.
    for chemin in ("/api/v1/version", "/api/v1/export", "/app-state", "/meta"):
        assert client.get(chemin).status_code == 403, chemin


def test_cookie_api_n_ouvre_pas_mcp(compte_api) -> None:
    r = compte_api["cookie"].post("/mcp", json=_INIT_MCP, headers=_ACCEPT_MCP)
    assert r.status_code == 401  # le cookie n'authentifie jamais /mcp


# ── Clé `api` : route par route ─────────────────────────────────────────


@pytest.mark.parametrize(("methode", "chemin"), ROUTES)
def test_une_cle_api_ne_lit_que_v1(compte_api, methode, chemin) -> None:
    r = _anonyme().request(methode, _chemin_concret(chemin), headers=_bearer(compte_api["token"]))
    if methode == "GET" and chemin.startswith("/api/v1/"):
        if chemin in _V1_RESERVEES:
            assert r.status_code == 403, f"{chemin} est réservé à edit/admin"
        else:
            assert r.status_code not in (401, 403), f"GET {chemin} devrait être lisible par une clé api"
    else:
        assert r.status_code == 403, f"{methode} {chemin} rend {r.status_code} à une clé api"


def test_cle_api_refusee_sur_mcp(compte_api) -> None:
    r = _anonyme().post("/mcp", json=_INIT_MCP, headers={**_ACCEPT_MCP, **_bearer(compte_api["token"])})
    assert r.status_code == 403
    assert "Accès API" in r.json()["detail"]


def test_cle_api_lit_v1_comme_un_lecteur(db_isole) -> None:
    """Même contenu qu'une clé `read_only` : variante complète (compte
    actif), sans les doublons réservés à `edit`."""
    _, api = _compte_connecte("api")
    _, lecteur = _compte_connecte("read_only")
    cle_api, cle_lecteur = _cle(api)["token"], _cle(lecteur)["token"]
    for chemin in ("/api/v1/version", "/api/v1/export", "/api/v1/a-traiter", "/api/v1/enseignants"):
        ra = _anonyme().get(chemin, headers=_bearer(cle_api))
        rl = _anonyme().get(chemin, headers=_bearer(cle_lecteur))
        assert ra.status_code == rl.status_code, chemin
        assert ra.status_code != 403, chemin
        if ra.status_code == 200 and chemin != "/api/v1/version":
            assert ra.json() == rl.json(), chemin
    for chemin in _V1_RESERVEES:
        assert _anonyme().get(chemin, headers=_bearer(cle_api)).status_code == 403


def test_cle_api_ne_gere_pas_les_cles(compte_api) -> None:
    entetes = _bearer(compte_api["token"])
    assert _anonyme().get("/auth/mcp-keys", headers=entetes).status_code == 403
    assert _anonyme().post("/auth/mcp-keys", headers=entetes).status_code == 403


# ── Les clés ne gèrent jamais les clés (tous rôles) — faille corrigée ──


@pytest.mark.parametrize("role", ["read_only", "edit", "admin"])
def test_une_cle_ne_peut_ni_lister_ni_creer_ni_revoquer_de_cle(db_isole, role) -> None:
    _, client = _compte_connecte(role)
    creee = _cle(client)
    autre = _cle(client)
    entetes = _bearer(creee["token"])
    assert _anonyme().get("/auth/mcp-keys", headers=entetes).status_code == 403
    assert _anonyme().post("/auth/mcp-keys", headers=entetes).status_code == 403
    assert _anonyme().delete(f"/auth/mcp-keys/{autre['id']}", headers=entetes).status_code == 403
    # Toujours deux clés, et la même clé marche toujours ailleurs.
    assert len(client.get("/auth/mcp-keys").json()["keys"]) == 2
    assert _anonyme().get("/api/v1/version", headers=entetes).status_code == 200


# ── Isolation des clés ──────────────────────────────────────────────────


def test_un_compte_api_ne_voit_ni_ne_revoque_la_cle_d_un_autre(db_isole) -> None:
    _, admin = _compte_connecte("admin")
    cle_admin = _cle(admin, "clé de l'admin")
    _, api = _compte_connecte("api")
    cle_api = _cle(api, "ma clé")

    liste = api.get("/auth/mcp-keys").json()["keys"]
    assert [c["id"] for c in liste] == [cle_api["id"]]
    assert liste[0]["nom"] == "ma clé"
    assert "token" not in liste[0]
    # L'id d'une autre clé : 404, exactement comme un id qui n'existe pas —
    # rien ne dit qu'elle existe.
    autre = api.delete(f"/auth/mcp-keys/{cle_admin['id']}")
    inexistante = api.delete("/auth/mcp-keys/987654")
    assert autre.status_code == inexistante.status_code == 404
    assert autre.json() == inexistante.json()
    # La clé de l'admin marche toujours, et l'admin ne voit pas celle du compte api.
    assert _anonyme().get("/meta", headers=_bearer(cle_admin["token"])).status_code == 200
    assert [c["id"] for c in admin.get("/auth/mcp-keys").json()["keys"]] == [cle_admin["id"]]


@pytest.mark.parametrize("role", ["read_only", "edit", "admin", "api"])
def test_chaque_role_ne_voit_que_ses_cles(db_isole, role) -> None:
    _, voisin = _compte_connecte("edit")
    cle_voisin = _cle(voisin)
    _, client = _compte_connecte(role)
    mienne = _cle(client)
    assert [c["id"] for c in client.get("/auth/mcp-keys").json()["keys"]] == [mienne["id"]]
    assert client.delete(f"/auth/mcp-keys/{cle_voisin['id']}").status_code == 404


def test_pas_de_vue_admin_de_toutes_les_cles() -> None:
    """Aucune route ne liste les clés des autres : seule `/auth/mcp-keys`
    (les siennes) parle de clés."""
    chemins = {c for _, c in ROUTES}
    assert {c for c in chemins if "key" in c or "cle" in c.split("/")[-1]} == {
        "/auth/mcp-keys", "/auth/mcp-keys/{key_id}",
    }


def test_limite_de_cinq_cles_actives(db_isole) -> None:
    _, api = _compte_connecte("api")
    for _ in range(5):
        _cle(api)
    r = api.post("/auth/mcp-keys")
    assert r.status_code == 409
    assert "5 clés API" in r.json()["message"]
    # Révoquer libère une place.
    premiere = api.get("/auth/mcp-keys").json()["keys"][0]
    assert api.delete(f"/auth/mcp-keys/{premiere['id']}").status_code == 200
    assert api.post("/auth/mcp-keys").status_code == 200


def test_nom_de_cle_et_derniere_utilisation(db_isole) -> None:
    _, api = _compte_connecte("api")
    creee = _cle(api, "  Écran   du couloir ")
    assert creee["nom"] == "Écran du couloir"
    assert creee["last_used_at"] is None
    assert _anonyme().get("/api/v1/version", headers=_bearer(creee["token"])).status_code == 200
    (cle,) = api.get("/auth/mcp-keys").json()["keys"]
    assert cle["last_used_at"] is not None
    assert api.post("/auth/mcp-keys", json={"nom": "x" * 61}).status_code == 422


# ── Changement de rôle ──────────────────────────────────────────────────


def test_de_api_vers_un_autre_role_les_cles_prennent_ses_droits(db_isole) -> None:
    user_id, api = _compte_connecte("api")
    token = _cle(api)["token"]
    assert _anonyme().get("/placements/manquantes", headers=_bearer(token)).status_code == 403
    _changer_role(user_id, "read_only")
    assert _anonyme().get("/placements/manquantes", headers=_bearer(token)).status_code == 200
    assert _anonyme().get("/api/v1/controles/doublons", headers=_bearer(token)).status_code == 403
    _changer_role(user_id, "edit")
    assert _anonyme().get("/api/v1/controles/doublons", headers=_bearer(token)).status_code != 403
    # Et l'appli s'ouvre au même cookie, sans reconnexion.
    assert api.get("/meta").status_code == 200


def test_d_un_role_vers_api_les_cles_sont_restreintes_aussitot(db_isole) -> None:
    user_id, client = _compte_connecte("edit")
    token = _cle(client)["token"]
    assert _anonyme().get("/placements/manquantes", headers=_bearer(token)).status_code == 200
    assert _anonyme().post("/mcp", json=_INIT_MCP, headers={**_ACCEPT_MCP, **_bearer(token)}).status_code == 200
    _changer_role(user_id, "api")
    assert _anonyme().get("/placements/manquantes", headers=_bearer(token)).status_code == 403
    assert _anonyme().post("/mcp", json=_INIT_MCP, headers={**_ACCEPT_MCP, **_bearer(token)}).status_code == 403
    assert _anonyme().get("/api/v1/controles/doublons", headers=_bearer(token)).status_code == 403
    assert _anonyme().get("/api/v1/version", headers=_bearer(token)).status_code == 200
    # Le cookie aussi : plus d'écran de données, ses clés toujours visibles.
    assert client.get("/meta").status_code == 403
    assert len(client.get("/auth/mcp-keys").json()["keys"]) == 1


def test_admin_active_et_change_un_compte_en_acces_api(db_isole) -> None:
    _, admin = _compte_connecte("admin")
    attente_id, email = _creer_compte("read_only", status="pending_admin_activation")
    r = admin.patch(f"/admin/users/{attente_id}", json={"role": "api"})
    assert r.status_code == 200, r.text
    assert (r.json()["role"], r.json()["status"]) == ("api", "active")
    client = _connecter(email)
    assert client.get("/auth/me").json()["role"] == "api"
    assert client.get("/app-state").status_code == 403
    # Et retour vers un rôle de la hiérarchie.
    r = admin.patch(f"/admin/users/{attente_id}", json={"role": "read_only"})
    assert r.status_code == 200 and r.json()["role"] == "read_only"
    assert client.get("/meta").status_code == 200
    assert admin.patch(f"/admin/users/{attente_id}", json={"role": "superuser"}).status_code == 422


def test_un_compte_api_n_administre_rien(db_isole) -> None:
    _, api = _compte_connecte("api")
    assert api.get("/admin/users").status_code == 403
    assert api.patch("/admin/users/1", json={"role": "admin"}).status_code == 403


def test_compte_api_desactive_refuse_partout(db_isole) -> None:
    user_id, api = _compte_connecte("api")
    token = _cle(api)["token"]
    from cal_iut.api.state import get_state
    from cal_iut.db.accounts_repository import AccountRepository
    from cal_iut.db.session import get_db

    db = get_db(get_state().db_path)
    try:
        repo = AccountRepository(db)
        repo.set_status(repo.get_by_id(user_id), "disabled")
    finally:
        db.close()
    assert _anonyme().get("/api/v1/version", headers=_bearer(token)).status_code == 403
    assert api.get("/auth/mcp-keys").status_code == 403


# ── Anti-aspiration : une clé `api` valide n'est jamais bannie ──────────


def test_une_cle_api_valide_n_est_pas_bannie_sur_refus(db_isole) -> None:
    from cal_iut.api import anti_aspiration as aa

    _, api = _compte_connecte("api")
    token = _cle(api)["token"]
    script = TestClient(app, client=("89.168.33.54", 50000), raise_server_exceptions=False)
    assert aa.bannissement_refus_actif()
    for _ in range(40):
        assert script.get("/app-state", headers=_bearer(token)).status_code == 403
    assert script.get("/api/v1/version", headers=_bearer(token)).status_code == 200
    assert not [b for b in aa.blocages.lister() if b.valeur == "89.168.33.54"]
    # Le cookie `api` non plus (catégorie « appli », identité = le compte).
    api_ip = TestClient(app, client=("89.168.33.55", 50000), raise_server_exceptions=False,
                        cookies=dict(api.cookies))
    for _ in range(40):
        assert api_ip.get("/meta").status_code == 403
    assert not [b for b in aa.blocages.lister() if b.valeur == "89.168.33.55"]


def test_un_cookie_api_sur_un_lien_perso_n_a_que_la_variante_publique(db_isole) -> None:
    """`?t=` passe le middleware sans compte : la variante (complète ou
    publique) était alors décidée par le seul cookie — celui d'un compte
    `api` actif débloquait les adresses mail des enseignants."""
    from cal_iut.api.main import expurger_payload, variante_lecture

    _, api = _compte_connecte("api")
    requete = type("R", (), {"state": type("S", (), {})(), "cookies": dict(api.cookies)})()
    assert variante_lecture(requete) == "public"
    _, lecteur = _compte_connecte("read_only")
    requete_lecteur = type("R", (), {"state": type("S", (), {})(), "cookies": dict(lecteur.cookies)})()
    assert variante_lecture(requete_lecteur) == "complet"
    avec_api = api.get("/app-state", params={"t": "x"})
    anonyme = _anonyme().get("/app-state", params={"t": "x"})
    assert avec_api.status_code == anonyme.status_code
    if avec_api.status_code == 200:
        assert avec_api.json() == anonyme.json()
        assert avec_api.json() == expurger_payload(avec_api.json())
