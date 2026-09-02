"""Le pilote Celcat, vérifié SANS navigateur ni identifiants.

`PilotePlaywright` reçoit sa page en paramètre : les tests y injectent une
fausse page qui note chaque interaction. La séquence du formulaire — l'ordre
des onglets, les cinq glisser-déposer, l'enregistrement en dernier — se
vérifie donc hors ligne, ce qui est le seul moyen de la verrouiller : Celcat
vit derrière un VPN et alimente la paie, on ne l'utilise pas comme banc
d'essai.

Ce qui est délibérément NON testé ici : que Celcat accepte la saisie une
fois les libellés relevés. Ça se joue derrière le VPN. Les tests vérifient
la séquence, le refus tant que la carte est vide, et que la carte livrée
porte bien ce que le relevé du 01/09/2026 a lu.
"""

from __future__ import annotations

import datetime as dt

import pytest

from cal_iut.celcat import formulaire, navigateur as nav
from cal_iut.celcat.driver import PilotePlaywright, Rythme
from cal_iut.celcat.formulaire import CarteFormulaire, FormulaireNonReleve, charger_carte
from cal_iut.celcat.mapping import CelcatConfig, entree_pour_placement

# --------------------------------------------------------------------------
# Fausse page : juste ce que `navigateur.py` utilise, et un journal
# --------------------------------------------------------------------------


class FausseSouris:
    def __init__(self, page: FaussePage) -> None:
        self.page = page

    def click(self, x, y, click_count=1, **_):
        self.page.journal.append(("clic", x, y) if click_count == 1 else ("clic", x, y, click_count))
        self.page.ouvrir_icone_gauche(x, y)
        # Clic sur une cellule d'inspecteur (infobulle datée) : Celcat
        # restreint l'événement à cette semaine. Pas les autres infobulles
        # (« Créer un nouvel événement »).
        bulle = self.page.infobulles.get((x, y), "")
        if "/" in bulle:
            for texte in list(self.page.textes):
                if "[=54]" in texte:
                    pos = self.page.textes.pop(texte)
                    self.page.textes["4 (09/07/26) [=1]"] = pos
                    break

    def move(self, x, y, steps=1, **_):
        self.page.survol = (x, y)
        self.page.journal.append(("deplacement", x, y) if steps == 1 else ("deplacement", x, y, steps))

    def down(self, **_):
        self.page.journal.append(("appui",))

    def up(self, **_):
        self.page.journal.append(("relachement",))

    def wheel(self, dx, dy):
        self.page.journal.append(("molette", dx, dy))


class FausseClavier:
    def __init__(self, page: FaussePage) -> None:
        self.page = page

    def type(self, texte, delay=0):
        self.page.journal.append(("frappe", texte))

    def press(self, touche):
        self.page.journal.append(("touche", touche))


