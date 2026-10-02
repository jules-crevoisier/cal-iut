"""Défauts révélés par les premiers essais sur le VRAI Celcat (02/10/2026).

Signalement d'origine : docs/A-TESTER-SUR-CELCAT.md — règles d'envoi
(WR100BU, PTUT) et occupations hors MMI, écrites sans accès à Celcat, puis
essayées en lecture seule sur `URCA_2026` depuis le conteneur du robot
(VPN OpenConnect). Ce que ces essais ont montré, et que ces tests figent :

- connexion : la liste des rôles arrive par un appel réseau ; Celcat lent
  (accueil chargé en 44 s), le rôle était cherché avant d'être affiché ;
- `cal-iut celcat-reseau --connecter` annonçait « accès via le VPN : NON »
  sur un tunnel bon six secondes plus tard ;
- une séance envoyée par une règle (remarque « WR100BU - <id> », catégorie
  « TD0 ») ou dont l'identifiant porte des minuscules n'était pas reconnue
  comme nôtre par sa remarque ;
- le département « T_ CJ T41 » (avec une espace) gardait son nom complet ;
- les jours fériés, renvoyés par Celcat avec CHAQUE chargement et sans
  salle ni enseignant, étaient comptés « non attribué » une fois par lot.

Données inventées, sur la forme des réponses constatée ce jour-là
(`room_id` / `staff_id` dans les sous-objets, `deptName`, heures en UTC
dans le conteneur).
"""

from __future__ import annotations

import argparse
from datetime import date

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import occupations as occ
from cal_iut.celcat import reseau

# ── Connexion quand Celcat est lent ─────────────────────────────────────


class _Souris:
    def __init__(self, page: "_PageConnexion") -> None:
        self.page = page

    def click(self, x: int, y: int) -> None:
        self.page.clic(x, y)


class _Clavier:
    def __init__(self, page: "_PageConnexion") -> None:
        self.page = page

    def type(self, texte: str, delay: int = 0) -> None:
        self.page.saisies.append(texte)


class _PageConnexion:
    """L'écran de connexion de Celcat, avec une horloge simulée : les rôles
    n'apparaissent que `delai_roles_ms` après l'ouverture du déroulant."""

    POSITIONS = {
        "URCA_2026": (100, 100), "Connexion": (100, 200), "par défaut": (300, 300),
        "985_consultation": (300, 340), "985_T_MMI": (300, 380), "OK": (300, 500),
    }

    def __init__(self, delai_roles_ms: int, accueils_sans_bases: int = 0) -> None:
        self.delai_roles_ms = delai_roles_ms
        self.accueils_sans_bases = accueils_sans_bases
        self.chargements = 0
        self.t = 0
        self.etape = "accueil"
        self.roles_a: int | None = None
        self.role_choisi: str | None = None
        self.saisies: list[str] = []
        self.mouse = _Souris(self)
        self.keyboard = _Clavier(self)

    def goto(self, *_a, **_k) -> None:
        self.chargements += 1

    def wait_for_timeout(self, ms: int) -> None:
        self.t += ms

    def _textes(self) -> list[str]:
        if self.etape == "accueil":
            if self.chargements <= self.accueils_sans_bases:
                return ["Bienvenue dans Celcat Timetabler Live"]
            return ["URCA_2026", "Connexion"]
        if self.etape == "formulaire":
            textes = ["par défaut", "OK"]
            if self.roles_a is not None and self.t >= self.roles_a:
                textes += ["985_consultation", "985_T_MMI"]
            return textes
        return ["Déconnexion"]

    def evaluate(self, js: str, arg=None):
        if js == nav._JS_FEUILLES:
            return [{"texte": t, "x": self.POSITIONS[t][0], "y": self.POSITIONS[t][1]}
                    for t in self._textes() if t in self.POSITIONS]
        return [{"type": "text", "x": 500, "y": 300}, {"type": "password", "x": 500, "y": 340}]

    def clic(self, x: int, y: int) -> None:
        visible = {self.POSITIONS[t]: t for t in self._textes() if t in self.POSITIONS}
        texte = visible.get((x, y))
        if texte == "Connexion":
            self.etape = "formulaire"
        elif texte == "par défaut":
            self.roles_a = self.t + self.delai_roles_ms
        elif texte in ("985_consultation", "985_T_MMI"):
            self.role_choisi = texte
        elif texte == "OK":
            self.etape = "connecte"


