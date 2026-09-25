"""`DELETE /admin/users/{id}` (25/09/2026, dicté par Jules) : « Dans les
comptes, est-ce que tu peux ajouter la possibilité de supprimer les
personnes en attente d'activation ? C'est des personnes qui se sont
trompées ou qu'on ne veut pas, donc on veut les supprimer. »

Statuts identifiés dans `db/models.py::User`/`api/accounts.py` : un compte
passe par `pending_email` (signup fait, email pas confirmé) puis, une fois
l'email confirmé, soit directement `active` (adresse `ADMIN_EMAILS`) soit
`pending_admin_activation` (attend qu'un admin déjà actif lui donne un rôle
via `PATCH /admin/users/{id}`) ; un admin peut ensuite `disabled` un compte
`active`. La suppression se limite à `accounts.PENDING_STATUSES`
(`pending_email`, `pending_admin_activation`) — tout autre statut
(`active`, `disabled`) est refusé, ces comptes ayant été activés un jour.

Style : mêmes conventions que `tests/test_comptes_utilisateurs.py`, dont ce
fichier réutilise les ateliers (`admin_session`, `_creer_et_activer`,
`_inserer_utilisateur`, `_id_utilisateur`, `_statut_et_role`) plutôt que de
les redéfinir — même base SQLite temporaire isolée par test, même client
`TestClient` partagé.
"""

from __future__ import annotations

import pytest
from test_comptes_utilisateurs import (
    ADMIN_EMAIL,
    AUTRE_ADMIN_EMAIL,
    MOT_DE_PASSE,
    _confirmer,
    _creer_et_activer,
    _db,
    _id_utilisateur,
    _inserer_utilisateur,
    _isolation,  # noqa: F401 -- fixture autouse réutilisée
    _signup_et_extraire_token,
    admin_session,  # noqa: F401 -- fixture réutilisée
    client,
)

from cal_iut.db.models import User


def _existe_encore(email: str) -> bool:
    db = _db()
    try:
        return db.query(User).filter(User.email == email.strip().lower()).first() is not None
    finally:
        db.close()


# --------------------------------------------------------------------------
# DELETE /admin/users/{id}
# --------------------------------------------------------------------------


@pytest.mark.parametrize("statut_en_attente", ["pending_email", "pending_admin_activation"])
def test_suppression_d_un_compte_en_attente_reussit_et_le_retire_de_la_base(admin_session, statut_en_attente) -> None:  # noqa: F811
    cible_id = _inserer_utilisateur("jamais-active@example.test", status=statut_en_attente)

    reponse = client.delete(f"/admin/users/{cible_id}")
    assert reponse.status_code == 200, reponse.text
    assert not _existe_encore("jamais-active@example.test")


def test_suppression_d_un_compte_actif_est_refusee_et_le_compte_survit(admin_session) -> None:  # noqa: F811
    cible_id = _inserer_utilisateur("deja-active@example.test", status="active", role="edit")

    reponse = client.delete(f"/admin/users/{cible_id}")
    assert 400 <= reponse.status_code < 500, reponse.text
    assert reponse.json()["message"]
    assert _existe_encore("deja-active@example.test")


def test_suppression_d_un_compte_desactive_est_refusee_et_le_compte_survit(admin_session) -> None:  # noqa: F811
    """Un compte `disabled` a forcément été `active` un jour (`activated_at`
    posé) : même refus qu'un compte encore `active`, pas une suppression
    silencieuse déguisée en désactivation."""
    cible_id = _inserer_utilisateur("bloque-desactive@example.test", status="disabled", role="edit")

    reponse = client.delete(f"/admin/users/{cible_id}")
    assert 400 <= reponse.status_code < 500, reponse.text
    assert _existe_encore("bloque-desactive@example.test")


def test_admin_ne_peut_pas_se_supprimer_lui_meme(admin_session) -> None:  # noqa: F811
    reponse = client.delete(f"/admin/users/{admin_session}")
    assert 400 <= reponse.status_code < 500, reponse.text
    assert reponse.json()["message"]
    assert _existe_encore(ADMIN_EMAIL)


def test_suppression_id_inconnu_renvoie_404(admin_session) -> None:  # noqa: F811
    reponse = client.delete("/admin/users/999999999")
    assert reponse.status_code == 404


def test_suppression_refusee_401_pour_un_visiteur_anonyme() -> None:
    cible_id = _inserer_utilisateur("anonyme-cible@example.test", status="pending_admin_activation")
    reponse = client.delete(f"/admin/users/{cible_id}")
    assert reponse.status_code == 401
    assert _existe_encore("anonyme-cible@example.test")


def test_suppression_refusee_403_pour_un_role_non_admin() -> None:
    cible_id = _inserer_utilisateur("cible-non-admin@example.test", status="pending_admin_activation")
    _inserer_utilisateur("editrice-suppr@example.test", status="active", role="edit")
    client.post("/auth/login", json={"email": "editrice-suppr@example.test", "password": MOT_DE_PASSE})

    reponse = client.delete(f"/admin/users/{cible_id}")
    assert reponse.status_code == 403
    assert _existe_encore("cible-non-admin@example.test")


def test_suppression_d_un_compte_pending_admin_activation_cree_via_signup(admin_session, monkeypatch) -> None:  # noqa: F811
    """Bout en bout par la vraie voie (signup + confirm-email), pas
    seulement une insertion directe en base."""
    cible_id = _creer_et_activer(monkeypatch, "vrai-signup-a-supprimer@example.test")

    reponse = client.delete(f"/admin/users/{cible_id}")
    assert reponse.status_code == 200, reponse.text
    assert not _existe_encore("vrai-signup-a-supprimer@example.test")


def test_suppression_d_un_admin_active_directement_a_la_confirmation_est_aussi_refusee(admin_session, monkeypatch) -> None:  # noqa: F811
    """Un deuxième compte `ADMIN_EMAILS` bascule `active` dès la
    confirmation d'email (`mark_email_confirmed`, sans jamais passer par
    `PATCH /admin/users`) — `activated_at` est bien posé sur ce chemin-là
    aussi, la suppression doit donc être refusée comme pour tout compte
    activé par la voie normale."""
    token = _signup_et_extraire_token(monkeypatch, AUTRE_ADMIN_EMAIL)
    _confirmer(token)
    deuxieme_admin_id = _id_utilisateur(AUTRE_ADMIN_EMAIL)

    reponse = client.delete(f"/admin/users/{deuxieme_admin_id}")
    assert 400 <= reponse.status_code < 500, reponse.text
    assert _existe_encore(AUTRE_ADMIN_EMAIL)