class FaussePage:
    """Écran scriptable. `textes` = ce qui est affiché, avec sa position."""

    def __init__(self, *, textes=None, champs=None, icones=None, cellules=None,
                 infobulles=None) -> None:
        self.textes: dict[str, tuple[int, int]] = dict(textes or {})
        self.champs = list(champs or [])
        self.icones: dict[str, list[tuple[int, int]]] = dict(icones or {})
        self.cellules = list(cellules or [])
        # Infobulle affichée au survol d'une position — n'existe que le temps
        # du survol, comme dans la vraie application.
        self.infobulles: dict[tuple[int, int], str] = dict(infobulles or {})
        self.survol: tuple[int, int] | None = None
        self.journal: list[tuple] = []
        self.titre_panneau = ""
        self.mouse = FausseSouris(self)
        self.keyboard = FausseClavier(self)

    # --- API Playwright utilisée par navigateur.py ---

    def goto(self, url, **_):
        self.journal.append(("goto", url))

    def wait_for_timeout(self, ms):  # trop bavard pour le journal
        return None

    def ouvrir_icone_gauche(self, x: int, y: int) -> None:
        """Un clic dans la colonne d'icônes change le titre du panneau."""
        if x > 25:
            return
        for type_id, ordonnee in nav.ICONES.items():
            if abs(y - ordonnee) <= 10:
                self.titre_panneau = nav.TITRES_PANNEAU[type_id]
                return

    def on(self, evenement, gestionnaire):
        return None

    def evaluate(self, js, arg=None):
        if "out.push({texte:" in js:
            feuilles = [{"texte": t, "x": p[0], "y": p[1]} for t, p in self.textes.items()]
            if self.titre_panneau:
                feuilles.append({"texte": self.titre_panneau, "x": 78, "y": 40})
            if self.survol in self.infobulles:
                x, y = self.survol
                feuilles.append({"texte": self.infobulles[self.survol], "x": x, "y": y - 20})
            return feuilles
        if "zone.y_min" in js:
            # Les vraies cellules n'ont pas de texte : on ne rend que de la
            # géométrie, exactement comme le script de relevé l'a constaté.
            zone = arg or {}
            ymin, ymax = zone.get("y_min", 0), zone.get("y_max", 10_000)
            xmin, xmax = zone.get("x_min", 0), zone.get("x_max", 10_000)
            return [
                {
                    "x": c["x"], "y": c["y"],
                    "gauche": c.get("gauche", c["x"] - 38),
                    "haut": c.get("haut", c["y"] - 5),
                }
                for c in self.cellules
                if ymin <= c["y"] <= ymax and xmin <= c["x"] <= xmax
            ]
        if "backgroundImage" in js:
            return [
                {"x": x, "y": y, "fond": f"url(.../{arg}.png)"}
                for (x, y) in self.icones.get(arg, [])
            ]
        if "input,textarea" in js:
            return [dict(c) for c in self.champs]
        raise AssertionError(f"script inattendu : {js[:60]}")

    # --- aides de lecture pour les tests ---

    def clics(self) -> list[tuple[int, int]]:
        return [(e[1], e[2]) for e in self.journal if e[0] == "clic" and len(e) == 3]

    def frappes(self) -> list[str]:
        return [e[1] for e in self.journal if e[0] == "frappe"]

    def glissers(self) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        """Les glisser-déposer réellement effectués : prise -> dépôt."""
        sortie, prise = [], None
        for i, e in enumerate(self.journal):
            if e[0] == "appui":
                for prec in reversed(self.journal[:i]):
                    if prec[0] == "deplacement":
                        prise = (prec[1], prec[2])
                        break
            elif e[0] == "relachement" and prise is not None:
                for prec in reversed(self.journal[:i]):
                    if prec[0] == "deplacement":
                        sortie.append((prise, (prec[1], prec[2])))
                        break
                prise = None
        return sortie


CARTE_COMPLETE = CarteFormulaire(
    onglet_details="Détails",
    onglet_ressources="Ressources",
    jour="Jour:",
    heure="Heure:",
    champs={
        "categorie": "Catégorie d'événement:",
        "departement": "Département:",
        "enseignant": "Personnel",
        "salle": "Salles",
        "matiere": "Matières",
    },
    categories={"TD": "[TD]", "TP": "[TP]"},
    decalage_champ_y=32,
)


@pytest.fixture
def cfg() -> CelcatConfig:
    return CelcatConfig(
        enseignants={"FLI": "20900"},
        salles={"h111": "H.111"},
        types_seance={"TD": 4, "TP": 6, "CM": None},
        modules={"WR314D": "TSBZ2520"},
    )


def _entree(cfg, **kw):
    base = {
        "session_id": "s1", "course_code": "WR314D", "session_type": "TD", "week": 2,
        "day": 0, "slot": 0, "duration_slots": 1, "teacher_codes": ["FLI"],
        "room_id": "h111", "groupe": "TD AB", "semestre": "S2", "lundi": "2026-09-14",
    }
    base.update(kw)
    return entree_pour_placement(cfg, **base)


# --------------------------------------------------------------------------
# Ce que la traduction doit refuser de deviner
# --------------------------------------------------------------------------


def test_sans_semestre_le_nom_du_groupe_celcat_est_introuvable(cfg) -> None:
    """« TD AB » ne suffit pas : Celcat nomme « BUT MMI S2 TD AB »."""
    e = _entree(cfg, semestre="")
    assert not e.prete
    assert any("semestre" in b for b in e.bloquants)


def test_sans_date_la_semaine_celcat_n_est_pas_reperable(cfg) -> None:
    """Le sélecteur de semaines s'identifie par ses DATES. Envoyer l'index
    solveur (ou `index + 1`) y déverserait la promo sur d'autres semaines."""
    e = _entree(cfg, lundi="")
    assert not e.prete
    assert any("semaine" in b for b in e.bloquants)


def test_le_nom_de_groupe_celcat_est_reconstitue(cfg) -> None:
    assert _entree(cfg).nom_groupe_celcat == "BUT MMI S2 TD AB"


def test_un_groupe_promo_devient_cm_cote_celcat(cfg) -> None:
    assert _entree(cfg, groupe="Promo BUT1", semestre="S1").nom_groupe_celcat == "BUT MMI S1 CM"


def test_le_type_de_seance_garde_son_nom(cfg) -> None:
    """Le libellé de catégorie se retrouve par « TD », pas par l'index 4."""
    assert _entree(cfg).type_seance_nom == "TD"


