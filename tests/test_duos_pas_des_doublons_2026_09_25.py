"""Un duo synchronisé dans deux demi-salles n'est pas un doublon.

Kyllian Bresson (25/09/2026) : « pour H.201 et H.203, c'est en soi la même
salle, donc il ne faut pas deux MODULES DIFFÉRENTS en même temps dans ces deux
salles ». Le duo synchronisé, lui, met le MÊME module dans les deux moitiés,
un enseignant par moitié — c'est voulu (`teacher_duos.yaml`).

Mesuré sur la production le 25/09/2026 : 69 des 180 doublons relevés étaient
ces duos. Sans cette exception, le vrai signal se noie.
"""

from __future__ import annotations

from types import SimpleNamespace

from cal_iut.api.doublons import _duo_dans_deux_moities


def _p(session_id: str, room_id: str, course_code: str):
    return SimpleNamespace(session_id=session_id, room_id=room_id, course_code=course_code)


def test_meme_module_dans_les_deux_moities_nest_pas_un_doublon() -> None:
    assert _duo_dans_deux_moities([_p("a", "h007", "WR112"), _p("b", "h008", "WR112")])


def test_deux_modules_differents_dans_les_deux_moities_reste_un_doublon() -> None:
    assert not _duo_dans_deux_moities([_p("a", "h201", "WR314D"), _p("b", "h203", "WR316D")])


def test_la_meme_salle_deux_fois_reste_un_doublon_meme_pour_un_seul_module() -> None:
    """Deux groupes ne tiennent pas dans la même pièce."""
    assert not _duo_dans_deux_moities([_p("a", "h101", "WR115"), _p("b", "h101", "WR115")])


def test_trois_seances_dont_un_intrus_reste_un_doublon() -> None:
    assert not _duo_dans_deux_moities(
        [_p("a", "h201", "WR112"), _p("b", "h203", "WR112"), _p("c", "h201_h203", "WR308D")]
    )