def test_la_connexion_attend_que_le_role_soit_affiche(monkeypatch) -> None:
    monkeypatch.setenv("CELCAT_URL", "https://celcat.invalid/")
    monkeypatch.setenv("CELCAT_UTILISATEUR", "utilisateur")
    monkeypatch.setenv("CELCAT_MOT_DE_PASSE", "secret")
    page = _PageConnexion(delai_roles_ms=6000)  # `login.getRoles` met 6 s à répondre

    nav.connexion(page, base="URCA_2026", role=nav.ROLE_LECTURE)

    assert page.role_choisi == "985_consultation"
    assert page.etape == "connecte"


def test_la_connexion_recharge_l_accueil_quand_la_liste_des_bases_ne_vient_pas(monkeypatch) -> None:
    """Celcat lent : une fois sur trois, l'accueil se chargeait SANS la liste
    des bases, et elle ne venait plus (« texte jamais affiché : 'URCA_2026' »,
    cinq fois le 02/10/2026). Un rechargement suffisait à chaque fois."""
    monkeypatch.setenv("CELCAT_URL", "https://celcat.invalid/")
    monkeypatch.setenv("CELCAT_UTILISATEUR", "utilisateur")
    monkeypatch.setenv("CELCAT_MOT_DE_PASSE", "secret")
    page = _PageConnexion(delai_roles_ms=0, accueils_sans_bases=1)
    monkeypatch.setattr(nav.time, "time", lambda: page.t / 1000)  # l'horloge suit les attentes simulées

    nav.connexion(page, base="URCA_2026", role=nav.ROLE_LECTURE)

    assert page.chargements == 2
    assert page.etape == "connecte"


def test_la_connexion_renonce_apres_trois_accueils_sans_bases(monkeypatch) -> None:
    import pytest

    monkeypatch.setenv("CELCAT_URL", "https://celcat.invalid/")
    page = _PageConnexion(delai_roles_ms=0, accueils_sans_bases=99)
    monkeypatch.setattr(nav.time, "time", lambda: page.t / 1000)

    with pytest.raises(TimeoutError, match="URCA_2026"):
        nav.connexion(page, base="URCA_2026", role=nav.ROLE_LECTURE)
    assert page.chargements == 3


def test_la_connexion_reste_immediate_quand_le_role_est_deja_la(monkeypatch) -> None:
    monkeypatch.setenv("CELCAT_URL", "https://celcat.invalid/")
    monkeypatch.setenv("CELCAT_UTILISATEUR", "utilisateur")
    monkeypatch.setenv("CELCAT_MOT_DE_PASSE", "secret")
    page = _PageConnexion(delai_roles_ms=0)

    nav.connexion(page, base="URCA_2026", role=nav.ROLE_ECRITURE)

    assert page.role_choisi == "985_T_MMI"
    assert page.t < 20_000, "pas d'attente ajoutée quand tout est déjà affiché"


# ── `cal-iut celcat-reseau --connecter` ──────────────────────────────────


def test_celcat_reseau_connecter_attend_le_dns_du_tunnel(monkeypatch, capsys) -> None:
    """openconnect rend la main dès le tunnel établi ; le DNS et les routes
    suivent quelques secondes après (`reseau.attendre_acces`). Vérifier dans
    la foulée annonçait « NON », code 1, sur un VPN parfaitement monté."""
    from cal_iut import cli

    verifications = iter([
        reseau.Diagnostic(False, "ne résout pas", vpn_monte=False),  # avant montage
        reseau.Diagnostic(False, "ne résout pas", vpn_monte=False),  # juste après : DNS pas encore posé
        reseau.Diagnostic(False, "ne résout pas", vpn_monte=False),
        reseau.Diagnostic(True, "celcat:443 répond.", vpn_monte=True),
    ])
    monkeypatch.setenv("CELCAT_URL", "https://celcat.invalid/")
    monkeypatch.setattr(reseau, "client_disponible", lambda: ("openconnect", "/usr/sbin/openconnect"))
    monkeypatch.setattr(reseau, "etat_vpn", lambda: "déconnecté")
    monkeypatch.setattr(reseau, "verifier", lambda url, **k: next(verifications))
    monkeypatch.setattr(reseau, "connecter", lambda **k: reseau.Diagnostic(True, "VPN monté.", vpn_monte=True))
    monkeypatch.setattr(reseau.time, "sleep", lambda _s: None)

    code = cli.cmd_celcat_reseau(argparse.Namespace(url=None, connecter=True))

    sortie = capsys.readouterr().out
    assert code == 0
    assert "accès via le VPN  : OK" in sortie