# --------------------------------------------------------------------------
# Semaine : lever l'ambiguïté du format de date sans rien supposer
# --------------------------------------------------------------------------


def test_infobulle_en_jour_mois(cfg) -> None:
    """« 1 (04/01/27–10/01/27) », capture utilisateur du 01/09/2026."""
    assert nav.infobulle_designe_la_semaine("1 (04/01/27–10/01/27)", dt.date(2027, 1, 4))


def test_infobulle_en_mois_jour(cfg) -> None:
    """« 4 (1/25/27-1/31/27) », relevé de docs/CELCAT.md — l'autre lecture."""
    assert nav.infobulle_designe_la_semaine("4 (1/25/27-1/31/27)", dt.date(2027, 1, 25))


def test_une_semaine_sosie_est_rejetee() -> None:
    """Le vrai danger : prendre la semaine du 1er avril pour celle du 4
    janvier, les deux s'écrivant avec les mêmes chiffres inversés. Exiger un
    intervalle de six jours cohérent suffit à les distinguer."""
    assert not nav.infobulle_designe_la_semaine("14 (01/04/27–07/04/27)", dt.date(2027, 1, 4))


def test_un_intervalle_qui_n_est_pas_une_semaine_est_rejete() -> None:
    assert not nav.infobulle_designe_la_semaine("(04/01/27–15/01/27)", dt.date(2027, 1, 4))


def test_une_infobulle_sans_deux_dates_ne_designe_rien() -> None:
    assert not nav.infobulle_designe_la_semaine("Semaine 4", dt.date(2027, 1, 4))
    assert not nav.infobulle_designe_la_semaine("", dt.date(2027, 1, 4))


def test_choisir_semaine_survole_avant_de_cliquer() -> None:
    """L'infobulle n'existe que pendant un survol réel : c'est la conclusion
    du 01/09/2026, après une nuit de coordonnées devinées sans succès."""
    page = FaussePage(
        cellules=[{"x": 100, "y": 900}, {"x": 130, "y": 900}],
        infobulles={
            (100, 900): "3 (07/09/26–13/09/26)",
            (130, 900): "4 (14/09/26–20/09/26)",
        },
    )
    choisie = nav.choisir_semaine(page, dt.date(2026, 9, 14))
    assert "14/09/26" in choisie["infobulle"]
    assert page.journal.index(("deplacement", 130, 900)) < page.journal.index(("clic", 130, 900))
    assert ("clic", 100, 900) not in page.journal


def test_choisir_semaine_leve_plutot_que_de_cliquer_au_hasard() -> None:
    page = FaussePage(
        cellules=[{"x": 100, "y": 900}],
        infobulles={(100, 900): "3 (07/09/26–13/09/26)"},
    )
    with pytest.raises(LookupError, match="2027-03-01"):
        nav.choisir_semaine(page, dt.date(2027, 3, 1), delai=0.2)
    assert page.clics() == []


def test_choisir_semaine_lit_le_format_reel_de_celcat() -> None:
    """Format relevé sur le vrai Celcat le 01/09/2026 : « Week: 37
    (9/7/26-9/13/26) » — préfixe anglais et dates en mois/jour/an."""
    page = FaussePage(
        cellules=[{"x": 278, "y": 869}, {"x": 357, "y": 869}, {"x": 436, "y": 869},
                  {"x": 521, "y": 869}],
        infobulles={
            (278, 869): "Week: 34 (8/17/26-8/23/26)",
            (357, 869): "Week: 35 (8/24/26-8/30/26)",
            (436, 869): "Week: 36 (8/31/26-9/6/26)",
            (521, 869): "Week: 37 (9/7/26-9/13/26)",
        },
    )
    choisie = nav.choisir_semaine(page, dt.date(2026, 9, 7))
    assert choisie["infobulle"] == "Week: 37 (9/7/26-9/13/26)"
    assert page.clics() == [(521, 869)]


def test_choisir_semaine_saute_a_la_cellule_calculee_sans_tout_survoler() -> None:
    """52 cellules × 650 ms de survol feraient une minute par semaine. Une
    cellule valant une semaine dans l'ordre de lecture, la première suffit à
    caler l'origine — mais la cellule visée est VÉRIFIÉE avant le clic."""
    cellules = [{"x": 199 + 79 * i, "y": 869} for i in range(8)]
    infobulles = {
        (c["x"], 869): f"Week: {41 + i} ({(dt.date(2026, 10, 5) + dt.timedelta(weeks=i)).month}/"
        f"{(dt.date(2026, 10, 5) + dt.timedelta(weeks=i)).day}/26-"
        f"{(dt.date(2026, 10, 11) + dt.timedelta(weeks=i)).month}/"
        f"{(dt.date(2026, 10, 11) + dt.timedelta(weeks=i)).day}/26)"
        for i, c in enumerate(cellules)
    }
    page = FaussePage(cellules=cellules, infobulles=infobulles)

    nav.choisir_semaine(page, dt.date(2026, 11, 16))

    survols = [e for e in page.journal if e[0] == "deplacement"]
    assert len(survols) == 2, "une cellule pour l'origine, une pour vérifier la cible"
    assert page.clics() == [(199 + 79 * 6, 869)]


