"""Anti-aspiration (29/09/2026) — cf. `api/anti_aspiration.py` et
docs/ANTI-ASPIRATION.md.

Les requêtes de test visent surtout `/rien-ici?t=lien` : une page
« publique » (pas de préfixe protégé), qui répond 404 sans rien lire — le
middleware ne regarde que le chemin, l'IP et les en-têtes, et la route
derrière n'a pas d'importance. Seul compte ici : 429, 403, ou passage.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import anti_aspiration as aa
from cal_iut.api import main
from tests.conftest import creer_compte_actif_et_connecter

IP = "203.0.113.7"
AUTRE_IP = "198.51.100.20"
PUBLIC = "/rien-ici?t=lien"


def _client(ip: str = IP, **kw) -> TestClient:
    return TestClient(main.app, client=(ip, 50000), **kw)


@pytest.fixture
def budgets_serres(monkeypatch):
    """Budgets minuscules : 3 requêtes publiques, 10 pour un compte."""
    monkeypatch.setenv("CAL_IUT_AA_PUBLIC", "3/h")
    monkeypatch.setenv("CAL_IUT_AA_PUBLIC_BURST", "3")
    monkeypatch.setenv("CAL_IUT_AA_APPLI", "10/h")
    monkeypatch.setenv("CAL_IUT_AA_APPLI_BURST", "10")
    monkeypatch.setenv("CAL_IUT_AA_API", "6/h")
    monkeypatch.setenv("CAL_IUT_AA_API_BURST", "6")
    monkeypatch.setenv("CAL_IUT_AA_BAN_SEUIL", "1000")


def _statuts(client: TestClient, chemin: str, n: int, **kw) -> list[int]:
    return [client.get(chemin, **kw).status_code for _ in range(n)]


# ── Par défaut : limitation de débit coupée, protections actives ────────────


def test_limitation_de_debit_off_par_defaut(budgets_serres) -> None:
    assert aa.mode() == "off"
    client = _client()
    statuts = _statuts(client, PUBLIC, 20)
    assert 429 not in statuts and 403 not in statuts
    # Aucun seau : la limitation de débit n'a rien touché…
    assert len(aa.seaux) == 0
    # … mais le trafic est compté (écran Trafic).
    assert aa.trafic.instantane(3600)["clients"][0]["requetes"] == 20


def test_valeur_inconnue_retombe_sur_off(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "bloquer-tout")
    assert aa.mode() == "off"
    assert 429 not in _statuts(_client(), PUBLIC, 10)
    assert len(aa.seaux) == 0


def test_interrupteur_de_secours_coupe_tout(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.PROTECTIONS_ENV, "off")
    aa.blocages.ajouter("ip", IP, "préparé", "test")
    client = _client()
    assert 403 not in _statuts(client, PUBLIC, 5)
    for _ in range(40):
        client.get("/export/json?t=promo")
    assert len(aa.trafic) == 0 and len(aa.seaux) == 0
    assert [b.source for b in aa.blocages.lister()] == ["manuel"]


# ── Mode observe : compte, journalise, laisse passer ────────────────────────


def test_observe_laisse_passer_mais_compte_et_journalise(monkeypatch, budgets_serres, caplog) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "observe")
    caplog.set_level(logging.WARNING, logger="cal_iut.anti_aspiration")
    statuts = _statuts(_client(), PUBLIC, 8)
    assert 429 not in statuts and 403 not in statuts
    lignes = aa.trafic.instantane(3600)["clients"]
    assert len(lignes) == 1
    assert lignes[0]["ip"] == IP
    assert lignes[0]["requetes"] == 8
    assert lignes[0]["depassements"] == 5
    assert lignes[0]["categorie"] == "public"
    assert lignes[0]["part_publique"] == 1.0
    # Une ligne par épisode, pas une par requête refusée.
    journal = [r for r in caplog.records if r.name == "cal_iut.anti_aspiration"]
    assert len(journal) == 1
    message = journal[0].getMessage()
    assert "mode=observe" in message and f"ip={IP}" in message
    # Jamais le paramètre `t` (ni rien d'autre du client que son IP).
    assert "t=lien" not in message and "testclient" not in message


def test_observe_ne_bannit_pas(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "observe")
    monkeypatch.setenv("CAL_IUT_AA_BAN_SEUIL", "2")
    assert 403 not in _statuts(_client(), PUBLIC, 10)
    assert aa.blocages.lister() == []


# ── Mode enforce : 429, Retry-After, exemptions, budgets par identité ───────


def test_enforce_refuse_au_dela_du_budget_avec_retry_after(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    client = _client()
    assert _statuts(client, PUBLIC, 3) == [404, 404, 404]
    refus = client.get(PUBLIC)
    assert refus.status_code == 429
    # 3/h : un jeton toutes les 20 minutes.
    assert 1100 <= int(refus.headers["Retry-After"]) <= 1200
    assert "Trop de requêtes" in refus.json()["detail"]
    # Une autre IP a son propre seau.
    assert _client(AUTRE_IP).get(PUBLIC).status_code == 404


def test_enforce_exempte_assets_et_sante(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    client = _client()
    _statuts(client, PUBLIC, 5)  # seau public vide
    for chemin in ("/assets/index-abc123.js", "/health", "/healthz", "/robots.txt"):
        assert 429 not in _statuts(client, chemin, 10), chemin


def test_enforce_ip_exemptee_jamais_limitee(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    monkeypatch.setenv("CAL_IUT_AA_EXEMPTS", "203.0.113.0/24")
    assert 429 not in _statuts(_client(), PUBLIC, 10)
    assert aa.trafic.instantane(3600)["clients"][0]["requetes"] == 10


def test_enforce_compte_connecte_a_un_budget_plus_large(db_isole, monkeypatch, budgets_serres) -> None:
    client = _client()
    creer_compte_actif_et_connecter(client, role="edit")
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    # 10 pour le compte, là où l'IP anonyme n'en a que 3.
    assert _statuts(client, PUBLIC, 10) == [404] * 10
    assert client.get(PUBLIC).status_code == 429
    # Même IP, sans cookie : seau public distinct, intact.
    anonyme = _client()
    assert _statuts(anonyme, PUBLIC, 3) == [404] * 3
    assert anonyme.get(PUBLIC).status_code == 429


def test_enforce_cle_api_a_son_propre_budget(db_isole, monkeypatch, budgets_serres) -> None:
    client = _client()
    creer_compte_actif_et_connecter(client, role="read_only")
    cle = client.post("/auth/mcp-keys").json()["token"]
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    script = _client()
    entetes = {"Authorization": f"Bearer {cle}"}
    assert _statuts(script, PUBLIC, 6, headers=entetes) == [404] * 6
    assert script.get(PUBLIC, headers=entetes).status_code == 429
    # Clé inventée : pas de budget de compte, c'est l'IP anonyme.
    faux = {"Authorization": "Bearer caliut_invente"}
    assert _statuts(_client(AUTRE_IP), PUBLIC, 3, headers=faux) == [404] * 3
    assert _client(AUTRE_IP).get(PUBLIC, headers=faux).status_code == 429


def test_cookie_falsifie_ne_donne_pas_le_budget_d_un_compte(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    client = _client(cookies={"cal_iut_account_session": "1.0.9999999999.signature-inventee"})
    assert _statuts(client, PUBLIC, 3) == [404] * 3
    assert client.get(PUBLIC).status_code == 429


def test_sonde_et_ics_ont_leur_propre_seau(monkeypatch, budgets_serres) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    client = _client()
    _statuts(client, PUBLIC, 5)
    assert aa.classer("/api/v1/version", IP, None, None)[0] == "sonde"
    assert aa.classer("/ics/prof/KBR.ics", IP, None, None)[0] == "ics"
    assert client.get("/auth/status").status_code == 200


# ── Bannissement automatique ────────────────────────────────────────────────


def test_bannissement_automatique_apres_n_refus(monkeypatch, budgets_serres, caplog) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    monkeypatch.setenv("CAL_IUT_AA_BAN_SEUIL", "3")
    monkeypatch.setenv("CAL_IUT_AA_BAN_DUREE", "1h")
    caplog.set_level(logging.WARNING, logger="cal_iut.anti_aspiration")
    client = _client()
    statuts = _statuts(client, PUBLIC, 7)
    assert statuts[:3] == [404, 404, 404]
    assert statuts[3:6] == [429, 429, 429]
    # Banni : 403, même sur une autre catégorie.
    assert statuts[6] == 403
    assert client.get("/auth/status").status_code == 403
    (ban,) = aa.blocages.lister()
    assert ban.automatique and ban.source == "debit" and ban.type == "ip" and ban.valeur == IP
    expire = datetime.fromisoformat(ban.expire_le)
    assert timedelta(minutes=59) < expire - datetime.now(UTC) <= timedelta(hours=1)
    assert any("bannissement" in r.getMessage() for r in caplog.records)
    # Le ban automatique ne vaut qu'en enforce : repassé en observe, il ne
    # s'applique plus (un blocage manuel, si).
    monkeypatch.setenv(aa.MODE_ENV, "observe")
    assert client.get("/auth/status").status_code == 200


def test_un_compte_n_est_jamais_banni(db_isole, monkeypatch, budgets_serres) -> None:
    client = _client()
    creer_compte_actif_et_connecter(client, role="edit")
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    monkeypatch.setenv("CAL_IUT_AA_BAN_SEUIL", "2")
    _statuts(client, PUBLIC, 20)
    assert aa.blocages.lister() == []


# ── Liste de blocage manuelle ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("type_", "valeur", "entetes"),
    [
        ("ip", IP, {}),
        ("cidr", "203.0.113.0/24", {}),
        ("user_agent", "python-requests", {"User-Agent": "Python-Requests/2.31"}),
    ],
)
def test_blocage_manuel_toujours_applique_sauf_interrupteur(monkeypatch, type_, valeur, entetes) -> None:
    aa.blocages.ajouter(type_, valeur, "aspiration", "test")
    client = _client()
    for m in ("off", "observe", "enforce"):
        monkeypatch.setenv(aa.MODE_ENV, m)
        refus = client.get(PUBLIC, headers=entetes)
        assert refus.status_code == 403, m
        assert refus.json() == {"detail": "Accès refusé."}
    monkeypatch.setenv(aa.MODE_ENV, "off")
    monkeypatch.setenv(aa.PROTECTIONS_ENV, "off")
    assert client.get(PUBLIC, headers=entetes).status_code == 404
    monkeypatch.delenv(aa.PROTECTIONS_ENV)
    # Une autre IP / un autre navigateur passe.
    assert _client(AUTRE_IP).get(PUBLIC, headers={"User-Agent": "Mozilla/5.0"}).status_code == 404


def test_blocage_ne_coupe_jamais_le_healthcheck(monkeypatch) -> None:
    monkeypatch.setenv(aa.MODE_ENV, "enforce")
    aa.blocages.ajouter("ip", IP, "test", "test")
    assert _client().get("/health").status_code in (200, 503)


def test_blocages_persistants_et_expiration(tmp_path, monkeypatch) -> None:
    b = aa.blocages.ajouter("ip", IP, "aspiration nocturne", "admin@example.test", aa.lire_duree("24h"))
    donnees = json.loads((tmp_path / "blocages.json").read_text(encoding="utf-8"))
    assert donnees["blocages"][0]["id"] == b.id
    assert donnees["blocages"][0]["auteur"] == "admin@example.test"

    # Relu par une nouvelle liste (redémarrage).
    relue = aa.ListeBlocages()
    assert relue.correspondance(IP, "", inclure_debit=False).id == b.id

    # Écrit à la main, déjà expiré : ignoré, puis purgé à l'écriture suivante.
    passe = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
    donnees["blocages"].append({**donnees["blocages"][0], "id": "expire", "valeur": AUTRE_IP, "expire_le": passe})
    (tmp_path / "blocages.json").write_text(json.dumps(donnees), encoding="utf-8")
    relue = aa.ListeBlocages()
    assert relue.correspondance(AUTRE_IP, "", inclure_debit=True) is None
    assert [x.id for x in relue.lister()] == [b.id]
    relue.ajouter("user_agent", "scrapy", "robot", "test")
    ids = [x["id"] for x in json.loads((tmp_path / "blocages.json").read_text())["blocages"]]
    assert "expire" not in ids and b.id in ids

    assert relue.retirer(b.id) is not None
    assert relue.correspondance(IP, "", inclure_debit=True) is None


def test_meme_cible_remplacee_pas_empilee() -> None:
    aa.blocages.ajouter("ip", IP, "premier", "test", 3600)
    aa.blocages.ajouter("ip", IP, "second", "test", None)
    (b,) = aa.blocages.lister()
    assert b.motif == "second" and b.expire_le is None


@pytest.mark.parametrize(
    ("type_", "valeur"),
    [("ip", "pas-une-ip"), ("cidr", "0.0.0.0/0"), ("cidr", "10.0.0.0/4"), ("user_agent", "ab"), ("autre", "x")],
)
def test_cibles_invalides_refusees(type_, valeur) -> None:
    with pytest.raises(aa.ErreurBlocage):
        aa.valider_cible(type_, valeur)


# ── Routes d'administration ─────────────────────────────────────────────────


def test_routes_admin_refusees_aux_non_admins(db_isole) -> None:
    anonyme = _client()
    assert anonyme.get("/admin/trafic").status_code == 401
    assert anonyme.get("/admin/trafic?t=lien").status_code == 401  # le lien public n'ouvre pas /admin
    editeur = _client()
    creer_compte_actif_et_connecter(editeur, role="edit")
    assert editeur.get("/admin/trafic").status_code == 403
    assert editeur.get("/admin/blocages").status_code == 403
    assert editeur.post("/admin/blocages", json={"type": "ip", "valeur": AUTRE_IP}).status_code == 403
    assert editeur.delete("/admin/blocages/abc").status_code == 403


def test_routes_admin_en_mode_off(db_isole) -> None:
    admin = _client()
    creer_compte_actif_et_connecter(admin, role="admin")
    trafic = admin.get("/admin/trafic").json()
    assert trafic["mode"] == "off"
    # Protections toujours actives : le comptage tourne même sans limitation.
    assert trafic["comptage_actif"] is True
    assert trafic["protections"]["actives"] is True and trafic["protections"]["refus_actif"] is True
    assert trafic["protections"]["refus_seuil"] == 30
    assert {b["categorie"] for b in trafic["budgets"]} == set(aa.CATEGORIES)
    # La liste se prépare même en off.
    cree = admin.post(
        "/admin/blocages", json={"type": "cidr", "valeur": "198.51.100.0/24", "motif": "hébergeur", "duree": "7j"}
    )
    assert cree.status_code == 201, cree.text
    corps = cree.json()
    assert corps["auteur"].startswith("test-admin-") and corps["expire_le"]
    liste = admin.get("/admin/blocages").json()
    assert [b["id"] for b in liste["blocages"]] == [corps["id"]]
    assert admin.get("/admin/trafic").json()["resume"]["ip_bloquees"] == 1
    assert admin.delete(f"/admin/blocages/{corps['id']}").json() == {"ok": True}
    assert admin.delete(f"/admin/blocages/{corps['id']}").status_code == 404
    assert admin.get("/admin/blocages").json()["blocages"] == []


def test_admin_ne_peut_pas_se_bloquer_sans_confirmer(db_isole) -> None:
    admin = _client()
    creer_compte_actif_et_connecter(admin, role="admin")
    r = admin.post("/admin/blocages", json={"type": "ip", "valeur": IP})
    assert r.status_code == 409
    r = admin.post("/admin/blocages", json={"type": "user_agent", "valeur": "testclient"})
    assert r.status_code == 409
    r = admin.post("/admin/blocages", json={"type": "ip", "valeur": IP, "forcer": True})
    assert r.status_code == 201


def test_admin_valeurs_invalides(db_isole) -> None:
    admin = _client()
    creer_compte_actif_et_connecter(admin, role="admin")
    assert admin.post("/admin/blocages", json={"type": "ip", "valeur": "999.1.1.1"}).status_code == 400
    r = admin.post("/admin/blocages", json={"type": "ip", "valeur": AUTRE_IP, "duree": "bientôt"})
    assert r.status_code == 400
    assert "durée" in r.json()["message"]


def test_admin_trafic_en_observe(db_isole, monkeypatch) -> None:
    admin = _client(AUTRE_IP)
    creer_compte_actif_et_connecter(admin, role="admin")
    monkeypatch.setenv(aa.MODE_ENV, "observe")
    visiteur = _client()
    for n in range(4):
        visiteur.get(f"/rien-ici?t=lien{n}", headers={"User-Agent": "curl/8.0"})
    aa.blocages.ajouter("ip", IP, "test", "test")
    corps = admin.get("/admin/trafic?fenetre=15min").json()
    assert corps["mode"] == "observe" and corps["comptage_actif"] is True
    (ligne,) = [c for c in corps["clients"] if c["ip"] == IP]
    assert ligne["requetes_15min"] == 4 and ligne["requetes_24h"] == 4
    assert ligne["user_agent"] == "curl/8.0"
    assert ligne["liens_distincts"] == 4
    assert ligne["blocage_id"]
    # L'admin lui-même apparaît sous son compte.
    (moi,) = [c for c in corps["clients"] if c["ip"] == AUTRE_IP]
    assert moi["compte_email"].startswith("test-admin-")
    assert corps["resume"]["clients"] == 2


# ── IP réelle : jamais celle qu'écrit le client ─────────────────────────────


async def _ip_vue(entetes: list[tuple[bytes, bytes]], pair: str) -> str:
    """Passe une requête dans le middleware de proxy d'uvicorn, réglé comme
    `cal-iut serve` le règle, et rend l'IP que verrait l'application."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    vu = {}

    async def appli(scope, receive, send):
        vu["ip"] = scope["client"][0]

    middleware = ProxyHeadersMiddleware(appli, trusted_hosts=aa.proxys_de_confiance())
    await middleware({"type": "http", "client": (pair, 1234), "headers": entetes}, None, None)
    return vu["ip"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("xff", "pair", "attendu"),
    [
        # nginx (10.0.1.5) écrase l'en-tête avec l'IP réelle : cas nominal.
        (b"203.0.113.7", "10.0.1.5", "203.0.113.7"),
        # Ancien nginx (ajoute au lieu d'écraser) + client qui invente
        # l'en-tête : l'adresse inventée est à gauche, jamais retenue.
        (b"1.2.3.4, 203.0.113.7, 10.0.1.9", "10.0.1.5", "203.0.113.7"),
        # Client qui se dit « interne » : toujours pas.
        (b"10.0.0.1, 203.0.113.7", "10.0.1.5", "203.0.113.7"),
        # Requête qui n'arrive PAS d'un proxy : l'en-tête est ignoré.
        (b"1.2.3.4", "198.51.100.20", "198.51.100.20"),
    ],
)
async def test_ip_reelle_non_falsifiable(xff, pair, attendu) -> None:
    assert await _ip_vue([(b"x-forwarded-for", xff)], pair) == attendu


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_serve_passe_la_liste_des_proxys_a_uvicorn(monkeypatch) -> None:
    import argparse

    import uvicorn

    from cal_iut import cli

    appel = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: appel.update(kw))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")  # plus lue
    cli.cmd_serve(argparse.Namespace(host="127.0.0.1", port=8000, reload=False))
    assert appel["proxy_headers"] is True
    assert appel["forwarded_allow_ips"] == aa.PROXYS_DEFAUT
    assert "*" not in appel["forwarded_allow_ips"]


