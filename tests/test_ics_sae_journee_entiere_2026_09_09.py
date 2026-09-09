"""Une fenêtre SAE doit être une JOURNÉE ENTIÈRE, y compris chez Outlook.

Signalement de Jules Crevoisier, 09/09/2026, capture d'un agenda abonné :

    Détails du cours
    Semaine de projet/évaluation SAE — WS101
    Date     mardi 20 octobre 2026
    Horaire  00h00 - 00h00

L'évènement était pourtant conforme à la RFC 5545 :

    DTSTART;VALUE=DATE:20261020
    DTEND;VALUE=DATE:20261024

`VALUE=DATE` suffit à Google et à Apple. Outlook, lui, ne déduit pas
« journée entière » de la seule absence d'heure : il rend la fenêtre comme
un rendez-vous à minuit, d'où le « 00h00 - 00h00 ». Les deux champs
propriétaires `X-MICROSOFT-CDO-ALLDAYEVENT` et `X-MICROSOFT-CDO-BUSYSTATUS`
sont ce qu'il attend ; les autres agendas les ignorent.

ET UN SECOND DÉFAUT, TROUVÉ EN REGARDANT CELUI-LÀ. Les fenêtres SAE
n'émettaient aucun `SEQUENCE`. Un agenda déjà abonné ne remplace un
évènement que si ce numéro augmente : déplacer ou raccourcir une fenêtre ne
se voyait donc JAMAIS chez ceux qui l'avaient déjà reçue. C'est exactement
le défaut corrigé le 29/08/2026 sur les séances — signalé par David
Annebicque, « ça n'a pas bougé dans mon agenda » — resté sur cette
branche-ci parce qu'elle a été écrite après.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cal_iut.api.ics_feed import IcsAllDayItem, build_ics


def _fenetre(**kw) -> IcsAllDayItem:
    base = {
        "key": "WS101-2026-10-20",
        "title": "SAE WS101",
        "date_start": "2026-10-20",
        "date_end": "2026-10-23",
        "description": "Semaine de projet/évaluation SAE — WS101",
    }
    base.update(kw)
    return IcsAllDayItem(**base)


def _ics(*fenetres: IcsAllDayItem) -> str:
    return build_ics(
        items=[],
        calendar_name="TP C",
        uid_prefix="groupe-but1-tp-c",
        group_labels={},
        teacher_labels={},
        all_day_items=list(fenetres),
    )


def _bloc(ics: str) -> list[str]:
    lignes = ics.split("\r\n")
    debut = lignes.index("BEGIN:VEVENT")
    return lignes[debut : lignes.index("END:VEVENT", debut) + 1]


# --------------------------------------------------------------------------


def test_outlook_reconnait_la_journee_entiere() -> None:
    """LE symptôme : « Horaire 00h00 - 00h00 »."""
    bloc = _bloc(_ics(_fenetre()))

    assert "X-MICROSOFT-CDO-ALLDAYEVENT:TRUE" in bloc, bloc


def test_la_fenetre_n_occupe_pas_le_temps_de_qui_la_recoit() -> None:
    """`TRANSP:TRANSPARENT` le dit aux agendas standards, `BUSYSTATUS:FREE`
    à Outlook. Une semaine de projet n'est pas un rendez-vous : la marquer
    occupée rendrait ses cinq jours indisponibles dans les vues de
    disponibilité."""
    bloc = _bloc(_ics(_fenetre()))

    assert "TRANSP:TRANSPARENT" in bloc
    assert "X-MICROSOFT-CDO-BUSYSTATUS:FREE" in bloc


def test_les_dates_restent_conformes_a_la_rfc() -> None:
    """Non-régression : les champs propriétaires s'AJOUTENT, ils ne
    remplacent pas. `DTEND` reste exclusif — le lendemain du dernier jour."""
    bloc = _bloc(_ics(_fenetre()))

    assert "DTSTART;VALUE=DATE:20261020" in bloc
    assert "DTEND;VALUE=DATE:20261024" in bloc, "23 octobre inclus -> 24 exclusif"
    assert not any(ligne.startswith("DTSTART;TZID") for ligne in bloc), (
        "une journée entière ne porte pas de fuseau"
    )


# --------------------------------------------------------------------------
# Le second défaut : une fenêtre qui bouge doit se voir
# --------------------------------------------------------------------------


def test_une_fenetre_porte_un_numero_de_sequence() -> None:
    bloc = _bloc(_ics(_fenetre()))

    assert any(ligne.startswith("SEQUENCE:") for ligne in bloc), bloc


def test_une_fenetre_modifiee_a_une_sequence_plus_haute() -> None:
    """C'EST TOUT L'ENJEU. Sans progression du numéro, un agenda déjà abonné
    garde la première version : la fenêtre déplacée reste affichée à son
    ancienne date, sans que personne ne le voie."""

    def _seq(ics: str) -> int:
        return next(
            int(ligne.split(":", 1)[1])
            for ligne in _bloc(ics)
            if ligne.startswith("SEQUENCE:")
        )

    avant = _seq(_ics(_fenetre(updated_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC))))
    apres = _seq(_ics(_fenetre(updated_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC))))

    assert apres > avant, f"{apres} doit dépasser {avant}"


def test_une_fenetre_inchangee_garde_sa_sequence() -> None:
    """L'inverse compte autant : une séquence qui bouge sans raison ferait
    re-notifier tous les abonnés à chaque rafraîchissement."""
    horodatage = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    assert _bloc(_ics(_fenetre(updated_at=horodatage))) == _bloc(
        _ics(_fenetre(updated_at=horodatage))
    )


def test_l_uid_ne_change_pas_avec_les_dates() -> None:
    """Même raison que pour les séances : un UID qui varie AJOUTE un
    évènement au lieu de remplacer celui qui existe, et l'ancien reste
    affiché à côté du nouveau."""
    bloc = _bloc(_ics(_fenetre(date_start="2026-10-26", date_end="2026-10-29")))

    assert "UID:groupe-but1-tp-c-sae-WS101-2026-10-20@cal-iut" in bloc