def test_les_cellules_du_selecteur_sont_fusionnees_quand_elles_se_superposent() -> None:
    """qooxdoo empile deux `div` par cellule (relevé : mêmes colonnes à y=869
    et y=872). Sans fusion, chaque semaine serait comptée deux fois et
    l'indice calculé désignerait une semaine sur deux."""
    page = FaussePage(
        cellules=[
            {"x": 278, "y": 869, "gauche": 240, "haut": 869},
            {"x": 278, "y": 872, "gauche": 240, "haut": 872},
            {"x": 357, "y": 869, "gauche": 319, "haut": 869},
            {"x": 357, "y": 872, "gauche": 319, "haut": 872},
        ],
    )
    assert len(nav.cellules_semaines(page)) == 2


# --------------------------------------------------------------------------
# Icônes de la barre du panneau
# --------------------------------------------------------------------------


def test_une_icone_de_barre_se_clique_par_son_image() -> None:
    """qooxdoo ne leur donne ni texte, ni title, ni role."""
    page = FaussePage(icones={"new": [(1422, 218)]})
    nav.cliquer_icone_barre(page, "creer")
    assert page.clics() == [(1422, 218)]


def test_deux_icones_identiques_font_lever_plutot_que_choisir() -> None:
    """`new.png` sert dans plusieurs barres : cliquer la mauvaise crée un
    événement dans un panneau qu'on ne regarde pas — c'est l'incident du
    01/09/2026, un événement fantôme récurrent sur 54 semaines."""
    page = FaussePage(icones={"new": [(1422, 218), (300, 400)]})
    with pytest.raises(LookupError, match="2 icônes"):
        nav.cliquer_icone_barre(page, "creer")
    assert page.clics() == []


def test_une_icone_absente_fait_lever() -> None:
    with pytest.raises(LookupError):
        nav.cliquer_icone_barre(FaussePage(), "enregistrer")


# --------------------------------------------------------------------------
# Glisser-déposer : c'est ainsi que le formulaire se remplit
# --------------------------------------------------------------------------


def test_le_glisser_deposer_passe_par_des_positions_intermediaires() -> None:
    """Un saut direct est ignoré par le glisser-déposer maison de qooxdoo."""
    page = FaussePage()
    nav.glisser_deposer(page, (210, 287), (600, 720))
    types = [e[0] for e in page.journal]
    assert types == ["deplacement", "appui", "deplacement", "relachement"]
    depose = next(e for e in page.journal if e[0] == "deplacement" and len(e) == 4)
    assert depose[1:3] == (600, 720)
    assert depose[3] > 1  # steps


# --------------------------------------------------------------------------
# Carte du formulaire : refuser, et dire quoi faire
# --------------------------------------------------------------------------


def test_la_carte_livree_porte_l_onglet_ressources_releve() -> None:
    """Relevé du 01/09/2026 sur URCA_2025, événement réel (pas un férié)."""
    carte = charger_carte("data/config")
    assert carte.jour == "Jour:"
    assert carte.heure == "Heure:"
    assert carte.champs["enseignant"] == "Personnel"
    assert carte.champs["salle"] == "Salles"
    assert carte.champs["matiere"] == "Matières"
    assert carte.categories == {"TD": "[TD]", "TP": "[TP]", "CM": "[CM]"}
    assert carte.manques() == []
    assert carte.confirmee


def test_une_carte_absente_ne_vaut_pas_une_carte_vide(tmp_path) -> None:
    assert charger_carte(tmp_path).manques()


def test_le_refus_dit_ou_aller(tmp_path) -> None:
    with pytest.raises(FormulaireNonReleve) as erreur:
        CarteFormulaire().exiger_complete()
    message = str(erreur.value)
    assert "celcat_formulaire.yaml" in message
    assert "relever_formulaire" in message
    assert "Rien n'a été écrit" in message


def test_la_categorie_se_designe_par_son_libelle_pas_par_un_index() -> None:
    assert CARTE_COMPLETE.categorie("TD") == "[TD]"
    with pytest.raises(FormulaireNonReleve, match="CM"):
        CARTE_COMPLETE.categorie("CM")


