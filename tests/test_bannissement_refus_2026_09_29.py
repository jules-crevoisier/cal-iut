"""Bannissement sur refus d'accès répétés — ACTIF PAR DÉFAUT (décision
utilisateur du 29/09/2026, cf. `api/anti_aspiration.py`).

Cas réel des journaux de production du 29/09 : 79.137.33.236 (un VPS)
bouclait `GET /export/json?t=promo` (401) → `/app-state?t=promo` (200) →
`/meta?t=promo` (200), jusqu'à deux boucles par seconde (≈ 19 401 en 90 s).
Dans les mêmes journaux, des clients LÉGITIMES qu'il ne faut jamais gêner :
une appli qui sonde `/api/v1/version` (304), Google Agenda et des box sur
`/ics/prof/XXX.ics?t=XXX`, un navigateur sur un lien personnel, une lecture
ponctuelle de `/app-state?t=<groupe>`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import anti_aspiration as aa
from cal_iut.api import main
from tests.conftest import creer_compte_actif_et_connecter

ASPIRATEUR = "79.137.33.236"
APPLI_API = "89.168.33.53"
GOOGLE_AGENDA = "66.249.92.131"
NAVIGATEUR = "77.133.250.4"
LECTEUR = "149.202.61.176"
ADMIN = "198.51.100.10"


def _client(ip: str, **kw) -> TestClient:
    return TestClient(main.app, client=(ip, 50000), raise_server_exceptions=False, **kw)


def _boucle_aspirateur(client: TestClient) -> tuple[int, int, int]:
    """Une boucle du journal : rend les trois statuts."""
    return (
        client.get("/export/json?t=promo").status_code,
        client.get("/app-state?t=promo").status_code,
        client.get("/meta?t=promo").status_code,
    )


def _bannis() -> list[aa.Blocage]:
    return [b for b in aa.blocages.lister() if b.source == "refus"]


def test_protections_actives_sans_aucune_variable() -> None:
    assert aa.mode() == "off"  # la limitation de débit, elle, reste coupée
    assert aa.protections_actives() and aa.bannissement_refus_actif()


def test_scenario_du_journal_banni_avant_le_31e_refus() -> None:
    client = _client(ASPIRATEUR)
    refus_401 = 0
    for _ in range(40):
        export, app_state, meta = _boucle_aspirateur(client)
        if export == 401:
            refus_401 += 1
            if refus_401 < 30:
                assert app_state not in (401, 403) and meta not in (401, 403)
            else:
                # Le 30e refus vient de bannir : la suite de la même boucle
                # est déjà refusée.
                assert (app_state, meta) == (403, 403)
        else:
            assert export == 403
            break
    assert refus_401 == 30
    # Banni : 403 sobre sur tout, y compris ce que le lien public ouvre.
    for chemin in ("/app-state?t=promo", "/meta?t=promo", "/ics/prof/KBR.ics?t=KBR", "/"):
        r = client.get(chemin)
        assert r.status_code == 403, chemin
        assert r.json() == {"detail": "Accès refusé."}
    (ban,) = _bannis()
    assert (ban.type, ban.valeur, ban.auteur, ban.automatique) == ("ip", ASPIRATEUR, "automatique", True)
    assert ban.motif == "bannissement automatique : 30 refus 401/403 en 10 min"
    reste = datetime.fromisoformat(ban.expire_le) - datetime.now(UTC)
    assert timedelta(hours=23, minutes=59) < reste <= timedelta(hours=24)
    # Persistant : relu après redémarrage.
    assert aa.ListeBlocages().correspondance(ASPIRATEUR, "", inclure_debit=False) is not None
    # Les autres ne sont pas touchés.
    assert _client(LECTEUR).get("/app-state?t=but1-td-a").status_code not in (401, 403)


def test_29_refus_ne_bannissent_pas() -> None:
    client = _client(ASPIRATEUR)
    for _ in range(29):
        assert client.get("/export/json?t=promo").status_code == 401
    assert _bannis() == []
    assert client.get("/app-state?t=promo").status_code != 403
    # Le 30e, si.
    assert client.get("/export/json?t=promo").status_code == 401
    assert client.get("/meta?t=promo").status_code == 403


def test_seuil_plancher_un_refus_ne_bannit_jamais(monkeypatch) -> None:
    monkeypatch.setenv("CAL_IUT_AA_REFUS_SEUIL", "1")
    client = _client(ASPIRATEUR)
    assert client.get("/export/json?t=promo").status_code == 401
    assert _bannis() == []
    assert client.get("/export/json?t=promo").status_code == 401
    assert len(_bannis()) == 1


def test_appli_qui_sonde_la_version_jamais_bannie() -> None:
    client = _client(APPLI_API)
    etag = None
    for _ in range(60):
        entetes = {"If-None-Match": etag} if etag else {}
        r = client.get("/api/v1/version?t=app", headers=entetes)
        assert r.status_code in (200, 304)
        etag = r.headers.get("ETag", etag)
    # Même sans lien ni clé (401 à chaque fois) : la sonde de version ne
    # compte jamais.
    for _ in range(60):
        assert client.get("/api/v1/version").status_code == 401
    assert _bannis() == []


def test_agenda_ics_jamais_banni() -> None:
    agenda = _client(GOOGLE_AGENDA, headers={"User-Agent": "Google-Calendar-Importer"})
    for n in range(80):
        assert agenda.get(f"/ics/prof/P{n % 7}.ics?t=P{n % 7}").status_code not in (401, 403)
    assert _bannis() == []


def test_navigateur_sur_lien_public_jamais_banni() -> None:
    navigateur = _client(NAVIGATEUR, headers={"User-Agent": "Mozilla/5.0 Firefox/130.0"})
    for _ in range(50):
        for chemin in ("/meta?t=TPA", "/app-state?t=TPA", "/api/v1/version?t=TPA"):
            assert navigateur.get(chemin).status_code not in (401, 403), chemin
    assert _bannis() == []


def test_refus_sur_auth_et_version_ne_comptent_pas() -> None:
    client = _client(ASPIRATEUR)
    for _ in range(40):
        assert client.get("/auth/me").status_code == 401
        assert client.get("/api/v1/version").status_code == 401
    assert _bannis() == []
    assert aa.trafic.instantane(3600)["clients"][0]["refus_acces"] == 0


def test_ip_exemptee_jamais_bannie(monkeypatch) -> None:
    monkeypatch.setenv("CAL_IUT_AA_EXEMPTS", "79.137.33.0/24")
    client = _client(ASPIRATEUR)
    for _ in range(40):
        assert client.get("/export/json?t=promo").status_code == 401
    assert _bannis() == []


def test_bannissement_sur_refus_desactivable(monkeypatch) -> None:
    monkeypatch.setenv(aa.REFUS_ENV, "off")
    client = _client(ASPIRATEUR)
    for _ in range(40):
        assert client.get("/export/json?t=promo").status_code == 401
    assert _bannis() == []
    # Le reste des protections (liste manuelle) tient toujours.
    aa.blocages.ajouter("ip", ASPIRATEUR, "à la main", "test")
    assert client.get("/meta?t=promo").status_code == 403


def test_un_compte_connecte_n_est_jamais_banni(db_isole) -> None:
    client = _client(NAVIGATEUR)
    creer_compte_actif_et_connecter(client, role="read_only")
    for _ in range(40):
        assert client.get("/admin/users").status_code == 403
    assert _bannis() == []


def test_ban_expire_rend_l_acces(tmp_path) -> None:
    client = _client(ASPIRATEUR)
    for _ in range(30):
        client.get("/export/json?t=promo")
    assert client.get("/meta?t=promo").status_code == 403
    fichier = tmp_path / "blocages.json"
    donnees = json.loads(fichier.read_text(encoding="utf-8"))
    donnees["blocages"][0]["expire_le"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat(timespec="seconds")
    fichier.write_text(json.dumps(donnees), encoding="utf-8")
    aa.blocages.vider_cache()
    assert client.get("/meta?t=promo").status_code != 403


def test_deblocage_par_un_admin(db_isole) -> None:
    client = _client(ASPIRATEUR)
    for _ in range(30):
        client.get("/export/json?t=promo")
    (ban,) = _bannis()
    admin = _client(ADMIN)
    creer_compte_actif_et_connecter(admin, role="admin")
    liste = admin.get("/admin/blocages").json()["blocages"]
    assert [(b["id"], b["source"]) for b in liste] == [(ban.id, "refus")]
    trafic = admin.get("/admin/trafic?fenetre=15min").json()
    (ligne,) = [c for c in trafic["clients"] if c["ip"] == ASPIRATEUR]
    assert ligne["refus_acces"] == 30 and ligne["blocage_id"] == ban.id
    assert admin.delete(f"/admin/blocages/{ban.id}").json() == {"ok": True}
    assert client.get("/meta?t=promo").status_code != 403
    # Compteur remis à zéro : un refus de plus ne rebannit pas aussitôt.
    assert client.get("/export/json?t=promo").status_code == 401
    assert client.get("/meta?t=promo").status_code != 403


def _derriere_le_proxy() -> TestClient:
    """L'application telle que `cal-iut serve` la sert : derrière le
    middleware de proxy d'uvicorn réglé sur les proxys de confiance, la
    requête arrivant de nginx (10.0.1.5)."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    appli = ProxyHeadersMiddleware(main.app, trusted_hosts=aa.proxys_de_confiance())
    return TestClient(appli, client=("10.0.1.5", 50000), raise_server_exceptions=False)


