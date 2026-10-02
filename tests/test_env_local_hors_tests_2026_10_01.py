"""Les tests ne lisent jamais le `.env` du poste.

Signalement d'origine (01/10/2026, suite complète lancée sur le poste de
Jules) : `test_mail_teacher_links_2026_08_28.py::
test_previsualisation_liste_les_profs_avec_et_sans_adresse` échouait dans la
suite complète et passait seul. Cause : `test_celcat_regles_envoi_2026_10_01.
py::test_la_commande_refuse_ecrire_sur_urca_2026_avant_toute_connexion`
appelle `cli.main()`, donc `load_dotenv()`, qui remonte depuis `cli.py`
jusqu'au `.env` de la racine du dépôt. Le mot de passe Celcat, la clé API de
la production et `CAL_IUT_PUBLIC_URL` se retrouvaient dans l'environnement de
TOUS les tests suivants. La CI n'a pas de `.env` : elle ne voyait rien.

Le garde-fou est dans `conftest.py` (`_sans_env_local`).
"""

import os

from dotenv import load_dotenv

SENTINELLE = "CAL_IUT_SENTINELLE_ENV_LOCAL"


def test_load_dotenv_ne_charge_rien_pendant_les_tests(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(SENTINELLE, raising=False)
    fichier = tmp_path / ".env"
    fichier.write_text(f"{SENTINELLE}=fuite\n", encoding="utf-8")

    import dotenv

    try:
        # Les deux façons dont le code l'atteint : le nom déjà importé en tête
        # de module, et `from dotenv import load_dotenv` au moment de l'appel
        # (`cli.py`, dans chaque commande).
        load_dotenv(fichier)
        dotenv.load_dotenv(fichier)
        assert SENTINELLE not in os.environ
    finally:
        os.environ.pop(SENTINELLE, None)


def test_une_commande_cli_ne_charge_pas_le_env_du_depot(monkeypatch, capsys) -> None:
    """Le cas réel : la commande d'essai Celcat, refusée avant toute
    connexion, ne doit rien laisser dans l'environnement."""
    from cal_iut import cli

    appels: list[tuple] = []
    import dotenv

    reel = dotenv.load_dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: appels.append((a, k)) or reel(*a, **k))
    monkeypatch.setattr(
        "sys.argv", ["cal-iut", "celcat-essai-regle", "--cours", "WR100BU", "--base", "URCA_2026", "--ecrire"]
    )
    avant = dict(os.environ)
    assert cli.main() == 2
    capsys.readouterr()
    assert appels, "la commande appelle bien load_dotenv : c'est lui qu'on neutralise"
    assert dict(os.environ) == avant