def test_une_carte_complete_est_confirmee() -> None:
    assert CARTE_COMPLETE.confirmee, CARTE_COMPLETE.manques()


# --------------------------------------------------------------------------
# Le pilote
# --------------------------------------------------------------------------


def _rythme() -> Rythme:
    zero = (0.0, 0.0)
    return Rythme(entre_actions=zero, entre_seances=zero, entre_groupes=zero,
                  pause_longue_toutes_les=0, pause_longue=zero)


def _page_connexion() -> FaussePage:
    return FaussePage(
        textes={
            "URCA_FORMATION": (400, 300),
            "Connexion": (500, 600),
            "par défaut": (700, 400),
            "985_T_MMI": (700, 450),
            "OK": (800, 700),
            "Déconnexion": (1500, 50),
        },
        champs=[{"type": "text", "x": 600, "y": 350}, {"type": "password", "x": 600, "y": 400}],
    )


def test_la_connexion_vise_la_base_d_entrainement_par_defaut(monkeypatch) -> None:
    """On n'apprend pas à écrire sur la base de production."""
    monkeypatch.setenv("CELCAT_URL", "https://celcat.test/")
    page = _page_connexion()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.ouvrir_session("bres0026", "secret")
    assert ("clic", 400, 300) in page.journal      # URCA_FORMATION
    assert "bres0026" in page.frappes()
    assert pilote.base == nav.BASE_ENTRAINEMENT
    assert pilote.role == nav.ROLE_ECRITURE


def test_le_mot_de_passe_n_apparait_jamais_dans_le_journal_du_pilote(monkeypatch) -> None:
    monkeypatch.setenv("CELCAT_URL", "https://celcat.test/")
    pilote = PilotePlaywright(_rythme(), page=_page_connexion(), carte=CARTE_COMPLETE)
    pilote.ouvrir_session("bres0026", "SECRET-123")
    assert "SECRET-123" not in " ".join(pilote.actions)
    assert "bres0026" in " ".join(pilote.actions)


def test_choisir_groupe_cherche_le_nom_celcat_puis_la_bonne_semaine(cfg) -> None:
    entree = _entree(cfg)
    page = FaussePage(
        textes={
            "Groupes": (78, 40),
            "Département": (900, 120),
            "BUT MMI S2 TD AB - 2024": (300, 500),
            "Semaines de l'emploi du temps": (200, 840),
        },
        cellules=[{"numero": 3, "x": 100, "y": 900}, {"numero": 4, "x": 130, "y": 900}],
        infobulles={
            (100, 900): "3 (07/09/26–13/09/26)",
            (130, 900): "4 (14/09/26–20/09/26)",
        },
    )
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.choisir_groupe(entree.nom_groupe_celcat, entree.semaine, lundi=entree.lundi)

    assert "BUT MMI S2 TD AB" in page.frappes()
    # Double-clic sur la ligne : c'est ce qui ouvre l'emploi du temps.
    assert ("clic", 300, 500, 2) in page.journal
    # Puis la semaine du 14/09, pas celle du 07/09.
    assert ("clic", 130, 900) in page.journal
    assert ("clic", 100, 900) not in page.journal


def test_ouvrir_ressource_ne_clique_pas_si_le_panneau_est_deja_le_bon() -> None:
    """Les Y figés des icônes ouvrent le mauvais type : si le titre est déjà
    le bon, on ne retouche pas la colonne."""
    page = FaussePage(textes={"Groupes": (78, 40)})
    nav.ouvrir_ressource(page, nav.TYPE_GROUPES)
    assert page.clics() == []


def test_creer_seance_refuse_tant_que_le_formulaire_n_est_pas_releve(cfg) -> None:
    """Aucun clic ne doit partir : c'est tout l'intérêt du refus."""
    page = FaussePage(icones={"new": [(1422, 218)]})
    pilote = PilotePlaywright(_rythme(), page=page, carte=CarteFormulaire())
    with pytest.raises(FormulaireNonReleve):
        pilote.creer_seance(_entree(cfg))
    assert page.journal == []