# ── Occupations hors MMI ─────────────────────────────────────────────────

SALLE_A, SALLE_B = 1_700_001, 1_700_002


def _evenement(**champs) -> dict:
    base = {
        "event_id": 1_990_001, "day_of_week": 0,
        "start_time": "1899-12-31T08:00:00.000Z", "end_time": "1899-12-31T09:30:00.000Z",
        "evCatName": "[TD]", "event_cat_id": 433, "dept_id": 610_029, "deptName": "T_MMI T29",
        "rooms": [{"room_id": SALLE_A, "name": "Salle A", "unique_name": "A"}],
        "modules": [], "staff": [], "groups": [],
        "weeks": "N" * 6 + "Y" + "N" * 47, "protected": "N", "global_event": "N", "suspended": "N", "notes": None,
    }
    return {**base, **champs}


def test_le_sigle_d_un_departement_ecrit_avec_une_espace() -> None:
    assert occ.libelle_departement("T_ CJ T41") == "CJ"
    assert occ.libelle_departement("T_TC T32") == "TC"
    assert occ.libelle_departement("R_CS R14") == "CS"
    assert occ.libelle_departement("iut Troyes T00") == "iut Troyes T00", "un nom d'une autre forme reste tel quel"


def test_une_seance_envoyee_par_une_regle_est_reconnue_par_sa_remarque() -> None:
    """WR100BU part en « TD0 » (pas une catégorie de cours) avec la remarque
    « WR100BU - <identifiant> ». Sans le journal (poste de l'admin, journal
    perdu), elle était comptée comme occupation EXTERNE de sa propre salle."""
    brut = _evenement(evCatName="TD0", event_cat_id=465, notes="WR100BU - WR100BU-S1-TD-1-but1-td-ab",
                      groups=[{"group_id": 1, "name": "BUT MMI S1 TD AB - 2024"}])
    assert occ.motif_a_nous(brut, occ.ContexteNous(), occ.ConfigOccupations()) == "écrit par cal-iut (notes)"

    ptut = _evenement(evCatName="Projet", event_cat_id=456, notes="PTUT - WR101-S1-TD-1-but1-td-ab")
    assert occ.motif_a_nous(ptut, occ.ContexteNous(), occ.ConfigOccupations()) == "écrit par cal-iut (notes)"


def test_la_remarque_d_une_regle_ne_contient_que_de_l_ascii() -> None:
    """Canari WR100BU du 02/10/2026 dans URCA_FORMATION : la remarque
    « WR100BU — <identifiant> » a été relue « WR100BU â€” <identifiant> ».
    Celcat abîme le tiret long à l'écriture, et l'identifiant n'était plus
    retrouvé dans la remarque. Le séparateur est donc en ASCII, et la
    lecture prend le dernier mot, quelle que soit la forme."""
    from cal_iut.celcat.mapping import SEPARATEUR_REMARQUE, session_id_depuis_notes

    ident = "WR100BU-S1-TD-1-but1-td-ab"
    assert SEPARATEUR_REMARQUE.isascii()
    assert session_id_depuis_notes(f"WR100BU{SEPARATEUR_REMARQUE}{ident}") == ident
    assert session_id_depuis_notes(f"WR100BU â€” {ident}") == ident, "ce que Celcat a gardé du canari"
    assert session_id_depuis_notes(f"WR100BU — {ident}") == ident
    assert session_id_depuis_notes(ident) == ident
    assert session_id_depuis_notes("") == "" and session_id_depuis_notes(None) == ""


def test_un_identifiant_de_seance_en_minuscules_est_reconnu() -> None:
    brut = _evenement(evCatName="Réunion", notes="WR305D-S3-TD-1-but2-dev-fi-td-cd", deptName=None, dept_id=None)
    assert occ.motif_a_nous(brut, occ.ContexteNous(), occ.ConfigOccupations()) == "écrit par cal-iut (notes)"


def test_une_remarque_libre_n_est_pas_prise_pour_un_identifiant() -> None:
    for notes in ("Réunion expertise n°3", "Réservation Amphi H MMI", "TD - salle à confirmer"):
        brut = _evenement(evCatName="Réunion", notes=notes, deptName="T_TC T32", dept_id=610_032)
        assert occ.motif_a_nous(brut, occ.ContexteNous(), occ.ConfigOccupations()) is None, notes


