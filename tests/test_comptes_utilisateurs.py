"""Comptes utilisateurs (email + mot de passe + rôles) — remplace le mot de
passe unique partagé (`CAL_IUT_PASSWORD`, `api/auth.py`) par de vrais
comptes : signup + confirmation e-mail + activation admin, connexion,
mot de passe oublié/réinitialisation, gestion des rôles côté `/admin/users`.

Contrat verrouillé par l'architecte (ne pas dévier — voir le prompt de
session) : tables `User`/`EmailToken` (`db/models.py`), module
`api/accounts.py`, `db/accounts_repository.py::AccountRepository`,
endpoints `/auth/*` et `/admin/users*` dans `api/main.py`.

RIEN de ceci n'existe encore : ce fichier doit échouer entièrement à la
collecte (ImportError sur `cal_iut.db.models.User`/`EmailToken`) tant que
l'implémentation n'existe pas — c'est le point de départ (rouge) attendu.

Style : mêmes conventions que `tests/test_auth_2026_08_28.py` (TestClient
partagé au niveau module, cookies nettoyés par un fixture autouse, noms de
tests en français). Base de comptes isolée par test dans un fichier SQLite
temporaire (même schéma que `tests/test_db.py`), jamais la vraie
`data/state/cal-iut.db` du dépôt.

Ne fait JAMAIS de vrai appel réseau : `mailer.send_email`/`is_configured`
sont monkeypatchés partout, comme dans `test_mail_teacher_links_2026_08_28.py`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import accounts, mailer
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.db import session as db_session
from cal_iut.db.models import EmailToken, User
from cal_iut.db.session import get_db, init_db
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

ADMIN_EMAIL = "crevoisier.ju@gmail.com"  # membre de accounts.ADMIN_EMAILS (contrat)
AUTRE_ADMIN_EMAIL = "kyllian.bresson@univ-reims.fr"  # deuxième membre, pour le scénario multi-admin
MOT_DE_PASSE = "Motdepasse123"  # >= 10 caractères (min_length du contrat)


# --------------------------------------------------------------------------
# Isolation : cookies + base SQLite dédiée par test.
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolation(tmp_path):
    """Repart d'un client sans cookie, sur une base SQLite temporaire —
    même esprit que `_sans_session` (test_auth) + `test_db.py::repo` :
    sans ça, chaque test écrirait des `User`/`EmailToken` réels dans
    `data/state/cal-iut.db` du dépôt (édité en direct par ailleurs)."""
    etat = get_state()
    ancien_db_path = etat.db_path
    db_path = tmp_path / f"comptes_{uuid.uuid4().hex}.db"
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(db_path)
    etat.db_path = db_path
    client.cookies.clear()
    yield
    client.cookies.clear()
    etat.db_path = ancien_db_path
    if db_session._engine:
        db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None


def _db():
    return get_db(get_state().db_path)


# --------------------------------------------------------------------------
# Petits ateliers de fabrication d'état, construits via l'API elle-même
# quand c'est possible (jamais via des méthodes de repository dont la
# signature exacte n'est pas verrouillée par le contrat) — un rang admin
# s'obtient par la vraie voie "signup + confirm-email sur une adresse
# ADMIN_EMAILS", jamais en écrivant `role="admin"` à la main.
# --------------------------------------------------------------------------


def _capturer_mail(monkeypatch) -> list[tuple[str, str, str, str | None]]:
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    captures: list[tuple[str, str, str, str | None]] = []

    def _send(to, subject, text, html=None):
        captures.append((to, subject, text, html))
        return "msg_test"

    monkeypatch.setattr(mailer, "send_email", _send)
    return captures


def _extraire_token(texte: str) -> str:
    m = re.search(r"token=([^&\s\"'<]+)", texte)
    assert m, f"aucun `token=` trouvé dans le mail envoyé : {texte!r}"
    return m.group(1)


def _signup_et_extraire_token(monkeypatch, email: str, password: str = MOT_DE_PASSE) -> str:
    captures = _capturer_mail(monkeypatch)
    reponse = client.post("/auth/signup", json={"email": email, "password": password})
    assert reponse.status_code == 201, reponse.text
    return _extraire_token(captures[-1][2])


def _confirmer(token: str):
    return client.get(f"/auth/confirm-email?token={token}", follow_redirects=False)


def _id_utilisateur(email: str) -> int:
    db = _db()
    try:
        row = db.query(User).filter(User.email == email.strip().lower()).one()
        return row.id
    finally:
        db.close()


def _statut_et_role(email: str) -> tuple[str, str]:
    db = _db()
    try:
        row = db.query(User).filter(User.email == email.strip().lower()).one()
        return row.status, row.role
    finally:
        db.close()


def _inserer_utilisateur(email: str, *, role: str = "read_only", status: str = "active", password: str = MOT_DE_PASSE) -> int:
    """Insertion directe (bypass signup) pour les cas où seul l'état final
    compte, ex. un compte déjà `disabled` pour les tests `/auth/me`."""
    db = _db()
    try:
        user = User(
            email=email.strip().lower(),
            password_hash=accounts.hash_password(password),
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _inserer_token(user_id: int, purpose: str, *, expire_dans: timedelta = timedelta(hours=1), deja_utilise: bool = False) -> str:
    raw = uuid.uuid4().hex
    db = _db()
    try:
        entree = EmailToken(
            user_id=user_id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            purpose=purpose,
            expires_at=datetime.now(UTC) + expire_dans,
            used_at=datetime.now(UTC) if deja_utilise else None,
        )
        db.add(entree)
        db.commit()
        return raw
    finally:
        db.close()


@pytest.fixture
def admin_session(monkeypatch):
    """Connecte le client module-level avec un vrai compte admin actif,
    obtenu par la voie prévue par le contrat (signup + confirm-email sur
    une adresse `ADMIN_EMAILS`)."""
    token = _signup_et_extraire_token(monkeypatch, ADMIN_EMAIL)
    _confirmer(token)
    reponse = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": MOT_DE_PASSE})
    assert reponse.status_code == 200, reponse.text
    yield _id_utilisateur(ADMIN_EMAIL)
    client.post("/auth/logout")
    client.cookies.clear()


def _creer_et_activer(monkeypatch, email: str, *, role: str | None = None, status: str | None = None) -> int:
    """Fait passer un utilisateur par signup + confirm-email (donc
    `pending_admin_activation` pour une adresse non-admin), puis, si
    demandé, active/ajuste via `PATCH /admin/users/{id}` — nécessite un
    admin déjà connecté sur le client partagé (appelant responsable de ça)."""
    token = _signup_et_extraire_token(monkeypatch, email)
    _confirmer(token)
    user_id = _id_utilisateur(email)
    if role is not None or status is not None:
        corps: dict[str, str] = {}
        if role is not None:
            corps["role"] = role
        if status is not None:
            corps["status"] = status
        reponse = client.patch(f"/admin/users/{user_id}", json=corps)
        assert reponse.status_code == 200, reponse.text
    return user_id


# --------------------------------------------------------------------------
# POST /auth/signup
# --------------------------------------------------------------------------


def test_signup_sans_mailer_configure_renvoie_503_et_ne_cree_personne(monkeypatch) -> None:
    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    reponse = client.post("/auth/signup", json={"email": "nouveau@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 503
    db = _db()
    try:
        assert db.query(User).filter(User.email == "nouveau@example.test").first() is None
    finally:
        db.close()


def test_signup_reussi_cree_un_compte_pending_email_et_envoie_un_mail_de_confirmation(monkeypatch) -> None:
    captures = _capturer_mail(monkeypatch)
    reponse = client.post("/auth/signup", json={"email": "nouveau@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 201
    assert reponse.json() == {"status": "pending_email"}

    assert len(captures) == 1
    to, _subject, texte, _html = captures[0]
    assert to == "nouveau@example.test"
    assert "confirm-email" in texte and "token=" in texte

    statut, _role = _statut_et_role("nouveau@example.test")
    assert statut == "pending_email"


def test_signup_normalise_l_email_en_minuscules_et_sans_espaces(monkeypatch) -> None:
    _capturer_mail(monkeypatch)
    reponse = client.post("/auth/signup", json={"email": "  NOUVEAU@Example.Test  ", "password": MOT_DE_PASSE})
    assert reponse.status_code == 201
    db = _db()
    try:
        assert db.query(User).filter(User.email == "nouveau@example.test").one_or_none() is not None
    finally:
        db.close()


@pytest.mark.parametrize("statut_existant", ["active", "pending_admin_activation", "disabled"])
def test_signup_avec_email_deja_confirme_renvoie_409(monkeypatch, statut_existant) -> None:
    _inserer_utilisateur("deja@example.test", status=statut_existant)
    _capturer_mail(monkeypatch)
    reponse = client.post("/auth/signup", json={"email": "deja@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 409


def test_signup_sur_un_pending_email_existant_renvoie_un_nouveau_token_au_lieu_de_409(monkeypatch) -> None:
    """Cas spécial verrouillé (anti-scanner de mails) : un second signup sur
    la même adresse encore `pending_email` renvoie 201 comme un signup
    neuf — pas 409 — et invalide le jeton `confirm_email` déjà émis."""
    ancien_token = _signup_et_extraire_token(monkeypatch, "encore-en-attente@example.test")

    nouvelles_captures = _capturer_mail(monkeypatch)
    reponse = client.post("/auth/signup", json={"email": "encore-en-attente@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 201
    assert reponse.json() == {"status": "pending_email"}
    assert len(nouvelles_captures) == 1

    # Un seul utilisateur, pas un doublon.
    db = _db()
    try:
        assert db.query(User).filter(User.email == "encore-en-attente@example.test").count() == 1
    finally:
        db.close()

    # L'ANCIEN jeton, jamais utilisé mais désormais invalidé, ne doit plus
    # confirmer quoi que ce soit.
    reponse_ancien = _confirmer(ancien_token)
    assert reponse_ancien.status_code == 302
    assert "statut=erreur" in reponse_ancien.headers["location"]

    # Le nouveau jeton, lui, fonctionne.
    nouveau_token = _extraire_token(nouvelles_captures[-1][2])
    reponse_nouveau = _confirmer(nouveau_token)
    assert reponse_nouveau.status_code == 302
    assert "statut=ok" in reponse_nouveau.headers["location"]


# --------------------------------------------------------------------------
# GET /auth/confirm-email
# --------------------------------------------------------------------------


def test_confirm_email_token_inconnu_redirige_avec_statut_erreur() -> None:
    reponse = client.get("/auth/confirm-email?token=nimportequoi", follow_redirects=False)
    assert reponse.status_code == 302
    assert "statut=erreur" in reponse.headers["location"]


def test_confirm_email_token_expire_redirige_avec_statut_erreur() -> None:
    user_id = _inserer_utilisateur("expire@example.test", status="pending_email")
    token = _inserer_token(user_id, "confirm_email", expire_dans=timedelta(hours=-1))
    reponse = _confirmer(token)
    assert reponse.status_code == 302
    assert "statut=erreur" in reponse.headers["location"]
    statut, _role = _statut_et_role("expire@example.test")
    assert statut == "pending_email"


def test_confirm_email_token_deja_consomme_redirige_avec_statut_erreur() -> None:
    user_id = _inserer_utilisateur("deja-consomme@example.test", status="pending_email")
    token = _inserer_token(user_id, "confirm_email", deja_utilise=True)
    reponse = _confirmer(token)
    assert reponse.status_code == 302
    assert "statut=erreur" in reponse.headers["location"]


def test_confirm_email_valide_active_le_compte_en_attente_d_activation_admin(monkeypatch) -> None:
    token = _signup_et_extraire_token(monkeypatch, "future-editrice@example.test")
    reponse = _confirmer(token)
    assert reponse.status_code == 302
    assert "statut=ok" in reponse.headers["location"]
    statut, role = _statut_et_role("future-editrice@example.test")
    assert statut == "pending_admin_activation"
    assert role == "read_only"


def test_confirm_email_sur_une_adresse_admin_emails_active_directement_en_admin(monkeypatch) -> None:
    token = _signup_et_extraire_token(monkeypatch, ADMIN_EMAIL)
    _confirmer(token)
    statut, role = _statut_et_role(ADMIN_EMAIL)
    assert statut == "active"
    assert role == "admin"


# --------------------------------------------------------------------------
# POST /auth/login
# --------------------------------------------------------------------------


def test_login_email_inconnu_et_mot_de_passe_incorrect_donnent_le_meme_corps_401() -> None:
    """Pas d'énumération de comptes : les deux échecs doivent être
    indiscernables, jusqu'à l'octet près."""
    _inserer_utilisateur("existe@example.test", status="active", password=MOT_DE_PASSE)

    reponse_inconnu = client.post("/auth/login", json={"email": "inconnu@example.test", "password": MOT_DE_PASSE})
    reponse_mauvais_mdp = client.post("/auth/login", json={"email": "existe@example.test", "password": "mauvais-mot-de-passe"})

    assert reponse_inconnu.status_code == 401
    assert reponse_mauvais_mdp.status_code == 401
    assert reponse_inconnu.content == reponse_mauvais_mdp.content
    assert reponse_inconnu.json() == {"detail": "Email ou mot de passe incorrect."}


def test_login_pending_email_est_refuse_403() -> None:
    _inserer_utilisateur("pas-confirme@example.test", status="pending_email")
    reponse = client.post("/auth/login", json={"email": "pas-confirme@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 403


def test_login_disabled_est_refuse_403() -> None:
    _inserer_utilisateur("bloque@example.test", status="disabled")
    reponse = client.post("/auth/login", json={"email": "bloque@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 403


def test_login_pending_admin_activation_reussit_et_pose_le_cookie() -> None:
    _inserer_utilisateur("en-attente-admin@example.test", status="pending_admin_activation")
    reponse = client.post("/auth/login", json={"email": "en-attente-admin@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 200, reponse.text
    assert accounts.ACCOUNT_SESSION_COOKIE in reponse.cookies


def test_login_active_reussit_et_expose_role_et_status() -> None:
    _inserer_utilisateur("active@example.test", status="active", role="edit")
    reponse = client.post("/auth/login", json={"email": "active@example.test", "password": MOT_DE_PASSE})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["role"] == "edit"
    assert corps["status"] == "active"


# --------------------------------------------------------------------------
# POST /auth/logout
# --------------------------------------------------------------------------


def test_logout_supprime_le_cookie_de_session() -> None:
    _inserer_utilisateur("a-deconnecter@example.test", status="active")
    client.post("/auth/login", json={"email": "a-deconnecter@example.test", "password": MOT_DE_PASSE})
    reponse = client.post("/auth/logout")
    assert reponse.status_code == 200
    assert client.get("/auth/me").status_code == 401


# --------------------------------------------------------------------------
# POST /auth/forgot-password
# --------------------------------------------------------------------------


def test_forgot_password_renvoie_toujours_200_ok_meme_pour_un_email_inconnu(monkeypatch) -> None:
    _inserer_utilisateur("reelle@example.test", status="active")
    appeles = _capturer_mail(monkeypatch)

    reponse_inconnu = client.post("/auth/forgot-password", json={"email": "fantome@example.test"})
    reponse_reelle = client.post("/auth/forgot-password", json={"email": "reelle@example.test"})

    assert reponse_inconnu.status_code == 200
    assert reponse_reelle.status_code == 200
    assert reponse_inconnu.json() == {"ok": True}
    assert reponse_reelle.json() == {"ok": True}
    # Seule l'adresse réelle et active doit avoir déclenché un envoi.
    assert len(appeles) == 1
    assert appeles[0][0] == "reelle@example.test"


@pytest.mark.parametrize("statut", ["pending_email", "disabled"])
def test_forgot_password_n_envoie_rien_pour_un_compte_pending_ou_disabled(monkeypatch, statut) -> None:
    _inserer_utilisateur("pas-eligible@example.test", status=statut)
    appeles = _capturer_mail(monkeypatch)
    reponse = client.post("/auth/forgot-password", json={"email": "pas-eligible@example.test"})
    assert reponse.status_code == 200
    assert reponse.json() == {"ok": True}
    assert appeles == []


def test_forgot_password_invalide_les_jetons_reset_precedents_du_meme_compte(monkeypatch) -> None:
    user_id = _inserer_utilisateur("mot-de-passe-oublie@example.test", status="active")
    ancien_token = _inserer_token(user_id, "reset_password")
    _capturer_mail(monkeypatch)

    reponse = client.post("/auth/forgot-password", json={"email": "mot-de-passe-oublie@example.test"})
    assert reponse.status_code == 200

    # L'ancien jeton, jamais expiré ni consommé lui-même, doit désormais être
    # rejeté (invalidation immédiate au moment du nouvel envoi).
    reponse_reset = client.post(
        "/auth/reset-password", json={"token": ancien_token, "new_password": "UnAutreMotDePasse1"}
    )
    assert reponse_reset.status_code == 400


# --------------------------------------------------------------------------
# POST /auth/reset-password
# --------------------------------------------------------------------------


def test_reset_password_token_invalide_renvoie_400() -> None:
    reponse = client.post("/auth/reset-password", json={"token": "nimportequoi", "new_password": "UnAutreMotDePasse1"})
    assert reponse.status_code == 400


def test_reset_password_token_expire_renvoie_400() -> None:
    user_id = _inserer_utilisateur("expire-reset@example.test", status="active")
    token = _inserer_token(user_id, "reset_password", expire_dans=timedelta(hours=-1))
    reponse = client.post("/auth/reset-password", json={"token": token, "new_password": "UnAutreMotDePasse1"})
    assert reponse.status_code == 400


def test_reset_password_token_deja_utilise_renvoie_400() -> None:
    user_id = _inserer_utilisateur("deja-utilise-reset@example.test", status="active")
    token = _inserer_token(user_id, "reset_password", deja_utilise=True)
    reponse = client.post("/auth/reset-password", json={"token": token, "new_password": "UnAutreMotDePasse1"})
    assert reponse.status_code == 400


def test_reset_password_sur_un_compte_disabled_renvoie_403() -> None:
    user_id = _inserer_utilisateur("bloque-reset@example.test", status="disabled")
    token = _inserer_token(user_id, "reset_password")
    reponse = client.post("/auth/reset-password", json={"token": token, "new_password": "UnAutreMotDePasse1"})
    assert reponse.status_code == 403


def test_reset_password_reussi_change_le_mot_de_passe_et_invalide_les_autres_jetons_du_meme_compte() -> None:
    user_id = _inserer_utilisateur("reset-complet@example.test", status="active", password=MOT_DE_PASSE)
    token_a_consommer = _inserer_token(user_id, "reset_password")
    token_toujours_valide_par_ailleurs = _inserer_token(user_id, "reset_password")

    reponse = client.post(
        "/auth/reset-password", json={"token": token_a_consommer, "new_password": "NouveauMotDePasse1"}
    )
    assert reponse.status_code == 200, reponse.text

    # Le nouveau mot de passe fonctionne bien à la connexion.
    reponse_login = client.post("/auth/login", json={"email": "reset-complet@example.test", "password": "NouveauMotDePasse1"})
    assert reponse_login.status_code == 200
    client.post("/auth/logout")
    client.cookies.clear()

    # Le SECOND jeton, pourtant non expiré et non consommé lui-même, doit
    # être immédiatement rejeté — invalidé en cascade par le premier reset.
    reponse_second = client.post(
        "/auth/reset-password", json={"token": token_toujours_valide_par_ailleurs, "new_password": "TroisiemeMotDePasse1"}
    )
    assert reponse_second.status_code == 400


# --------------------------------------------------------------------------
# GET /auth/me
# --------------------------------------------------------------------------


def test_me_sans_cookie_renvoie_401() -> None:
    assert client.get("/auth/me").status_code == 401


def test_me_avec_un_compte_disabled_renvoie_quand_meme_l_identite() -> None:
    """Un compte `pending`/`disabled` doit pouvoir résoudre qui il est —
    seules les routes protégées par `require_role` doivent le refuser, pas
    `/auth/me`. Le cookie est ici construit directement (le login normal
    bloquerait un compte `disabled` en amont), comme le ferait un vrai
    cookie déjà posé avant une désactivation ultérieure."""
    user_id = _inserer_utilisateur("desactive-mais-identifiable@example.test", status="disabled")
    client.cookies.set(accounts.ACCOUNT_SESSION_COOKIE, accounts.make_account_session_token(user_id))

    reponse = client.get("/auth/me")
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["id"] == user_id
    assert corps["email"] == "desactive-mais-identifiable@example.test"
    assert corps["status"] == "disabled"


def test_me_avec_cookie_valide_renvoie_id_email_role_status() -> None:
    user_id = _inserer_utilisateur("moi-meme@example.test", status="active", role="edit")
    client.post("/auth/login", json={"email": "moi-meme@example.test", "password": MOT_DE_PASSE})
    corps = client.get("/auth/me").json()
    assert corps == {"id": user_id, "email": "moi-meme@example.test", "role": "edit", "status": "active"}


# --------------------------------------------------------------------------
# GET /admin/users
# --------------------------------------------------------------------------


def test_admin_users_liste_refusee_401_pour_un_visiteur_anonyme() -> None:
    assert client.get("/admin/users").status_code == 401


def test_admin_users_liste_refusee_403_pour_un_role_edit() -> None:
    _inserer_utilisateur("editrice@example.test", status="active", role="edit")
    client.post("/auth/login", json={"email": "editrice@example.test", "password": MOT_DE_PASSE})
    assert client.get("/admin/users").status_code == 403


def test_admin_users_liste_accessible_a_un_admin_et_filtrable_par_statut(admin_session, monkeypatch) -> None:
    _creer_et_activer(monkeypatch, "lectrice-en-attente@example.test")  # reste pending_admin_activation

    tous = client.get("/admin/users").json()
    emails = {u["email"] for u in tous["users"]} if isinstance(tous, dict) and "users" in tous else {u["email"] for u in tous}
    assert "lectrice-en-attente@example.test" in emails

    filtres = client.get("/admin/users?status=pending_admin_activation").json()
    filtres_emails = {u["email"] for u in filtres["users"]} if isinstance(filtres, dict) and "users" in filtres else {u["email"] for u in filtres}
    assert "lectrice-en-attente@example.test" in filtres_emails
    assert ADMIN_EMAIL not in filtres_emails  # l'admin lui-même est `active`, pas `pending_admin_activation`


# --------------------------------------------------------------------------
# PATCH /admin/users/{id}
# --------------------------------------------------------------------------


def test_admin_patch_users_400_si_ni_role_ni_status(admin_session, monkeypatch) -> None:
    cible = _creer_et_activer(monkeypatch, "cible-vide@example.test")
    reponse = client.patch(f"/admin/users/{cible}", json={})
    assert reponse.status_code == 400


def test_admin_patch_users_404_si_id_inconnu(admin_session) -> None:
    reponse = client.patch("/admin/users/999999999", json={"role": "edit"})
    assert reponse.status_code == 404


def test_admin_patch_users_fixer_le_role_active_un_compte_pending_admin_activation(admin_session, monkeypatch) -> None:
    cible = _creer_et_activer(monkeypatch, "a-activer@example.test")
    statut_avant, _role = _statut_et_role("a-activer@example.test")
    assert statut_avant == "pending_admin_activation"

    reponse = client.patch(f"/admin/users/{cible}", json={"role": "edit"})
    assert reponse.status_code == 200, reponse.text

    statut_apres, role_apres = _statut_et_role("a-activer@example.test")
    assert statut_apres == "active"
    assert role_apres == "edit"


def test_admin_patch_users_refuse_de_desactiver_le_dernier_admin_actif(admin_session) -> None:
    reponse = client.patch(f"/admin/users/{admin_session}", json={"status": "disabled"})
    assert reponse.status_code == 409
    assert reponse.json()["message"] == "Impossible de retirer le dernier administrateur actif."
    statut, _role = _statut_et_role(ADMIN_EMAIL)
    assert statut == "active"


def test_admin_patch_users_refuse_de_retrograder_le_role_du_dernier_admin_actif(admin_session) -> None:
    reponse = client.patch(f"/admin/users/{admin_session}", json={"role": "edit"})
    assert reponse.status_code == 409
    assert reponse.json()["message"] == "Impossible de retirer le dernier administrateur actif."
    _statut, role = _statut_et_role(ADMIN_EMAIL)
    assert role == "admin"


def test_admin_patch_users_scenario_multi_admin_le_dernier_seul_reste_protege(admin_session, monkeypatch) -> None:
    """Deux admins actifs : rétrograder/désactiver l'un des deux doit
    réussir (il en reste encore un actif) — puis la même opération sur le
    DERNIER restant doit échouer en 409."""
    deuxieme_admin_id = _signup_et_extraire_token(monkeypatch, AUTRE_ADMIN_EMAIL)
    _confirmer(deuxieme_admin_id)
    deuxieme_admin_id = _id_utilisateur(AUTRE_ADMIN_EMAIL)
    statut, role = _statut_et_role(AUTRE_ADMIN_EMAIL)
    assert (statut, role) == ("active", "admin")  # deuxième adresse ADMIN_EMAILS, même mécanisme

    # Avec deux admins actifs, désactiver le deuxième doit réussir.
    reponse_ok = client.patch(f"/admin/users/{deuxieme_admin_id}", json={"status": "disabled"})
    assert reponse_ok.status_code == 200, reponse_ok.text

    # Il ne reste plus qu'un seul admin actif (le premier) : le même genre
    # d'opération sur lui doit désormais échouer.
    reponse_refusee = client.patch(f"/admin/users/{admin_session}", json={"status": "disabled"})
    assert reponse_refusee.status_code == 409


# --------------------------------------------------------------------------
# Plancher de rôles sur les routes existantes (contrat : toute route
# auparavant protégée par le seul mot de passe partagé exige désormais
# `require_role("read_only")` au minimum ; les routes de mutation
# `require_role("edit")` ; les anciennes routes `require_admin_session`
# deviennent `require_role("admin")`.
# --------------------------------------------------------------------------


def test_route_de_lecture_exige_au_moins_le_role_read_only() -> None:
    assert client.get("/meta").status_code == 401  # anonyme : bloqué

    _inserer_utilisateur("lectrice@example.test", status="active", role="read_only")
    client.post("/auth/login", json={"email": "lectrice@example.test", "password": MOT_DE_PASSE})
    assert client.get("/meta").status_code == 200


def test_route_de_mutation_exige_au_moins_le_role_edit() -> None:
    """`DELETE /exceptions/{id}` : un id inexistant renvoie 404 une fois
    passée la barrière de rôle — ce 404 (business, pas 403 d'auth) prouve
    qu'un rôle `edit` a bien traversé la garde, là où `read_only` ne le
    doit pas."""
    _inserer_utilisateur("lectrice-seule@example.test", status="active", role="read_only")
    client.post("/auth/login", json={"email": "lectrice-seule@example.test", "password": MOT_DE_PASSE})
    assert client.delete("/exceptions/999999999").status_code == 403
    client.post("/auth/logout")
    client.cookies.clear()

    _inserer_utilisateur("editrice-mutation@example.test", status="active", role="edit")
    client.post("/auth/login", json={"email": "editrice-mutation@example.test", "password": MOT_DE_PASSE})
    assert client.delete("/exceptions/999999999").status_code == 404


def test_anciennes_routes_require_admin_session_exigent_desormais_le_role_admin() -> None:
    """`GET /celcat/plan` représente ici tout le groupe migré depuis
    `require_admin_session` (`POST /rooms`, `POST /notifications/test`,
    `GET /mail/teacher-links*`, `POST /mail/teacher-links/send`)."""
    assert client.get("/celcat/plan").status_code == 401  # anonyme

    _inserer_utilisateur("editrice-non-admin@example.test", status="active", role="edit")
    client.post("/auth/login", json={"email": "editrice-non-admin@example.test", "password": MOT_DE_PASSE})
    assert client.get("/celcat/plan").status_code == 403


# --------------------------------------------------------------------------
# Régression : les liens personnels `?t=...` restent publics, sans compte
# ni cookie — c'est le comportement le plus facile à casser par accident
# en migrant `require_auth` vers le système de comptes (contrat explicite).
# --------------------------------------------------------------------------


@pytest.fixture
def etat_avec_seance():
    """État minimal, monté à la main (même patron que
    `test_auth_2026_08_28.py::etat_avec_seance`) — sans lui, `/app-state`
    404 sur « Aucun planning résolu » avant même d'atteindre la question
    d'authentification que ce test vérifie réellement : `state.timetable`
    n'est jamais peuplé par le cycle de vie de l'app dans ce fichier
    (`TestClient(app)` sans `with`, cf. tous les autres tests de ce
    module), il faut donc le simuler explicitement."""
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "groups": etat.groups, "rooms": etat.rooms,
        "calendar": etat.calendar, "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability,
        "config_dir": etat.config_dir, "student_presences": etat.student_presences,
        "corrections": etat.corrections, "courses": etat.courses,
        "teacher_duos": etat.teacher_duos,
    }
    seance = SessionToPlace(
        id="s1", course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["KBR"],
    )
    etat.sessions = [seance]
    etat.sessions_by_id = {"s1": seance}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="s1", week=0, day=0, slot=0,
                               course_code="WR101", group_ids=["but1-td-ab"], teacher_codes=["KBR"]),
    ]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.config_dir = ROOT / "data" / "config"
    etat.student_presences = []
    etat.corrections = []
    etat.courses = []
    etat.teacher_duos = []
    yield
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_lien_personnel_t_reste_accessible_sans_cookie_ni_compte(etat_avec_seance) -> None:
    assert client.cookies.get(accounts.ACCOUNT_SESSION_COOKIE) is None
    reponse_app_state = client.get("/app-state?t=KBR")
    assert reponse_app_state.status_code == 200, reponse_app_state.text

    reponse_ics = client.get("/ics/prof/KBR.ics?t=KBR")
    assert reponse_ics.status_code == 200, reponse_ics.text


# --------------------------------------------------------------------------
# `CAL_IUT_PASSWORD` ne doit plus authentifier quoi que ce soit, nulle part.
# --------------------------------------------------------------------------


def test_cal_iut_password_n_authentifie_plus_rien_sur_auth_login() -> None:
    import os

    ancien_mot_de_passe_partage = os.environ.get("CAL_IUT_PASSWORD")
    assert ancien_mot_de_passe_partage, "CAL_IUT_PASSWORD doit être positionné par conftest.py"

    reponse = client.post("/auth/login", json={"password": ancien_mot_de_passe_partage})
    # Ancienne forme du corps (`{password}` seul, sans `email`) : soit 422
    # (schéma désormais `{email, password}`), soit 401 — jamais un succès.
    assert reponse.status_code in (401, 422)
    assert accounts.ACCOUNT_SESSION_COOKIE not in reponse.cookies


# --------------------------------------------------------------------------
# Effet immédiat d'une action admin : le rôle/statut est relu en base à
# CHAQUE requête, jamais mis en cache dans le cookie/la session.
# --------------------------------------------------------------------------


def test_une_desactivation_admin_bloque_la_requete_suivante_sans_nouveau_cookie(admin_session, monkeypatch) -> None:
    cible_id = _creer_et_activer(monkeypatch, "editrice-a-desactiver@example.test", role="edit")

    client.post("/auth/logout")  # quitte la session admin sur le client partagé
    client.cookies.clear()
    client.post("/auth/login", json={"email": "editrice-a-desactiver@example.test", "password": MOT_DE_PASSE})

    # Avant toute action admin : le rôle edit traverse bien la garde de
    # mutation (même sonde 404-vs-403 que le test de plancher de rôles).
    assert client.delete("/exceptions/999999999").status_code == 404

    # Un admin la désactive, PENDANT que le cookie `edit` original reste
    # posé sur le client — on ne se reconnecte jamais.
    cookie_edit = dict(client.cookies)
    client.cookies.clear()
    client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": MOT_DE_PASSE})
    reponse_patch = client.patch(f"/admin/users/{cible_id}", json={"status": "disabled"})
    assert reponse_patch.status_code == 200, reponse_patch.text
    client.post("/auth/logout")
    client.cookies.clear()

    # On rejoue EXACTEMENT le même cookie `edit`, jamais renouvelé.
    for nom, valeur in cookie_edit.items():
        client.cookies.set(nom, valeur)
    assert client.delete("/exceptions/999999999").status_code == 403