def _page_formulaire() -> FaussePage:
    """L'inspecteur d'événement, aux positions RELEVÉES le 01/09/2026.

    Les coordonnées ne sont pas inventées : ce sont celles lues sur
    `URCA_2026` en 1920×1080 (`data/releves/celcat-formulaire-20260901-164729`).
    Les garder exactes fait que ces tests attrapent une erreur de décalage —
    viser à droite de « Jour: » tombe sur « Heure: », à 18 px près.
    """
    return FaussePage(
        textes={
            "Détails": (960, 622),
            "Ressources": (1055, 622),
            "Semaines:": (635, 702),
            "4 (09/07/26) [=1]": (1296, 702),
            "Jour:": (952, 737),
            "Heure:": (1090, 737),
            "Catégorie d'événement:": (1320, 734),
            "Département:": (1283, 802),
            "Personnel": (687, 737),
            "Salles": (672, 701),
            "Matières": (680, 666),
            # La ligne prise dans la liste de gauche, après filtrage.
            "[TD]": (210, 287),
            "T_MMI": (210, 287),
            "20900": (210, 287),
            "H.111": (210, 287),
            "TSBZ2520": (210, 287),
            "Sun": (1820, 134),
            "10:00 AM": (620, 221),
        },
        # `new` en double, comme à l'écran : le « Nouveau » de la liste de
        # gauche et celui de l'emploi du temps. Les quatre autres icônes
        # n'ont pas de doublon et servent à désigner la bonne barre.
        icones={
            "new": [(64, 81), (1802, 83)],
            "delete": [(1824, 83)],
            "refresh": [(1862, 84)],
            "save": [(1884, 83)],
            "cancel": [(1906, 83)],
        },
        infobulles={(1802, 83): "Créer un nouvel événement"},
    )


def test_une_case_vide_se_clique_au_croisement_jour_heure() -> None:
    """L'ancien autoclicker visait le dimanche pour éviter un créneau occupé."""
    page = _page_formulaire()
    case = nav.cliquer_case_vide(page)
    assert case["jour"] == "Sun"
    assert case["heure"] == "10:00 AM"
    assert page.clics() == [(1820, 233)]


def test_fermer_panneau_conflits_revient_aux_groupes() -> None:
    """Après un `new` sur une case occupée, Celcat ouvre Conflits, pas Détails."""
    page = FaussePage(textes={"Conflits": (200, 280)})
    assert nav.fermer_panneau_conflits(page) is True
    assert page.titre_panneau == "Groupes"
    page = _page_formulaire()
    assert nav.fermer_panneau_conflits(page) is False
    assert page.clics() == []


def test_creer_seance_continue_si_conflits_avec_details(cfg) -> None:
    """`new` ouvre souvent Conflits (54 semaines) : on remplit quand même."""
    page = _page_formulaire()
    page.textes["Conflits"] = (200, 280)
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg))
    assert ("clic", 1884, 83) in page.journal
    assert ("clic", 1802, 83) in page.journal
    # Conflits se ferme AVANT d'attendre Détails : sinon l'inspecteur
    # n'apparaît pas (constaté le 01/09/2026, événement 1933224).
    icone_groupes = ("clic", 20, 266)
    onglet_details = ("clic", 960, 622)
    assert icone_groupes in page.journal
    assert page.journal.index(icone_groupes) < page.journal.index(onglet_details)


def test_creer_seance_clique_une_case_vide_avant_new(cfg) -> None:
    """Sans la case vide, `new` reprend le lundi 7h (événement 1933212)."""
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg))

    # Dimanche vide d'abord, PUIS `new` de l'emploi du temps — pas celui de
    # la liste de gauche. Sans la case vide, `new` reprend le lundi 7h.
    assert page.journal[0] == ("clic", 1820, 233)
    assert ("clic", 1802, 83) in page.journal
    assert page.journal[-1] == ("clic", 1884, 83)
    assert ("clic", 64, 81) not in page.journal

    # Les deux onglets, dans l'ordre : Détails puis Ressources.
    onglets = {(960, 622), (1055, 622)}
    ordre = [e for e in page.journal if e[0] == "clic" and (e[1], e[2]) in onglets]
    assert ordre[0] == ("clic", 960, 622)
    assert ("clic", 1055, 622) in ordre
    assert ordre.index(("clic", 960, 622)) < ordre.index(("clic", 1055, 622))

    # L'horaire est saisi en UNE fois, en 12 heures, comme Celcat l'affiche.
    assert "8:00 AM-9:30 AM" in page.frappes()

    # Les CINQ champs de ressource sont remplis par glisser-déposer.
    assert len(page.glissers()) == 5


def test_creer_seance_depose_chaque_ressource_sur_son_champ(cfg) -> None:
    """Un dépôt sur le mauvais champ rattacherait la séance à la mauvaise
    ressource — invisible jusqu'au moment de payer."""
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg))

    depots = [arrivee for _, arrivee in page.glissers()]
    dy = CARTE_COMPLETE.decalage_champ_y
    assert (1320, 734 + dy) in depots   # Catégorie d'événement
    assert (1283, 802 + dy) in depots   # Département
    assert (687, 737 + dy) in depots   # Personnel
    assert (672, 701 + dy) in depots   # Salles
    assert (680, 666 + dy) in depots   # Matières


