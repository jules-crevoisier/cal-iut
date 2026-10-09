"""Modifier un évènement déjà créé — tâche 16 (Kyllian Bresson, 07/10/2026) :
« Il faut permettre de rouvrir et modifier un évènement existant directement
depuis l'outil, avec les mêmes informations/champs que lors de sa création
[...] sans devoir le supprimer puis en créer un nouveau. »

Libellé et semestre étaient figés à la création, et rien ne permettait de
retirer un horaire libre une fois posé. Le reste (groupes, enseignants,
note, position, horaire) passait déjà par `PATCH /placements/personnalisees`.
"""

from __future__ import annotations

from test_evenement_horaire_libre_2026_09_23 import SEMAINE, _corps, _place, _seance, monter  # noqa: F401

from cal_iut.api.state import get_state


def _creer(client, **over) -> dict:
    r = client.post("/placements/evenements", json=_corps(**over))
    assert r.status_code == 200, r.text
    return r.json()


def test_libelle_et_semestre_modifiables_sans_changer_l_id(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    cree = _creer(client, day=1, slot=1)
    sid = cree["session_id"]

    r = client.patch(f"/placements/personnalisees/{sid}", json={"libelle": "Réunion de rentrée", "semestre": "S3"})
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == sid
    assert r.json()["course_code"] == "REUNION-DE-RENTREE"
    assert r.json()["course_name"] == "Réunion de rentrée"
    seance = get_state().sessions_by_id[sid]
    assert seance.semestre == "S3"
    assert seance.metadata.get("evenement") is True
    placement = next(p for p in get_state().timetable if p.session_id == sid)
    assert placement.course_code == "REUNION-DE-RENTREE"


def test_passer_un_evenement_dans_la_pause_meridienne(monter):
    """CM 13h30-14h (exemple de la tâche) : stocké sur le créneau 3 et
    signalé `midi`, même si le formulaire envoie un autre créneau."""
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = _creer(client, day=2, slot=1)["session_id"]

    r = client.patch(
        f"/placements/personnalisees/{sid}",
        json={"week": SEMAINE, "day": 2, "slot": 1, "heure_debut": "13:30", "heure_fin": "14:00"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["slot"], r.json()["hor"], r.json()["midi"]) == (3, "13h30–14h", True)


def test_retirer_l_horaire_libre_revient_au_creneau(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = _creer(client, heure_debut="13:30", heure_fin="14:00", day=2, slot=0)["session_id"]

    r = client.patch(
        f"/placements/personnalisees/{sid}",
        json={"week": SEMAINE, "day": 2, "slot": 1, "sans_horaire": True},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["slot"], r.json()["hor"], r.json()["midi"]) == (1, None, False)
    seance = get_state().sessions_by_id[sid]
    assert "horaire" not in seance.metadata
    assert "pause_midi" not in seance.metadata


def test_libelle_refuse_sur_une_seance_qui_n_est_pas_un_evenement(monter):
    a = _seance("a")
    a.metadata["custom_session"] = True
    client = monter([(a, _place(a, 0, 0))])
    r = client.patch("/placements/personnalisees/a", json={"libelle": "Autre chose"})
    assert r.status_code == 400
    assert get_state().sessions_by_id["a"].course_name == "Cours existant"


def test_sans_horaire_et_horaire_s_excluent(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = _creer(client)["session_id"]
    r = client.patch(
        f"/placements/personnalisees/{sid}",
        json={"sans_horaire": True, "heure_debut": "13:00", "heure_fin": "14:00"},
    )
    assert r.status_code == 422


def test_payload_expose_de_quoi_rouvrir_l_evenement(monter):
    from cal_iut.export.html_view import build_payload

    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = _creer(client, heure_debut="13:30", heure_fin="14:00", note="Amphi plein")["session_id"]

    etat = get_state()
    payload = build_payload(
        {"placements": [
            {"session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
             "course_code": p.course_code, "group_ids": p.group_ids, "teacher_codes": p.teacher_codes,
             "room_id": getattr(p, "room_id", None)}
            for p in etat.timetable
        ]},
        etat.sessions,
        etat.groups,
    )
    rows = {r["id"]: r for r in payload["rows"]}
    assert rows[sid]["evt"] == {"sem": "S1", "note": "Amphi plein", "hd": "13:30", "hf": "14:00"}
    assert "evt" not in rows["a"]