def test_nginx_ecrase_x_forwarded_for_et_calcule_l_ip_reelle() -> None:
    from pathlib import Path

    gabarit = (Path(__file__).resolve().parents[1] / "frontend" / "nginx.conf.template").read_text(encoding="utf-8")
    lignes = [ligne.strip() for ligne in gabarit.splitlines() if not ligne.strip().startswith("#")]
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in lignes
    assert not any("$proxy_add_x_forwarded_for" in ligne for ligne in lignes)
    assert "real_ip_header X-Forwarded-For;" in lignes
    assert "real_ip_recursive on;" in lignes
    for plage in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert f"set_real_ip_from {plage};" in lignes


# ── Robots ──────────────────────────────────────────────────────────────────


def test_x_robots_tag_toujours_pose() -> None:
    assert aa.mode() == "off"
    r = _client().get("/auth/status")
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_robots_txt_interdit_tout() -> None:
    from pathlib import Path

    robots = (Path(__file__).resolve().parents[1] / "frontend" / "public" / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots and "Disallow: /" in robots


# ── Briques ─────────────────────────────────────────────────────────────────


def test_lecture_des_durees_et_debits() -> None:
    assert aa.lire_duree("30s") == 30
    assert aa.lire_duree("10min") == 600
    assert aa.lire_duree("24h") == 86400
    assert aa.lire_duree("7j") == 7 * 86400
    assert aa.lire_debit("120/min") == (120, 60)
    assert aa.lire_debit("2/s") == (2, 1)
    assert aa.lire_debit("90") == (90, 60)
    for faux in ("", "demain", "3 semaines", "-1h"):
        with pytest.raises(ValueError):
            aa.lire_duree(faux)


def test_variable_illisible_garde_la_valeur_par_defaut(monkeypatch) -> None:
    monkeypatch.setenv("CAL_IUT_AA_PUBLIC", "beaucoup")
    budget = aa.configuration().budgets["public"]
    assert (budget.nombre, budget.periode_s) == (120, 60)


def test_memoire_du_trafic_bornee(monkeypatch) -> None:
    monkeypatch.setattr(aa, "_MAX_CLIENTS", 50)
    t = aa.Trafic()
    for n in range(500):
        t.noter(f"192.0.2.{n % 250}-{n}", categorie="public", chemin=f"/p/{n}", user_agent=f"ua{n}")
    assert len(t) <= 50
    client = aa.Trafic()
    for n in range(200):
        client.noter(IP, categorie="public", chemin=f"/p/{n}", user_agent=f"ua{n}", t=f"t{n}")
    (ligne,) = client.instantane(3600)["clients"]
    assert ligne["requetes"] == 200
    assert len(ligne["chemins"]) <= 5 and ligne["user_agents_distincts"] <= 5
    assert ligne["liens_distincts"] == 200


def test_fenetres_du_trafic() -> None:
    t = aa.Trafic()
    maintenant = 1_800_000_000.0
    t.noter(IP, categorie="public", chemin="/", user_agent="", maintenant=maintenant - 20 * 3600)
    t.noter(IP, categorie="public", chemin="/", user_agent="", maintenant=maintenant - 40 * 60)
    t.noter(IP, categorie="appli", chemin="/", user_agent="", maintenant=maintenant - 60)
    (ligne,) = t.instantane(86400, maintenant=maintenant)["clients"]
    assert (ligne["requetes_15min"], ligne["requetes_1h"], ligne["requetes_24h"]) == (1, 2, 3)
    assert ligne["part_publique"] == round(2 / 3, 3)
    assert t.instantane(900, maintenant=maintenant)["resume"]["requetes"] == 1
    # Au-delà de 24 h, tout est oublié.
    assert t.instantane(86400, maintenant=maintenant + 86400)["clients"] == []


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli(monkeypatch, *argv: str) -> int:
    import sys

    from cal_iut import cli

    monkeypatch.setattr(sys, "argv", ["cal-iut", *argv])
    return cli.main()


def test_cli_bloquer_et_debloquer_en_local(monkeypatch, capsys) -> None:
    assert _cli(monkeypatch, "bloquer", "203.0.113.0/24", "--motif", "hébergeur", "--duree", "7j") == 0
    assert _cli(monkeypatch, "bloquer", "--ua", "python-requests", "--motif", "robot", "--duree", "permanent") == 0
    (plage, ua) = aa.blocages.lister()
    assert (plage.type, plage.valeur, ua.type, ua.expire_le) == ("cidr", "203.0.113.0/24", "user_agent", None)
    assert "hébergeur" in capsys.readouterr().out
    assert _cli(monkeypatch, "trafic") == 0
    sortie = capsys.readouterr().out
    assert plage.id in sortie and "python-requests" in sortie
    assert _cli(monkeypatch, "debloquer", plage.id) == 0
    assert [b.id for b in aa.blocages.lister()] == [ua.id]
    assert _cli(monkeypatch, "debloquer", "inconnu") == 1
    assert _cli(monkeypatch, "bloquer", "pas-une-ip", "--motif", "x") == 1


def test_cli_prod_passe_par_l_api_admin(monkeypatch, capsys) -> None:
    from cal_iut import cli

    appels = []

    def faux(methode, chemin, **kw):
        appels.append((methode, chemin, kw))
        if methode == "POST":
            return 201, {"id": "abc", "type": "ip", "valeur": IP, "motif": "m", "auteur": "a", "expire_le": None}
        if chemin == "/admin/blocages":
            return 200, {"blocages": []}
        if methode == "DELETE":
            return 200, {"ok": True}
        return 200, {
            "mode": "observe", "fenetre": "1h", "comptage_actif": True, "variable": aa.MODE_ENV,
            "resume": {"requetes": 9, "clients": 1, "depassements": 2, "refus_403": 0, "ip_bloquees": 0},
            "clients": [{
                "ip": IP, "requetes_15min": 1, "requetes_1h": 9, "requetes_24h": 9, "part_publique": 1.0,
                "depassements": 2, "user_agent": "curl/8.0", "blocage_id": None,
            }],
        }

    monkeypatch.setattr(cli, "_appel_admin_prod", faux)
    assert _cli(monkeypatch, "bloquer", IP, "--motif", "m", "--duree", "24h", "--prod") == 0
    assert appels[-1] == (
        "POST", "/admin/blocages",
        {"json": {"type": "ip", "valeur": IP, "motif": "m", "duree": "24h", "forcer": False}},
    )
    assert _cli(monkeypatch, "trafic", "--prod") == 0
    assert "curl/8.0" in capsys.readouterr().out
    assert _cli(monkeypatch, "debloquer", "abc", "--prod") == 0
    assert appels[-1][:2] == ("DELETE", "/admin/blocages/abc")
    # Rien n'a été écrit localement.
    assert aa.blocages.lister() == []
