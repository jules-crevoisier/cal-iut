"""Flux .ics : fuseau horaire et détection des mises à jour.

Retour de David Annebicque, 29/08/2026 : « tu as un offset de 2 heures dans
ton export ical en URL. Pense à générer une clé unique pour chaque événement,
et qui change à chaque modif, sinon Google Calendar ne voit pas toujours la
mise à jour. En fait c'est ton UTC qui n'est pas configuré. »

Deux problèmes distincts, et le second se traite autrement qu'énoncé.

**Le fuseau.** `DTSTART:20260916T080000`, sans suffixe ni `TZID`, est une
heure FLOTTANTE au sens de la RFC 5545 : chaque client l'interprète à sa
façon, et Google la lit comme de l'UTC — d'où les 2 heures d'écart en été.

Le correctif ne peut PAS être « ajouter 2 heures » ni « convertir en UTC avec
un décalage fixe » : le planning va de septembre à mars et traverse DEUX
changements d'heure (25/10/2026 et 28/03/2027). Un décalage figé serait juste
la moitié de l'année. D'où un vrai composant VTIMEZONE Europe/Paris et des
dates en `TZID` — c'est le fuseau qui porte la règle de bascule, pas nous.

**La mise à jour.** Pris au pied de la lettre, « une clé unique qui change à
chaque modif » produirait l'inverse de l'effet voulu : un UID différent, pour
un agenda, c'est un ÉVÉNEMENT différent — l'ancien resterait en place et le
nouveau s'ajouterait à côté. Ce qui signale une modification en iCalendar,
c'est `SEQUENCE` (entier croissant) et `LAST-MODIFIED`, à UID CONSTANT.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from cal_iut.api.ics_feed import IcsItem, build_ics


def _item(date="2026-09-16", debut="08:00", fin="09:30", sid="WR104-S1-CM-2", maj=None) -> IcsItem:
    return IcsItem(
        session_id=sid, course_code="WR104", course_name="Culture numérique",
        date=date, time_start=debut, time_end=fin, room_label="H.018",
        group_ids=["but1-promo"], teacher_codes=["MMA"], updated_at=maj,
    )


def _construire(items) -> str:
    return build_ics(items, "Martial Martin", "prof-MMA", {"but1-promo": "Promo BUT1"}, {"MMA": "Martial Martin"})


# --------------------------------------------------------------------------
# Le fuseau horaire
# --------------------------------------------------------------------------


def test_le_flux_declare_le_fuseau_de_paris() -> None:
    ics = _construire([_item()])
    assert "BEGIN:VTIMEZONE" in ics
    assert "TZID:Europe/Paris" in ics
    assert "END:VTIMEZONE" in ics


def test_les_horaires_sont_rattaches_au_fuseau_et_non_flottants() -> None:
    """LE test du bug : sans `TZID`, Google lit l'heure comme de l'UTC."""
    ics = _construire([_item()])
    assert "DTSTART;TZID=Europe/Paris:20260916T080000" in ics
    assert "DTEND;TZID=Europe/Paris:20260916T093000" in ics
    assert "DTSTART:2026" not in ics, "plus aucune date flottante"


def test_le_fuseau_porte_les_deux_bascules_heure_ete_hiver() -> None:
    """Le planning va de septembre à mars : un décalage figé serait faux la
    moitié de l'année."""
    ics = _construire([_item()])
    assert "BEGIN:DAYLIGHT" in ics and "BEGIN:STANDARD" in ics
    assert "TZOFFSETTO:+0200" in ics  # heure d'été
    assert "TZOFFSETTO:+0100" in ics  # heure d'hiver
    # Règles de bascule européennes : dernier dimanche de mars et d'octobre.
    assert "BYDAY=-1SU;BYMONTH=3" in ics
    assert "BYDAY=-1SU;BYMONTH=10" in ics


def test_une_seance_d_hiver_garde_la_meme_ecriture() -> None:
    """L'heure écrite reste l'heure locale affichée ; c'est le VTIMEZONE qui
    dit quel décalage appliquer selon la date. Rien à calculer nous-mêmes."""
    ics = _construire([_item(date="2026-12-16")])
    assert "DTSTART;TZID=Europe/Paris:20261216T080000" in ics


# --------------------------------------------------------------------------
# La détection des mises à jour
# --------------------------------------------------------------------------


def test_l_uid_reste_stable_quand_la_seance_se_deplace() -> None:
    """Un UID qui changerait ferait AJOUTER un événement au lieu de mettre à
    jour l'existant — l'inverse de l'effet recherché."""
    avant = _construire([_item(date="2026-09-16", debut="08:00")])
    apres = _construire([_item(date="2026-11-11", debut="14:00")])
    uid = re.search(r"UID:(.+)", avant).group(1)
    assert uid in apres


def test_une_modification_incremente_SEQUENCE() -> None:
    """C'est `SEQUENCE`, pas l'UID, qui dit à un agenda « cet événement a
    changé »."""
    ancien = _construire([_item(maj=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc))])
    recent = _construire([_item(maj=datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc))])
    seq_ancien = int(re.search(r"SEQUENCE:(\d+)", ancien).group(1))
    seq_recent = int(re.search(r"SEQUENCE:(\d+)", recent).group(1))
    assert seq_recent > seq_ancien


def test_la_date_de_modification_est_publiee() -> None:
    ics = _construire([_item(maj=datetime(2026, 8, 29, 18, 30, tzinfo=timezone.utc))])
    assert "LAST-MODIFIED:20260829T183000Z" in ics


def test_sans_date_de_modification_la_sequence_vaut_zero() -> None:
    """Une séance jamais modifiée n'a pas à porter un numéro de révision."""
    ics = _construire([_item(maj=None)])
    assert "SEQUENCE:0" in ics


def test_deux_seances_ont_des_uid_differents() -> None:
    ics = _construire([_item(sid="a"), _item(sid="b", debut="09:30", fin="11:00")])
    uids = re.findall(r"UID:(.+)", ics)
    assert len(uids) == 2 and len(set(uids)) == 2


# --------------------------------------------------------------------------
# Ce qui ne doit pas avoir changé
# --------------------------------------------------------------------------


def test_le_flux_reste_un_calendrier_valide() -> None:
    ics = _construire([_item()])
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") == 1
    # Les lignes iCalendar se terminent par CRLF (RFC 5545 §3.1).
    assert "\r\n" in ics


def test_une_seance_sans_date_est_ignoree() -> None:
    assert "BEGIN:VEVENT" not in _construire([_item(date="")])


def test_le_contenu_metier_est_conserve() -> None:
    ics = _construire([_item()])
    assert "SUMMARY:WR104 — Promo BUT1" in ics
    assert "LOCATION:H.018" in ics
    assert "Martial Martin" in ics