@pytest.mark.parametrize(
    "xff",
    [
        # nginx à jour : l'en-tête ne porte que l'IP réelle.
        ASPIRATEUR,
        # Ancien nginx (ajoute) : l'aspirateur écrit l'IP d'une victime à
        # gauche, le proxy ajoute la vraie à droite.
        f"{LECTEUR}, {ASPIRATEUR}",
    ],
)
def test_une_ip_falsifiee_ne_fait_pas_bannir_une_autre(xff) -> None:
    client = _derriere_le_proxy()
    for _ in range(30):
        assert client.get("/export/json?t=promo", headers={"X-Forwarded-For": xff}).status_code == 401
    assert [b.valeur for b in _bannis()] == [ASPIRATEUR]
    victime = _client(LECTEUR)
    assert victime.get("/meta?t=promo").status_code != 403


def test_en_tete_ignore_hors_proxy() -> None:
    """Requête qui n'arrive pas d'un proxy : `X-Forwarded-For` n'est pas lu,
    c'est l'adresse de connexion qui est bannie."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    appli = ProxyHeadersMiddleware(main.app, trusted_hosts=aa.proxys_de_confiance())
    client = TestClient(appli, client=(ASPIRATEUR, 50000), raise_server_exceptions=False)
    for _ in range(30):
        client.get("/export/json?t=promo", headers={"X-Forwarded-For": LECTEUR})
    assert [b.valeur for b in _bannis()] == [ASPIRATEUR]