def test_creer_seance_cherche_les_valeurs_de_l_entree(cfg) -> None:
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg))

    frappes = page.frappes()
    assert "[TD]" in frappes        # catégorie par LIBELLÉ, pas l'index 4
    assert "20900" in frappes       # code enseignant
    assert "H.111" in frappes       # salle
    assert "TSBZ2520" in frappes    # module
    assert "4" not in frappes


def test_le_jour_se_choisit_au_clavier(cfg) -> None:
    """Déroulant trié lundi -> dimanche : Home, puis Bas, puis Entrée.
    Lundi (jour Celcat 1) ne demande aucun Bas."""
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg, day=2))  # mercredi -> jour Celcat 3

    touches = [e[1] for e in page.journal if e[0] == "touche"]
    assert "Home" in touches
    assert touches.count("ArrowDown") == 2
    assert touches.index("Home") < touches.index("Enter")


def test_creer_seance_refuse_si_le_formulaire_porte_54_semaines(cfg) -> None:
    """`new` coche l'année entière : enregistrer recopierait la séance."""
    page = _page_formulaire()
    page.textes.pop("4 (09/07/26) [=1]", None)
    page.textes["1-54 [=54]"] = (800, 702)
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    with pytest.raises(ValueError, match="54"):
        pilote.creer_seance(_entree(cfg))
    assert ("clic", 1884, 83) not in page.journal
    assert ("clic", 1906, 83) in page.journal


def test_creer_seance_restreint_les_54_semaines_avant_enregistrer(cfg) -> None:
    """Un clic sur la cellule de l'inspecteur ramène à [=1], puis on sauve."""
    page = _page_formulaire()
    page.textes.pop("4 (09/07/26) [=1]", None)
    page.textes["1-54 [=54]"] = (1459, 702)
    page.cellules = [{"x": 996, "y": 660}]
    page.infobulles[(996, 660)] = "Week: 38 (9/14/26-9/20/26)"
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg))
    assert ("clic", 996, 660) in page.journal
    assert ("clic", 1884, 83) in page.journal
    assert ("clic", 1906, 83) not in page.journal


def test_restreindre_semaines_ne_fait_rien_si_deja_une() -> None:
    page = _page_formulaire()
    assert nav.restreindre_semaines_formulaire(page, dt.date(2026, 9, 14)) == 1
    assert page.clics() == []


def test_creer_seance_annule_si_un_depot_echoue(cfg) -> None:
    """Un `new` déjà cliqué sans Enregistrer laisse un fantôme : on annule."""
    page = _page_formulaire()
    page.textes.pop("[TD]", None)
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    with pytest.raises(LookupError):
        pilote.creer_seance(_entree(cfg))
    assert ("clic", 1802, 83) in page.journal
    assert ("clic", 1884, 83) not in page.journal
    assert ("clic", 1906, 83) in page.journal


def test_saisir_horaire_remplit_le_dialogue_deux_champs() -> None:
    """Cliquer « Heure: » ouvre « Sélectionner les heures », pas un champ unique."""
    page = FaussePage(
        textes={
            "Heure:": (1090, 737),
            "Sélectionner les heures": (500, 300),
            "Heure de début": (400, 400),
            "Heure de fin": (400, 450),
            "OK": (500, 600),
        },
    )
    nav.saisir_horaire(page, "08:00", "09:30")
    assert "8:00 AM" in page.frappes()
    assert "9:30 AM" in page.frappes()
    assert "8:00 AM-9:30 AM" not in page.frappes()
    assert (500, 600) in page.clics()


def test_creer_seance_ferme_un_inspecteur_deja_ouvert(cfg) -> None:
    """Un double-clic ouvre 1933212 : on le ferme avant de cliquer `new`."""
    page = _page_formulaire()
    page.textes["Evénement (ID 1933212)"] = (960, 1050)
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.creer_seance(_entree(cfg))
    assert page.journal[0] == ("clic", 1906, 83)
    assert ("clic", 1820, 233) in page.journal
    assert ("clic", 1802, 83) in page.journal


def test_nombre_semaines_lu_a_cote_du_libelle() -> None:
    page = _page_formulaire()
    assert nav.nombre_semaines_formulaire(page) == 1


def test_une_seance_bloquee_n_est_jamais_saisie(cfg) -> None:
    """Dernier rempart : même si le plan laissait passer une entrée bloquée,
    le pilote ne doit pas ouvrir un formulaire pour le remplir à moitié."""
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    with pytest.raises(ValueError, match="bloqu"):
        pilote.creer_seance(_entree(cfg, room_id="inconnue"))
    assert page.journal == []


