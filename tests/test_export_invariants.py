"""Invariants de l'export — le fichier que reçoivent réellement les gens.

Trois défauts trouvés le 26/08/2026 en explorant ce module, tous invisibles
depuis le code mais immédiats pour qui ouvre le fichier :

1. **Aucune date.** L'export ne portait qu'un numéro de semaine interne. Pour
   savoir quand avait lieu un cours, il fallait refaire la conversion à la main.
2. **Un numéro de semaine faux.** `week = index + 1` donnait « semaine 1 » là
   où l'interface affiche « Semaine 2 » : deux exports du même planning se
   contredisaient d'une semaine.
3. **Un tri alphabétique sur les jours.** « Jeudi » sortait avant « Lundi »,
   rendant le CSV illisible dans un tableur.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cal_iut.calendar.academic import build_default_calendar_2026_2027, department_week_number
from cal_iut.export.formatter import DAY_LABELS, build_export_rows, to_csv, to_json
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.cpsat import PlacedSession

CAL = build_default_calendar_2026_2027()
_reglage = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def placements_tires_au_sort(draw, max_n=8):
    n = draw(st.integers(min_value=1, max_value=max_n))
    placements, sessions = [], {}
    for i in range(n):
        sid = f"s{i}"
        p = PlacedSession(
            session_id=sid,
            week=draw(st.integers(min_value=0, max_value=min(20, len(CAL.teaching_mondays) - 1))),
            day=draw(st.integers(min_value=0, max_value=DAYS_PER_WEEK - 1)),
            slot=draw(st.integers(min_value=0, max_value=SLOTS_PER_DAY - 1)),
            course_code=draw(st.sampled_from(["WR101", "WR110", "WRA505C"])),
            group_ids=["but1-td-ab"], teacher_codes=["MRI"],
        )
        placements.append(p)
        sessions[sid] = SessionToPlace(
            id=sid, course_code=p.course_code, course_name="Test", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
            sequence_order=i + 1, group_ids=p.group_ids, teacher_codes=p.teacher_codes,
        )
    return placements, sessions


@given(placements_tires_au_sort())
@_reglage
def test_chaque_ligne_porte_une_date_reelle(donnees):
    """Sans date, l'export n'est pas exploitable par un humain."""
    placements, sessions = donnees
    for row in build_export_rows(placements, sessions, CAL, 0):
        assert row.date, f"{row.session_id} sans date"
        date.fromisoformat(row.date)  # lève si le format est invalide


@given(placements_tires_au_sort())
@_reglage
def test_la_date_correspond_au_jour_annonce(donnees):
    """« Mardi » dans la colonne jour doit bien être un mardi dans la colonne date."""
    placements, sessions = donnees
    for row in build_export_rows(placements, sessions, CAL, 0):
        reelle = date.fromisoformat(row.date)
        assert DAY_LABELS[reelle.weekday()] == row.day, (
            f"{row.date} est un {DAY_LABELS[reelle.weekday()]}, l'export dit {row.day}"
        )


@given(placements_tires_au_sort())
@_reglage
def test_le_numero_de_semaine_est_celui_affiche_dans_l_interface(donnees):
    """La même séance doit porter le même numéro de semaine partout."""
    placements, sessions = donnees
    for row in build_export_rows(placements, sessions, CAL, 0):
        attendu = department_week_number(CAL.teaching_mondays[row.semaine_solveur])
        assert row.week == attendu, (
            f"export : semaine {row.week}, interface : {attendu}"
        )


@given(placements_tires_au_sort())
@_reglage
def test_les_lignes_sortent_dans_l_ordre_chronologique(donnees):
    """Un CSV trié sur le LIBELLÉ du jour range « Jeudi » avant « Lundi »."""
    placements, sessions = donnees
    rows = build_export_rows(placements, sessions, CAL, 0)
    cles = [(r.date, r.time_start) for r in rows]
    assert cles == sorted(cles), f"ordre non chronologique : {cles}"


@given(placements_tires_au_sort())
@_reglage
def test_l_export_ne_perd_ni_ne_duplique_aucune_seance(donnees):
    placements, sessions = donnees
    rows = build_export_rows(placements, sessions, CAL, 0)
    assert len(rows) == len(placements)
    assert {r.session_id for r in rows} == {p.session_id for p in placements}


@given(placements_tires_au_sort())
@_reglage
def test_le_csv_se_relit_avec_toutes_ses_colonnes(donnees):
    """Un CSV qu'un tableur ne saurait pas relire ne sert à rien."""
    placements, sessions = donnees
    rows = build_export_rows(placements, sessions, CAL, 0)
    texte = to_csv(rows)
    relu = list(csv.DictReader(io.StringIO(texte)))
    assert len(relu) == len(rows)
    for original, ligne in zip(rows, relu):
        assert ligne["session_id"] == original.session_id
        assert ligne["date"] == original.date


@given(placements_tires_au_sort())
@_reglage
def test_json_et_csv_portent_exactement_les_memes_donnees(donnees):
    placements, sessions = donnees
    rows = build_export_rows(placements, sessions, CAL, 0)
    depuis_json = to_json(rows)
    depuis_csv = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert len(depuis_json) == len(depuis_csv)
    for a, b in zip(depuis_json, depuis_csv):
        assert str(a["session_id"]) == b["session_id"]
        assert str(a["week"]) == b["week"]


@given(placements_tires_au_sort())
@_reglage
def test_les_horaires_correspondent_au_creneau(donnees):
    placements, sessions = donnees
    horaires = {
        0: ("08:00", "09:30"), 1: ("09:30", "11:00"), 2: ("11:00", "12:30"),
        3: ("14:00", "15:30"), 4: ("15:30", "17:00"), 5: ("17:00", "18:30"),
    }
    par_id = {p.session_id: p for p in placements}
    for row in build_export_rows(placements, sessions, CAL, 0):
        attendu = horaires[par_id[row.session_id].slot]
        assert (row.time_start, row.time_end) == attendu


def test_un_export_sans_calendrier_laisse_la_date_vide_plutot_que_fausse():
    """Mieux vaut une colonne vide qu'une date inventée.

    Les appelants historiques n'ont pas de calendrier sous la main ; l'export
    doit rester possible, mais sans jamais afficher une date qu'il ne connaît
    pas.
    """
    p = PlacedSession(
        session_id="s", week=3, day=1, slot=0, course_code="WR101",
        group_ids=["g"], teacher_codes=["T"],
    )
    session = SessionToPlace(
        id="s", course_code="WR101", course_name="T", semestre="S1", parcours="BUT1",
        annee="BUT1", session_type=SessionType.TD, group_ids=["g"], teacher_codes=["T"],
    )
    row = build_export_rows([p], {"s": session})[0]
    assert row.date == ""
    assert row.semaine_solveur == 3
