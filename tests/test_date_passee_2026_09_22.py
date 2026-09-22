"""Date passée : « tout forçable avec popup forte ».

To-do : « ne pas pouvoir déplacer ou créer de séances sur des dates passées
ou alors vraiment une popup pour le forcer ». Décision de Jules (propriétaire)
le 22/09/2026 : TOUT reste forçable — mais toucher une date déjà écoulée doit
déclencher un conflit FORÇABLE dédié (`Date passée : ...`), distinct du
verrou de semaine existant (`Semaine N non modifiable`, cf.
`test_forcer_semaine_en_cours_2026_09_21.py`, qui doit rester vert SANS
modification).

Le fixture partagé (`test_placement_manuel.client`) place « placee » à la
semaine 10 (index solveur = index relatif S1, cf. `semester_week_offset`),
loin dans le futur du CALENDRIER RÉEL (`date.today()`) — le verrou de semaine
existant (`week_status`, qui lit `date.today()` directement, jamais
`main._today`) n'y déclenche donc JAMAIS. En gelant `main._today` sur une
date postérieure à la semaine 10, on isole complètement le nouveau contrôle
« Date passée » de l'ancien verrou de semaine — c'est le seul moyen de
tester les deux indépendamment sans dupliquer le calendrier de test.
"""

from __future__ import annotations

from datetime import date

import pytest
from test_maquette_session_patch import _cours  # type: ignore[import-not-found]
from test_placement_manuel import _place, _seance, client  # noqa: F401 — fixture réutilisée

from cal_iut.api import main
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import semester_week_offset

SEMAINE = 10  # cf. test_placement_manuel : "placee" y est déjà, loin dans le futur réel.


def _conflit_structure(reponse) -> dict:
    assert reponse.status_code == 409, reponse.text
    detail = reponse.json().get("detail")
    assert isinstance(detail, dict), f"le refus doit être structuré : {detail!r}"
    return detail


def _date_du_creneau(week: int, day: int) -> date:
    """Même calcul que `main._dates_passees_motifs`, pour construire les
    assertions sans dupliquer la logique testée — la valeur ATTENDUE, pas la
    logique elle-même."""
    etat = get_state()
    offset = semester_week_offset(etat.calendar, "S1")
    d = etat.calendar.week_day_to_date(offset + week, day)
    assert d is not None
    return d


def _gel(monkeypatch, apres: date) -> None:
    """Gèle `main._today()` — jamais `date.today()` système, ni `week_status`
    (qui continue de lire l'horloge réelle, cf. docstring du module)."""
    monkeypatch.setattr(main, "_today", lambda: apres)


@pytest.fixture
def apres_semaine_10(monkeypatch) -> date:
    """Date gelée strictement après le lundi de la semaine 10 — assez loin
    pour que TOUS les jours de cette semaine soient déjà « passés » du point
    de vue du contrôle « Date passée »."""
    lundi = _date_du_creneau(SEMAINE, 0)
    gelee = date(lundi.year, lundi.month, lundi.day)
    from datetime import timedelta

    gelee = gelee + timedelta(days=10)
    _gel(monkeypatch, gelee)
    return gelee


# --------------------------------------------------------------------------
# Créer une séance sur une date déjà écoulée
# --------------------------------------------------------------------------


def test_creer_sur_une_date_passee_est_forcable(client, apres_semaine_10) -> None:  # noqa: F811
    get_state().courses = [_cours()]
    corps = {
        "course_code": "WR101", "session_type": "TD", "group_ids": ["but1-td-ab"],
        "teacher_codes": ["MRI"], "week": SEMAINE, "day": 2, "slot": 3,
    }
    detail = _conflit_structure(client.post("/placements/personnalisees", json=corps))
    date_cible = _date_du_creneau(SEMAINE, 2)
    attendu = f"Date passée : le {['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi'][2]} {date_cible.strftime('%d/%m/%Y')} est déjà écoulé."
    assert attendu in detail["hard_conflicts"], detail
    assert not detail.get("blocking_conflicts"), "forçable : jamais bloquant"
    # Isolation de l'ancien verrou : la semaine 10 est FUTURE pour l'horloge
    # réelle (`week_status`), donc AUCUN motif « non modifiable » ici.
    assert not any("non modifiable" in m for m in detail["hard_conflicts"]), detail


def test_creer_en_forcant_passe_malgre_la_date_passee(client, apres_semaine_10) -> None:  # noqa: F811
    get_state().courses = [_cours()]
    corps = {
        "course_code": "WR101", "session_type": "TD", "group_ids": ["but1-td-ab"],
        "teacher_codes": ["MRI"], "week": SEMAINE, "day": 2, "slot": 3, "force": True,
    }
    assert client.post("/placements/personnalisees", json=corps).status_code == 200


def test_placer_sur_une_date_passee_est_forcable(client, apres_semaine_10) -> None:  # noqa: F811
    reponse = client.post("/placements/manquante/placer", json={"week": SEMAINE, "day": 3, "slot": 1})
    detail = _conflit_structure(reponse)
    assert any(m.startswith("Date passée : le ") and m.endswith("est déjà écoulé.") for m in detail["hard_conflicts"]), detail


# --------------------------------------------------------------------------
# Déplacer une séance
# --------------------------------------------------------------------------


