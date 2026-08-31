"""Synchronisation local <-> production.

Aucun de ces tests ne joint la production : `Instance` est remplacée par un
faux client HTTP. C'est volontaire — un test qui parlerait vraiment au
serveur déployé pourrait, un jour de mauvaise configuration, y ÉCRIRE.

Le point le plus important est vérifié plusieurs fois sous des angles
différents : sans `appliquer=True`, RIEN ne part en production.
"""

from __future__ import annotations

import pytest

from cal_iut.sync.prod import (
    Comparaison,
    Difference,
    Instance,
    SyncError,
    comparer,
    pousser,
    prod_depuis_env,
)


# --------------------------------------------------------------------------
# Comparaison
# --------------------------------------------------------------------------


def test_deux_plannings_identiques_ne_donnent_aucune_difference() -> None:
    planning = {"s1": (2, 0, 0, "h111"), "s2": (2, 1, 3, None)}
    comp = comparer(planning, dict(planning))
    assert comp.differences == []
    assert comp.identiques == 2
    assert "Identique" in comp.resume()


def test_un_changement_de_salle_seul_est_classe_salle() -> None:
    comp = comparer({"s1": (2, 0, 0, "h111")}, {"s1": (2, 0, 0, "h101")})
    assert [d.genre for d in comp.differences] == ["salle"]


def test_un_deplacement_est_classe_creneau_meme_si_la_salle_change_aussi() -> None:
    """Le créneau prime : c'est lui qui doit être poussé en premier, la salle
    est réaffirmée ensuite (cf. `pousser`)."""
    comp = comparer({"s1": (2, 0, 0, "h111")}, {"s1": (3, 1, 4, "h101")})
    assert [d.genre for d in comp.differences] == ["creneau"]


def test_une_seance_presente_d_un_seul_cote_est_signalee_des_deux_facons() -> None:
    comp = comparer({"a": (1, 0, 0, None)}, {"b": (1, 0, 0, None)})
    genres = sorted(d.genre for d in comp.differences)
    assert genres == ["absente_en_local", "absente_en_prod"]


def test_le_resume_chiffre_chaque_categorie() -> None:
    comp = comparer(
        {"s1": (2, 0, 0, "h111"), "s2": (2, 0, 1, "h101"), "s3": (1, 0, 0, None)},
        {"s1": (2, 0, 0, "h101"), "s2": (5, 0, 1, "h101"), "s3": (1, 0, 0, None)},
    )
    texte = comp.resume()
    assert "2 différence(s) sur 3" in texte
    assert "1 creneau" in texte and "1 salle" in texte


# --------------------------------------------------------------------------
# Poussée : le comportement par défaut doit être INOFFENSIF
# --------------------------------------------------------------------------


class FauxClient:
    """Enregistre les requêtes au lieu de les envoyer."""

    def __init__(self, statut: int = 200) -> None:
        self.appels: list[tuple[str, dict]] = []
        self.statut = statut

    def patch(self, url: str, json: dict):  # noqa: A002 — signature httpx
        self.appels.append((url, json))

        class R:
            status_code = self.statut
            text = "refusé" if self.statut != 200 else "ok"

        return R()


def _cible(statut: int = 200) -> tuple[Instance, FauxClient]:
    faux = FauxClient(statut)
    instance = Instance(url="https://exemple.invalid", mot_de_passe="x", email="admin@example.test")
    instance._client = faux  # type: ignore[assignment]
    return instance, faux


def _comparaison_une_difference(genre_creneau: bool = True) -> Comparaison:
    distant = (5, 1, 2, "h101") if genre_creneau else (2, 0, 0, "h101")
    return Comparaison(differences=[Difference("s1", (2, 0, 0, "h111"), distant)])


def test_sans_appliquer_aucune_requete_n_est_envoyee() -> None:
    """Le garde-fou central : `cal-iut prod push` sans `--appliquer` doit
    pouvoir être lancé sans la moindre conséquence en production."""
    cible, faux = _cible()
    res = pousser(cible, _comparaison_une_difference())
    assert faux.appels == []
    assert res.appliquees == ["s1"], "la simulation dit quand même quoi serait fait"


def test_avec_appliquer_le_creneau_puis_la_salle_sont_envoyes() -> None:
    cible, faux = _cible()
    pousser(cible, _comparaison_une_difference(), appliquer=True)
    urls = [u for u, _ in faux.appels]
    assert urls == ["/placements/s1", "/placements/s1/salle"]
    assert faux.appels[0][1]["week"] == 2
    assert faux.appels[1][1]["room_id"] == "h111"


def test_un_changement_de_salle_seul_ne_deplace_pas_la_seance() -> None:
    cible, faux = _cible()
    pousser(cible, _comparaison_une_difference(genre_creneau=False), appliquer=True)
    assert [u for u, _ in faux.appels] == ["/placements/s1/salle"]


def test_la_poussee_force_par_defaut() -> None:
    """Un échange de deux séances passe forcément par un état intermédiaire
    en conflit : sans forçage, la moitié de l'échange échouerait."""
    cible, faux = _cible()
    pousser(cible, _comparaison_une_difference(), appliquer=True)
    assert all(corps.get("force") is True for _, corps in faux.appels)


