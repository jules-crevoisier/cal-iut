"""Le lissage d'une promo n'est plus dans l'interface (demande utilisateur du
29/09/2026 : « trop dangereux ») : il reste en ligne de commande
(`cal-iut lisser`) et par l'API, réservé aux administrateurs. Un compte
« édition » ne peut ni lancer un calcul, ni lire une proposition, ni
l'appliquer."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cal_iut.api.main import app
from conftest import creer_compte_actif_et_connecter


def test_un_compte_edition_ne_peut_pas_lisser(db_isole) -> None:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    assert client.post("/placements/lissage", json={"parcours": "BUT3-DEV-FC"}).status_code == 403
    assert client.get("/placements/lissage/inconnu").status_code == 403
    assert client.post("/placements/lissage/inconnu/appliquer", json={"exclure": []}).status_code == 403


def test_un_administrateur_garde_l_acces_au_lissage(db_isole) -> None:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    # Tâche inconnue : 404, pas 403 — la route reste ouverte à l'admin.
    assert client.get("/placements/lissage/inconnu").status_code == 404