def test_deplacer_dans_le_meme_jour_ne_produit_qu_un_seul_motif(client, apres_semaine_10) -> None:  # noqa: F811
    """Source ET destination retombent sur la MÊME date (même semaine, même
    jour, slot différent) : un seul motif — celui de la source — jamais les
    deux libellés pour une date identique."""
    reponse = client.patch("/placements/placee", json={"week": SEMAINE, "day": 0, "slot": 4})
    detail = _conflit_structure(reponse)
    motifs_date = [m for m in detail["hard_conflicts"] if m.startswith("Date passée : ")]
    assert motifs_date == ["Date passée : cette séance a déjà eu lieu (lundi " + _date_du_creneau(SEMAINE, 0).strftime("%d/%m/%Y") + ")."]


def test_deplacer_vers_un_autre_jour_passe_produit_les_deux_motifs(client, apres_semaine_10) -> None:  # noqa: F811
    """Source ET destination sont deux dates PASSÉES distinctes : les deux
    motifs apparaissent, chacun avec son libellé propre."""
    reponse = client.patch("/placements/placee", json={"week": SEMAINE, "day": 1, "slot": 0})
    detail = _conflit_structure(reponse)
    source = _date_du_creneau(SEMAINE, 0).strftime("%d/%m/%Y")
    dest = _date_du_creneau(SEMAINE, 1).strftime("%d/%m/%Y")
    assert f"Date passée : cette séance a déjà eu lieu (lundi {source})." in detail["hard_conflicts"]
    assert f"Date passée : le mardi {dest} est déjà écoulé." in detail["hard_conflicts"]


def test_deplacer_vers_une_date_future_reelle_ne_declenche_rien(client) -> None:  # noqa: F811
    """Sans geler `main._today` (donc `date.today()` réel, bien avant la
    semaine 10) : aucun motif « Date passée »."""
    reponse = client.patch("/placements/placee", json={"week": SEMAINE, "day": 1, "slot": 0})
    assert reponse.status_code == 200, reponse.text


def test_forcer_leve_le_verrou_de_date_passee(client, apres_semaine_10) -> None:  # noqa: F811
    reponse = client.patch("/placements/placee", json={"week": SEMAINE, "day": 1, "slot": 0, "force": True})
    assert reponse.status_code == 200, reponse.text


# --------------------------------------------------------------------------
# La vérification à blanc (validate_placement) : RENDU, jamais levé
# --------------------------------------------------------------------------


def test_validate_placement_rend_le_motif_sans_lever(client, apres_semaine_10) -> None:  # noqa: F811
    reponse = client.post("/placements/placee/validate", json={"week": SEMAINE, "day": 1, "slot": 0})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["valid"] is False
    assert any(m.startswith("Date passée : ") for m in corps["hard_conflicts"]), corps
    assert not corps["blocking_conflicts"]


# --------------------------------------------------------------------------
# Patch SANS déplacement (maquette ET personnalisée) — volontairement HORS
# du contrôle « Date passée ». Le contrat ne l'exige que sur les chemins
# d'écriture qui passent DÉJÀ par un verrou de semaine ; `_controler_placement`
# (`api/session_patch.py`) n'en a jamais eu (gap pré-existant, hors périmètre
# de ce contrat), et `test_modifier_seance_creee_2026_09_22.py::
# test_changer_l_enseignant_sur_la_semaine_en_cours_passe_sans_forcer` fixe
# déjà ce comportement : changer l'enseignant SANS déplacer doit passer sans
# forcer, semaine en cours ou passée. Ces deux tests verrouillent l'absence
# volontaire du contrôle ici, pour qu'il ne revienne pas par erreur.
# --------------------------------------------------------------------------


def test_patch_maquette_sans_deplacement_ignore_la_date_passee(client, apres_semaine_10) -> None:  # noqa: F811
    reponse = client.patch("/placements/placee/seance", json={"duration_slots": 1, "teacher_codes": ["MRI"]})
    assert reponse.status_code == 200, reponse.text


def test_patch_personnalisee_sans_deplacement_ignore_la_date_passee(client, apres_semaine_10) -> None:  # noqa: F811
    etat = get_state()
    perso = _seance("perso")
    perso.metadata["custom_session"] = True
    etat.sessions.append(perso)
    etat.sessions_by_id[perso.id] = perso
    etat.timetable.append(_place(perso, SEMAINE, 4, 5))

    reponse = client.patch(f"/placements/personnalisees/{perso.id}", json={"teacher_codes": ["MRI"]})
    assert reponse.status_code == 200, reponse.text


# --------------------------------------------------------------------------
# Échange de deux séances
# --------------------------------------------------------------------------


def test_echanger_deux_seances_sur_des_dates_passees_produit_les_deux_motifs(client, apres_semaine_10) -> None:  # noqa: F811
    etat = get_state()
    autre = _seance("autre")
    etat.sessions.append(autre)
    etat.sessions_by_id[autre.id] = autre
    etat.timetable.append(_place(autre, SEMAINE, 2, 0))

    reponse = client.post("/placements/echanger", json={"session_a": "placee", "session_b": "autre"})
    detail = _conflit_structure(reponse)
    assert any(m.startswith("Date passée : ") for m in detail["hard_conflicts"]), detail
    # Rien n'a bougé : l'échange refusé est intégralement annulé.
    assert next(p for p in etat.timetable if p.session_id == "placee").day == 0
    assert next(p for p in etat.timetable if p.session_id == "autre").day == 2


def test_echanger_en_forcant_passe_malgre_les_dates_passees(client, apres_semaine_10) -> None:  # noqa: F811
    etat = get_state()
    autre = _seance("autre")
    etat.sessions.append(autre)
    etat.sessions_by_id[autre.id] = autre
    etat.timetable.append(_place(autre, SEMAINE, 2, 0))

    reponse = client.post("/placements/echanger", json={"session_a": "placee", "session_b": "autre", "force": True})
    assert reponse.status_code == 200, reponse.text