def test_une_salle_videe_en_local_est_bien_videe_en_production() -> None:
    """Les CM sans salle assignable doivent le rester là-bas (retour
    utilisateur : « il faut laisser la salle vide, elle sera rentrée par la
    suite »), et non garder l'ancienne petite salle."""
    cible, faux = _cible()
    comp = Comparaison(differences=[Difference("s1", (2, 0, 0, None), (2, 0, 0, "h006"))])
    pousser(cible, comp, appliquer=True)
    assert faux.appels[-1][1]["room_id"] == ""


def test_une_seance_absente_d_un_cote_est_ignoree_pas_creee_ni_supprimee() -> None:
    """Créer ou supprimer une séance à distance est une décision humaine."""
    cible, faux = _cible()
    comp = comparer({"local_seul": (1, 0, 0, None)}, {"prod_seul": (1, 0, 0, None)})
    res = pousser(cible, comp, appliquer=True)
    assert faux.appels == []
    assert sorted(sid for sid, _ in res.ignorees) == ["local_seul", "prod_seul"]
    assert res.appliquees == []


def test_un_refus_du_serveur_est_rapporte_et_n_arrete_pas_le_reste() -> None:
    cible, faux = _cible(statut=409)
    comp = Comparaison(
        differences=[
            Difference("s1", (2, 0, 0, "h111"), (2, 0, 0, "h101")),
            Difference("s2", (2, 0, 1, "h111"), (2, 0, 1, "h101")),
        ]
    )
    res = pousser(cible, comp, appliquer=True)
    assert [sid for sid, _ in res.echecs] == ["s1", "s2"], "les deux sont tentées"
    assert res.appliquees == []
    assert "409" in res.echecs[0][1]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_sans_configuration_le_message_dit_quoi_renseigner(monkeypatch) -> None:
    monkeypatch.delenv("CAL_IUT_PROD_URL", raising=False)
    monkeypatch.delenv("CAL_IUT_PROD_PASSWORD", raising=False)
    with pytest.raises(SyncError, match="CAL_IUT_PROD_URL"):
        prod_depuis_env()


def test_une_url_sans_mot_de_passe_ne_suffit_pas(monkeypatch) -> None:
    """Sinon on tenterait une connexion anonyme et l'erreur arriverait plus
    loin, sous une forme incompréhensible (HTTP 401)."""
    monkeypatch.setenv("CAL_IUT_PROD_URL", "https://exemple.invalid")
    monkeypatch.delenv("CAL_IUT_PROD_PASSWORD", raising=False)
    with pytest.raises(SyncError):
        prod_depuis_env()


def test_une_instance_non_connectee_le_dit_clairement() -> None:
    with pytest.raises(SyncError, match="non connectée"):
        Instance(url="https://exemple.invalid", mot_de_passe="x", email="admin@example.test").client


# --------------------------------------------------------------------------
# Le sens inverse : ramener la production en local
# --------------------------------------------------------------------------


def test_inverser_echange_les_deux_cotes() -> None:
    """Le sens PROD -> LOCAL réutilise `pousser` sur une comparaison
    retournée, plutôt qu'un second chemin à maintenir."""
    comp = comparer({"s1": (2, 0, 0, "h111")}, {"s1": (5, 1, 2, "h101")})
    inverse = comp.inverser()
    assert inverse.differences[0].local == (5, 1, 2, "h101")
    assert inverse.differences[0].distant == (2, 0, 0, "h111")


def test_inverser_conserve_le_nombre_d_identiques() -> None:
    comp = comparer({"a": (1, 0, 0, None), "b": (1, 0, 1, None)}, {"a": (1, 0, 0, None), "b": (2, 0, 1, None)})
    assert comp.inverser().identiques == comp.identiques == 1


def test_inverser_inverse_aussi_le_sens_des_absences() -> None:
    """Une séance absente en prod devient, vue de l'autre côté, une séance
    absente en local — et reste donc ignorée par `pousser` dans les deux
    sens : créer ou supprimer une séance demande une décision humaine."""
    comp = comparer({"local_seul": (1, 0, 0, None)}, {})
    assert [d.genre for d in comp.differences] == ["absente_en_prod"]
    assert [d.genre for d in comp.inverser().differences] == ["absente_en_local"]


def test_le_sens_inverse_applique_bien_les_positions_de_production() -> None:
    """Le cas réel du 29/08/2026 : quelqu'un réorganise la semaine en cours
    directement en ligne, et le poste local doit se remettre à jour sans
    écraser ce travail."""
    cible, faux = _cible()
    comp = comparer({"s1": (2, 0, 0, "h111")}, {"s1": (5, 1, 2, "h101")})
    pousser(cible, comp.inverser(), appliquer=True)
    corps = dict(faux.appels[0][1])
    assert (corps["week"], corps["day"], corps["slot"]) == (5, 1, 2)
    assert faux.appels[-1][1]["room_id"] == "h101"


def test_une_comparaison_inversee_deux_fois_revient_a_l_original() -> None:
    comp = comparer({"s1": (2, 0, 0, "h111")}, {"s1": (5, 1, 2, "h101")})
    aller_retour = comp.inverser().inverser()
    assert aller_retour.differences[0].local == comp.differences[0].local
    assert aller_retour.differences[0].distant == comp.differences[0].distant
