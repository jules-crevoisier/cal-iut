"""Une tâche dit QUI doit agir.

Question de Kyllian Bresson (25/09/2026) : « la liste des choses à faire, je
l'indique où sur Tâches ? le problème c'est qu'il y a des modifications qui
vous concernent et d'autres qui me concernent uniquement. »
"""

from __future__ import annotations

from test_taches_kanban_2026_09_22 import _client_edit  # type: ignore[import-not-found]


def test_une_tache_porte_qui_est_concerne(db_isole) -> None:
    client_edit = _client_edit(db_isole)
    cree = client_edit.post("/taches", json={"titre": "Mapper WSA507D", "concerne": "Jules"})
    assert cree.status_code == 200, cree.text
    assert cree.json()["concerne"] == "Jules"

    tache_id = cree.json()["id"]
    assert any(t["concerne"] == "Jules" for t in client_edit.get("/taches").json())

    maj = client_edit.patch(f"/taches/{tache_id}", json={"concerne": "Kyllian"})
    assert maj.status_code == 200, maj.text
    assert maj.json()["concerne"] == "Kyllian"


def test_une_tache_peut_ne_concerner_personne(db_isole) -> None:
    client_edit = _client_edit(db_isole)
    cree = client_edit.post("/taches", json={"titre": "À trier"})
    assert cree.json()["concerne"] is None

    tache_id = cree.json()["id"]
    client_edit.patch(f"/taches/{tache_id}", json={"concerne": "Jules"})
    # Chaîne vide = retirer l'attribution, pas « champ non fourni ».
    assert client_edit.patch(f"/taches/{tache_id}", json={"concerne": "  "}).json()["concerne"] is None