def test_les_jours_feries_sont_comptes_une_fois_et_sous_leur_nom() -> None:
    """Celcat renvoie les évènements globaux (jours fériés) avec chaque
    chargement, sans salle ni enseignant. Lus par lots, ils tombaient dans
    « non attribué », une fois par lot (× 88 au relevé complet du 02/10/2026),
    ce qui ressemblait à un défaut d'attribution."""
    ferie = _evenement(event_id=1_665_591, evCatName="Jour férié", event_cat_id=451, rooms=[], deptName=None,
                       dept_id=None, global_event="Y", protected="Y", weeks="Y" * 54,
                       start_time="1899-12-31T07:00:00.000Z", end_time="1899-12-31T19:00:00.000Z")
    cours_tc = _evenement(event_id=1_990_002, deptName="T_TC T32", dept_id=610_032,
                          rooms=[{"room_id": SALLE_B, "name": "Salle B", "unique_name": "B"}])
    page = occ.PageSimulee({
        "ressources": {"604": [{"room_id": SALLE_A, "name": "Salle A", "unique_name": "A"},
                               {"room_id": SALLE_B, "name": "Salle B", "unique_name": "B"}]},
        "evenements": [ferie, cours_tc],
    })
    ressources = [occ.RessourceSurveillee("salle", "a", "Salle A"), occ.RessourceSurveillee("salle", "b", "Salle B")]
    for lot in (1, 10):
        for r in ressources:
            r.trouvee, r.celcat_id = False, None
        res = occ.relever(page, occ.ConfigOccupations(pause_s=0, lot=lot), ressources, ctx=occ.ContexteNous(),
                          du=date(2026, 9, 28), au=date(2027, 7, 31), journal=lambda _l: None)
        assert res.ignores == {"jour férié": 1}, f"lot de {lot}"
        assert [(e["code"], e["departement"]) for e in res.evenements] == [("b", "TC")], f"lot de {lot}"


def test_la_reservation_de_l_amphi_par_mmi_n_est_pas_une_occupation_externe() -> None:
    """Relevé réel du 02/10/2026 : cinq évènements « Réservation Amphi H MMI »
    (département T_MMI T29, sans catégorie, groupe, enseignant ni matière,
    8h00–20h00 du lundi au vendredi, 22 semaines) donnaient 110 des 129
    occupations de H.018. L'amphi aurait été interdit à nos propres CM tout
    le second semestre. C'est MMI qui garde SA salle : ce n'est pas une
    occupation « hors MMI ». Une vraie activité (catégorie posée) compte."""
    cfg = occ.ConfigOccupations()
    reservation = _evenement(evCatName=None, event_cat_id=None, notes="Réservation Amphi H MMI", protected="Y",
                             start_time="1899-12-31T08:00:00.000Z", end_time="1899-12-31T20:00:00.000Z")
    assert occ.motif_a_nous(reservation, occ.ContexteNous(), cfg) == "réservation du département MMI"
    # Reconnu aussi par l'identifiant du département, quand `deptName` manque.
    sans_nom = {**reservation, "deptName": None}
    assert occ.motif_a_nous(sans_nom, occ.ContexteNous(depts_mmi_ids={610_029}), cfg) == "réservation du département MMI"

    reunion_mmi = _evenement(evCatName="Réunion", event_cat_id=460, notes="Conseil de département")
    assert occ.motif_a_nous(reunion_mmi, occ.ContexteNous(), cfg) is None, "une activité MMI saisie à la main compte"
    autre_departement = {**reservation, "deptName": "T_TC T32", "dept_id": 610_032}
    assert occ.motif_a_nous(autre_departement, occ.ContexteNous(), cfg) is None
    sans_departement = {**reservation, "deptName": None, "dept_id": None, "notes": "Réunion expertise n°3"}
    assert occ.motif_a_nous(sans_departement, occ.ContexteNous(), cfg) is None
    # Un évènement MMI avec un enseignant et une autre remarque est une vraie
    # activité. (La réservation elle-même, reconnue par sa remarque, reste
    # ignorée même avec un responsable : « en aucun cas ça nous bloque »,
    # Jules, 02/10/2026 — `test_occupations_releve_reel_2026_10_02.py`.)
    avec_enseignant = {**reservation, "notes": "Soutenances",
                       "staff": [{"staff_id": 1, "name": "X", "unique_name": "1"}]}
    assert occ.motif_a_nous(avec_enseignant, occ.ContexteNous(), cfg) is None

    assert occ.motif_a_nous(reservation, occ.ContexteNous(), occ.ConfigOccupations(reservations_mmi_ignorees=False)) is None
