"""La révision ne doit pas avancer au milieu d'un test, au gré de l'horloge.

Signalement d'origine : CI de la PR 190 (02/10/2026),
`test_occupations_externes_2026_10_01.py::test_api_v1_occupations_externes_etag`
— « assert 200 == 304 », vert en local. La sonde « configuration »
(`api/revision.py::sonde_fichiers`) ne relit les fichiers que toutes les 5 s.
Chaque test ayant son propre dossier de configuration, la sonde gardait
l'empreinte du test PRÉCÉDENT ; quand les 5 s tombaient entre deux requêtes
d'un même test, la révision avançait, l'ETag changeait, et le 304 attendu
devenait un 200. Environ une chance sur cent par test, à chaque lancement.

Pendant les tests, la sonde relit donc à chaque appel (`conftest.py`). En
production, la temporisation reste.
"""

from cal_iut.api import revision


def test_la_sonde_de_fichiers_voit_un_changement_tout_de_suite_pendant_les_tests(tmp_path) -> None:
    a = tmp_path / "a.yaml"
    a.write_text("un", encoding="utf-8")
    fichiers = [a]
    sonde = revision.sonde_fichiers(lambda: fichiers)
    premiere = sonde()

    b = tmp_path / "b.yaml"  # le test suivant, une autre configuration
    b.write_text("deux", encoding="utf-8")
    fichiers.append(b)

    assert sonde() != premiere, "vu tout de suite, pas 5 s plus tard au milieu du test suivant"


def test_en_production_la_sonde_reste_temporisee(tmp_path) -> None:
    a = tmp_path / "a.yaml"
    a.write_text("un", encoding="utf-8")
    fichiers = [a]
    sonde = revision.sonde_fichiers(lambda: fichiers, intervalle_s=5.0)
    premiere = sonde()
    fichiers.append(tmp_path / "absent.yaml")
    (tmp_path / "b.yaml").write_text("deux", encoding="utf-8")
    fichiers.append(tmp_path / "b.yaml")

    assert sonde() == premiere, "pas de relecture avant 5 s"
