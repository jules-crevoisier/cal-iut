"""Un TD affiché en [CM] dans Celcat doit être VU par l'audit.

Signalement de David Annebicque, 07/09/2026 : « ce qui est dans Celcat est
faux ! Les TD sont aléatoirement indiqués en TD ou en CM dans le type de
cours (premier onglet), ça casse la synchro et ça posera souci sur OMEGA ».

L'outillage existant ne pouvait pas voir ça : `corriger_cm_categories_
celcat.py` construit `types = {sid: "CM" for sid in journal}` — il déclare
que TOUT le journal est du CM, ce qui lui interdit par construction de
juger un TD. `inventaire_ecarts_categorie`, elle, est générique ; ces
tests fixent ce contrat pour les trois types, afin qu'un audit tous-types
puisse s'appuyer dessus.

Le garde-fou d'ÉCRITURE, lui, reste asymétrique et le reste tant qu'on n'a
pas relevé les identifiants Celcat de [TD] et [TP] : `CATEGORIE_IDS` ne
connaît que `CM: 430`, donc `verifier_charge_categorie` refuse un CM mal
catégorisé mais laisse passer un TD portant l'identifiant du CM. C'est
exactement la forme du symptôme signalé — d'où le dernier test, qui
documente ce trou plutôt que de le prétendre bouché.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cal_iut.celcat.categories import (
    CategorieRefusee,
    inventaire_ecarts_categorie,
    type_depuis_identifiant,
    verifier_charge_categorie,
)


@dataclass
class EvenementLive:
    """Ce que `lecture.evenement_depuis_rpc` retient d'un événement Celcat."""

    categorie: str


def _journal(session_id: str, event_id: int) -> dict[str, dict]:
    return {session_id: {"event_id": str(event_id), "signature": "1|4|08:00|09:30|X|H.103|M|4|TD AB"}}


def test_un_td_affiche_en_cm_est_signale():
    """Le cas de David : la maquette dit TD, Celcat affiche [CM]."""
    ecarts = inventaire_ecarts_categorie(
        journal=_journal("WR101-S1-TD-1-but1-td-ab", 1933256),
        live_par_event_id={1933256: EvenementLive(categorie="[CM]")},
        type_par_session={"WR101-S1-TD-1-but1-td-ab": "TD"},
    )

    assert len(ecarts) == 1
    ecart = ecarts[0]
    assert ecart.type_attendu == "TD"
    assert ecart.categorie_live == "[CM]"
    assert ecart.event_id == 1933256
    assert "[TD]" in ecart.motif and "[CM]" in ecart.motif


def test_un_td_correctement_affiche_ne_remonte_pas():
    """Sans quoi un audit « tout est faux » ne dirait rien de plus qu'un
    audit « rien n'est faux » : le tri doit rester informatif."""
    assert (
        inventaire_ecarts_categorie(
            journal=_journal("WR101-S1-TD-1-but1-td-ab", 1933256),
            live_par_event_id={1933256: EvenementLive(categorie="[TD]")},
            type_par_session={"WR101-S1-TD-1-but1-td-ab": "TD"},
        )
        == []
    )


def test_les_trois_types_sont_juges_chacun_sur_le_sien():
    """Un lot mêlant CM, TD et TP : chacun comparé à SON libellé attendu,
    et seuls les deux fautifs remontent."""
    journal = {
        "WR103-S1-CM-1": {"event_id": "1949592"},
        "WR101-S1-TD-1-but1-td-ab": {"event_id": "1933256"},
        "WR101-S1-TP-1-but1-tp-a": {"event_id": "1949679"},
    }
    live = {
        1949592: EvenementLive(categorie="[CM]"),  # correct
        1933256: EvenementLive(categorie="[CM]"),  # TD affiché en CM
        1949679: EvenementLive(categorie="[TD]"),  # TP affiché en TD
    }
    types = {
        "WR103-S1-CM-1": "CM",
        "WR101-S1-TD-1-but1-td-ab": "TD",
        "WR101-S1-TP-1-but1-tp-a": "TP",
    }

    ecarts = inventaire_ecarts_categorie(
        journal=journal, live_par_event_id=live, type_par_session=types
    )

    assert {(e.type_attendu, e.categorie_live) for e in ecarts} == {("TD", "[CM]"), ("TP", "[TD]")}