def test_relever_formulaire_rend_de_quoi_completer_la_carte() -> None:
    """Le relevé remplace la devinette : il vide tout ce qui est à l'écran."""
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CarteFormulaire())
    releve = pilote.relever_formulaire()
    assert "Jour:" in [t["texte"] for t in releve["textes"]]
    assert releve["icones"]["creer"]
    assert "champs" in releve


# --------------------------------------------------------------------------
# Ce que l'exploration du 01/09/2026 a établi sur le vrai Celcat
# --------------------------------------------------------------------------


def test_le_champ_est_sous_son_libelle_et_non_a_sa_droite() -> None:
    """Correction la plus importante du relevé : « Jour: » est en (952, 737),
    sa valeur en (956, 770). Viser 120 px à DROITE, comme on l'avait supposé
    d'après l'ancien autoclicker, tombait sur (1072, 737) — soit le libellé
    « Heure: » à 18 px près. On aurait saisi l'heure dans le champ du jour."""
    page = _page_formulaire()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)

    assert pilote._champ("Jour:") == (952, 769)

    heure = nav.trouver(page, "Heure:")
    assert abs(952 + 120 - heure["x"]) < 20, (
        "l'ancienne hypothèse horizontale visait bien le libellé voisin : "
        "ce test perdrait son sens si les positions relevées changeaient"
    )


def test_l_horaire_est_converti_en_douze_heures() -> None:
    """Celcat affiche « 7:00 AM-11:59 PM » : il parle en 12 heures alors que
    nos horaires sont en 24. Sans conversion, « 14:00 » dans un champ qui
    attend « 2:00 PM » donne au mieux un refus, au pire une heure fausse."""
    assert nav.heure_12h("08:00") == "8:00 AM"
    assert nav.heure_12h("14:00") == "2:00 PM"
    assert nav.heure_12h("12:00") == "12:00 PM"     # midi
    assert nav.heure_12h("00:30") == "12:30 AM"     # minuit
    assert nav.heure_12h("23:59") == "11:59 PM"
    assert nav.intervalle_12h("08:00", "09:30") == "8:00 AM-9:30 AM"
    with pytest.raises(ValueError):
        nav.heure_12h("25:00")
    with pytest.raises(ValueError):
        nav.heure_12h("midi")


def test_l_icone_creer_est_departagee_par_les_icones_sans_doublon() -> None:
    """`new.png` apparaît DEUX fois : le « Nouveau » de la liste de gauche en
    (64, 81) et celui de l'emploi du temps en (1802, 83). Cliquer le premier
    créerait un groupe, pas une séance. Les quatre icônes qui n'ont pas de
    doublon disent où est la bonne barre."""
    page = _page_formulaire()
    cible = nav.cliquer_icone_barre(page, "creer")
    assert (cible["x"], cible["y"]) == (1802, 83)
    assert page.clics() == [(1802, 83)]


def test_sans_repere_de_barre_une_icone_ambigue_fait_lever() -> None:
    """Plutôt s'arrêter que tenter sa chance : c'est un clic sur « new » qui a
    créé l'événement fantôme récurrent du 01/09/2026."""
    page = FaussePage(icones={"new": [(64, 81), (1802, 83)]})
    with pytest.raises(LookupError, match="mauvais panneau"):
        nav.cliquer_icone_barre(page, "creer")
    assert page.clics() == []


def test_la_carte_ne_reclame_plus_deux_champs_d_heure() -> None:
    """L'inspecteur porte UN champ « Heure: » avec l'intervalle entier. Exiger
    un début et une fin séparés aurait fait échouer la saisie sur un champ
    qui n'existe pas."""
    manques = CarteFormulaire(
        onglet_details="Détails", onglet_ressources="Ressources",
        jour="Jour:", heure="Heure:",
        champs={n: n for n in ("categorie", "departement", "enseignant", "salle", "matiere")},
    ).manques()
    assert manques == []
    assert "heure_debut" not in formulaire.CHAMPS_REQUIS
    assert "validation_horaire" not in formulaire.CHAMPS_REQUIS


def test_fermer_se_deconnecte_avant_de_fermer(monkeypatch) -> None:
    """Celcat garde les sessions ouvertes ; en enchaîner sans les rendre
    finit par saturer le serveur, qui cesse d'afficher la liste des bases."""
    monkeypatch.setenv("CELCAT_URL", "https://celcat.test/")
    page = _page_connexion()
    pilote = PilotePlaywright(_rythme(), page=page, carte=CARTE_COMPLETE)
    pilote.ouvrir_session("bres0026", "secret")
    pilote.fermer()
    assert ("clic", 1500, 50) in page.journal   # Déconnexion
