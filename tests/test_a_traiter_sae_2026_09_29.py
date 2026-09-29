"""« À traiter » : cours de SAE placés hors journée SAE (29/09/2026, « go »).

Règle de `/api/v1/sae` : un cours de SAE n'a lieu que sur une journée SAE de
son parcours ; hors journée, c'est une exception déclarée
(`solver_scheduled_sae`, ex. WSA501D) ou une anomalie. Ce que ces tests
protègent :

- `/api/v1/a-traiter` liste EXACTEMENT les anomalies de `/api/v1/sae` — même
  fonction (`v1._saes`), jamais une deuxième implémentation ;
- les exceptions déclarées n'y figurent pas (décision déjà prise, visible
  avec son motif dans `/api/v1/sae`) ;
- le point a la même forme que celui de l'écran (`todo.ts::pointsDepuisSae`,
  même fixture dans `utils/todo.sae.test.ts`).
"""

from __future__ import annotations

from test_api_v1_revision_2026_09_29 import client, etat  # noqa: F401 — fixtures partagées
from test_api_v1_sae_2026_09_29 import sae  # noqa: F401

from cal_iut.api import v1_vues

# Même fixture que `frontend/src/utils/todo.sae.test.ts`.
ANOMALIE = {
    "id": "ws-hors", "cours_code": "WS101", "cours_nom": "SAE WS101", "type": "TD", "parcours": "BUT1",
    "groupes": ["but1-td-ab"], "groupes_libelles": ["TD AB"], "enseignants": ["KBR"],
    "semaine": 7, "jour": 0, "creneau": 0,
}


def test_a_traiter_reprend_exactement_les_anomalies_de_l_api_sae(client, sae) -> None:  # noqa: F811
    anomalies = client.get("/api/v1/sae").json()["anomalies"]
    assert [a["id"] for a in anomalies] == ["ws-hors"]
    corps = client.get("/api/v1/a-traiter?nature=sae-hors-journee").json()
    points = corps["points"]
    assert [p["seance_id"] for p in points] == [a["id"] for a in anomalies]
    assert points[0]["gravite"] == "a_corriger"
    assert (points[0]["semaine"], points[0]["jour"]) == (sae, 0)
    nature = next(n for n in corps["natures"] if n["id"] == "sae-hors-journee")
    assert nature["nombre"] == 1 and nature["titre"] == "Cours de SAE hors journée SAE"


def test_les_exceptions_declarees_n_y_figurent_pas(client, sae) -> None:  # noqa: F811
    tous = client.get("/api/v1/a-traiter").json()["points"]
    ids = {p.get("seance_id") for p in tous if p["nature"] == "sae-hors-journee"}
    assert "wsa-solveur" not in ids, "WSA501D : exception déclarée (solver_scheduled_sae)"
    assert "ws-dans" not in ids, "dans sa journée SAE : rien à signaler"


def test_forme_du_point_comme_le_frontend() -> None:
    assert v1_vues.points_depuis_sae({}, [ANOMALIE]) == [{
        "nature": "sae-hors-journee", "gravite": "a_corriger", "cle": "sae-hj|ws-hors",
        "titre": "WS101 — SAE WS101", "detail": "TD · TD AB · hors journée SAE",
        "semaine": 7, "jour": 0, "creneau": 0, "parcours": ["BUT1"], "enseignants": ["KBR"],
        "nombre": 1, "seance_id": "ws-hors",
    }]