def test_le_type_se_relit_dans_l_identifiant_quand_la_maquette_est_muette():
    """Hors du serveur, `state.timetable` est vide et AUCUNE séance ne
    serait jugée : l'audit conclurait « aucun écart », ce qui se lirait
    comme une bonne nouvelle. Le journal porte pourtant le type dans son
    identifiant — vérifié sur les 268 séances réellement journalisées
    (145 TD, 83 TP, 40 CM)."""
    assert type_depuis_identifiant("WR101-S1-TD-1-but1-td-ab") == "TD"
    assert type_depuis_identifiant("WR103-S1-CM-1") == "CM"
    assert type_depuis_identifiant("WR101-S1-TP-1-but1-tp-a") == "TP"
    assert type_depuis_identifiant("ECHANGE-IA-S1-CM-CUSTOM1-but1-promo") == "CM"


def test_un_identifiant_sans_type_ne_se_devine_pas():
    """Mieux vaut une séance non jugée qu'une séance jugée à tort : un
    faux écart enverrait corriger une catégorie qui allait bien."""
    assert type_depuis_identifiant("libre-sans-type") == ""
    assert type_depuis_identifiant("") == ""
    # « CMD » n'est pas « CM » : seul un segment entier compte.
    assert type_depuis_identifiant("WR101-S1-CMD-1") == ""


def test_un_td_envoye_avec_l_identifiant_du_cm_est_refuse():
    """Le symptôme de David, empêché À L'ÉCRITURE cette fois.

    Le filet ne connaissait que l'identifiant du [CM] (430) : il refusait un
    CM mal catégorisé, mais laissait passer un TD portant ce même 430 —
    seule l'absence pure d'identifiant l'arrêtait. Les identifiants de [TD]
    (433) et [TP] (435), relevés sur URCA_2026 le 07/09/2026, rendent le
    filet symétrique.
    """
    with pytest.raises(CategorieRefusee, match="433"):
        verifier_charge_categorie({"event_cat_id": 430}, type_seance_nom="TD")

    with pytest.raises(CategorieRefusee, match="435"):
        verifier_charge_categorie({"event_cat_id": 430}, type_seance_nom="TP")


def test_les_categories_justes_passent():
    """Un filet qui refuse tout ne protège rien : il bloquerait la saisie."""
    verifier_charge_categorie({"event_cat_id": 430}, type_seance_nom="CM")
    verifier_charge_categorie({"event_cat_id": 433}, type_seance_nom="TD")
    verifier_charge_categorie({"event_cat_id": 435}, type_seance_nom="TP")


def test_les_variantes_voisines_du_catalogue_sont_refusees():
    """Le catalogue Celcat contient des libellés proches qui ne sont PAS
    les nôtres : [CM Capacite] 429, [CM bénévole] 845, [TD bénévole] 846,
    [TP bénévole] 847, TD0 465. Une séance y atterrirait sans que rien ne
    paraisse anormal à l'écran — et Celcat sert aussi à payer les
    enseignants."""
    for cat_id, type_seance in ((429, "CM"), (845, "CM"), (846, "TD"), (465, "TD"), (847, "TP")):
        with pytest.raises(CategorieRefusee):
            verifier_charge_categorie({"event_cat_id": cat_id}, type_seance_nom=type_seance)


def test_une_charge_sans_categorie_reste_refusee():
    """Le défaut historique : sans catégorie explicite, un CM retombait en
    [TP] du temps de l'autoclicker."""
    for type_seance in ("CM", "TD", "TP"):
        with pytest.raises(CategorieRefusee):
            verifier_charge_categorie({"event_cat_id": None}, type_seance_nom=type_seance)
