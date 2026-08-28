"""Le remplissage automatique du reliquat.

Ce module pose des séances dans un planning que le solveur a laissé incomplet.
C'est une porte de plus vers le planning, donc un risque de plus : il doit
refuser tout ce que le solveur refuse, et ne jamais défaire ce qui est en
place.

Trois familles de propriétés, dans l'ordre de gravité :

1. **Il ne casse rien** — aucune séance déjà posée n'est déplacée, aucune règle
   de calendrier n'est enfreinte.
2. **Il respecte ce que la validation manuelle ne couvre pas** — bornes de
   début/fin de cours, fenêtres de dates, plafond hebdomadaire de la cohorte.
   Sans ces contrôles, il pourrait poser WRA507D en mars alors qu'une règle
   exige janvier.
3. **Il choisit bien** — le créneau retenu est celui qui coûte le moins à
   l'étudiant, pas le premier venu ; sinon il remplit le semestre par le début
   en semant des trous.
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.completion import _trous, completer_placements
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
GROUPES = load_groups(CONFIG)
CAL = build_default_calendar_2026_2027()
GROUPE = "but1-td-ab"


def _seance(sid: str, duree: int = 1, code: str = "WR101") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="Test", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=[GROUPE], teacher_codes=["MRI"],
        duration_slots=duree,
    )


def _place(sid: str, week: int, day: int, slot: int) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=sid, week=week, day=day, slot=slot, course_code="WR101",
        group_ids=[GROUPE], teacher_codes=["MRI"],
    )


def _lancer(sessions, placements, candidats_par_seance, plafond=23):
    """Exécute le remplissage avec des créneaux candidats fournis d'avance.

    Les créneaux viennent de l'appelant (dans l'application, de la même
    recherche que le glisser-déposer) : on peut donc éprouver la logique de
    décision sans dépendre de tout le contexte de l'API.
    """
    poses: list[tuple[str, int, int, int]] = []

    def _poser(session, w, d, sl):
        poses.append((session.id, w, d, sl))
        placements.append(PlacedSessionWithRoom(
            session_id=session.id, week=w, day=d, slot=sl,
            course_code=session.course_code, group_ids=list(session.group_ids),
            teacher_codes=list(session.teacher_codes),
        ))
        return True

    rapport = completer_placements(
        sessions=sessions, placements=placements, groups=GROUPES, calendar=CAL,
        semestre_par_defaut="S1", config_dir=CONFIG, teacher_availability=[],
        contexte_dur=lambda s: (set(), set()),
        creneaux_candidats=lambda s: candidats_par_seance.get(s.id, []),
        poser=_poser, plafond_cohorte=plafond,
    )
    return rapport, poses


# ==========================================================================
# 1. Il ne casse rien
# ==========================================================================


def test_aucune_seance_deja_placee_n_est_touchee():
    """Il complète, il ne réarrange pas — c'est le rôle de la régénération."""
    deja = [_place("a", 10, 0, 0), _place("b", 10, 0, 1)]
    avant = [(p.session_id, p.week, p.day, p.slot) for p in deja]
    sessions = [_seance("a"), _seance("b"), _seance("c")]

    _lancer(sessions, deja, {"c": [(11, 1, 0)]})

    apres = {p.session_id: (p.week, p.day, p.slot) for p in deja}
    for sid, w, d, sl in avant:
        assert apres[sid] == (w, d, sl), f"{sid} a été déplacée"


def test_un_planning_deja_complet_ne_declenche_rien():
    deja = [_place("a", 10, 0, 0)]
    rapport, poses = _lancer([_seance("a")], deja, {})
    assert poses == []
    assert rapport.placees == [] and rapport.refusees == []
    assert "déjà placées" in rapport.resume()


def test_une_seance_sans_aucun_creneau_est_rendue_avec_son_motif():
    """Un rapport qui n'annoncerait que ses succès laisserait croire le
    planning complet — exactement le défaut qu'il corrige."""
    deja = [_place("a", 10, 0, 0)]
    rapport, poses = _lancer([_seance("a"), _seance("b")], deja, {"b": []})
    assert poses == []
    assert len(rapport.refusees) == 1
    assert rapport.refusees[0].session_id == "b"
    assert "régénération" in rapport.refusees[0].raison


# ==========================================================================
# 2. Les règles que la validation manuelle ne couvre pas
# ==========================================================================


def test_le_plafond_hebdomadaire_de_la_cohorte_n_est_jamais_depasse():
    """23 créneaux par semaine, c'est ce qu'un étudiant peut réellement suivre."""
    deja = [_place(f"p{i}", 10, i % 5, i // 5) for i in range(23)]
    sessions = [_seance(f"p{i}") for i in range(23)] + [_seance("trop")]

    rapport, poses = _lancer(sessions, deja, {"trop": [(10, 0, 5)]})

    assert poses == [], "le plafond hebdomadaire a été dépassé"
    assert "plafond" in rapport.refusees[0].raison


def test_un_bloc_compte_pour_sa_duree_dans_le_plafond():
    """Un bloc de 3h occupe deux créneaux : le compter pour un laisserait
    passer une semaine réellement surchargée."""
    deja = [_place(f"p{i}", 10, i % 5, i // 5) for i in range(22)]
    sessions = [_seance(f"p{i}") for i in range(22)] + [_seance("bloc", duree=2)]

    _, poses = _lancer(sessions, deja, {"bloc": [(10, 0, 3)]})

    assert poses == [], "22 + un bloc de 2 = 24, au-dessus du plafond de 23"


def test_un_bloc_ne_deborde_jamais_de_la_journee():
    """Un bloc de 3h posé sur le dernier créneau finirait à 20h."""
    sessions = [_seance("bloc", duree=2)]
    _, poses = _lancer(sessions, [_place("x", 10, 0, 0)] , {"bloc": [(11, 0, 5)]})
    assert poses == []


def test_les_bornes_de_fin_de_cours_sont_respectees():
    """WRA507D doit se terminer « environ en janvier » (`max_week_rules`).

    Le glisser-déposer ne vérifie pas cette règle : sans ce contrôle, le
    remplissage automatique poserait la séance en mars sans le moindre
    avertissement.
    """
    from cal_iut.ingestion.config_loader import load_course_max_week_rules

    regles = load_course_max_week_rules(CONFIG)
    regle = next((r for r in regles if r.course_code == "WRA507D"), None)
    assert regle is not None, "la règle de fin WRA507D a disparu de la configuration"

    seance = SessionToPlace(
        id="tardive", course_code=regle.course_code, course_name="T",
        semestre=regle.semestre, parcours="BUT3-DEV-FC", annee="BUT3",
        session_type=SessionType.TD, sequence_order=1,
        group_ids=[GROUPE], teacher_codes=["BTO"],
    )
    # Un seul créneau candidat, au-delà de la borne.
    apres_la_borne = regle.max_week + 3
    deja = [_place("ancre", apres_la_borne + 2, 0, 0)]
    rapport, poses = _lancer([seance], deja, {"tardive": [(apres_la_borne, 0, 0)]})

    assert poses == [], "séance posée au-delà de la borne de fin du cours"
    assert "période autorisée" in rapport.refusees[0].raison


# ==========================================================================
# 3. Il choisit le créneau le moins coûteux
# ==========================================================================


def test_le_creneau_choisi_se_colle_aux_cours_existants():
    """Prendre le premier créneau libre remplirait le semestre par le début en
    semant des trous : la séance atterrit à 8h alors que la cohorte commence à
    11h ce jour-là."""
    deja = [_place("a", 10, 0, 2), _place("b", 10, 0, 3)]
    sessions = [_seance("a"), _seance("b"), _seance("c")]

    # Trois créneaux également valides : à 8h (deux trous), à 12h30… non, à
    # 14h30 (collé), et un autre jour (journée créée de toutes pièces).
    _, poses = _lancer(sessions, deja, {"c": [(10, 0, 0), (10, 0, 4), (10, 1, 0)]})

    assert poses[0][1:] == (10, 0, 4), f"créneau retenu : {poses[0]}"


def test_une_journee_creee_de_toutes_pieces_est_evitee_si_possible():
    """Se déplacer pour une seule séance d'1h30 est le pire des résultats."""
    deja = [_place("a", 10, 0, 0)]
    sessions = [_seance("a"), _seance("c")]

    _, poses = _lancer(sessions, deja, {"c": [(10, 3, 0), (10, 0, 1)]})

    assert poses[0][1:] == (10, 0, 1), "une journée isolée a été préférée"


def test_le_dernier_creneau_de_la_journee_est_evite_a_egalite():
    deja = [_place("a", 10, 0, 0), _place("b", 10, 0, 1)]
    sessions = [_seance("a"), _seance("b"), _seance("c")]

    # 17h-18h30 (slot 5) crée autant de trous qu'un autre créneau isolé, mais
    # coûte davantage à l'étudiant.
    _, poses = _lancer(sessions, deja, {"c": [(10, 0, 5), (10, 0, 2)]})

    assert poses[0][3] == 2


def test_les_seances_les_plus_contraintes_passent_en_premier():
    """Sinon la séance qui n'avait qu'un seul créneau se le fait prendre par
    une autre qui en avait trente."""
    deja = [_place("ancre", 10, 0, 0)]
    sessions = [_seance("ancre"), _seance("facile"), _seance("difficile")]
    creneaux = {
        "facile": [(11, 0, 0), (11, 0, 1), (11, 1, 0)],
        "difficile": [(11, 0, 0)],
    }
    _, poses = _lancer(sessions, deja, creneaux)
    assert poses[0][0] == "difficile", f"ordre de traitement : {[p[0] for p in poses]}"


def test_deux_executions_identiques_donnent_le_meme_planning():
    """Un départage instable rendrait tout diagnostic impossible."""
    resultats = []
    for _ in range(3):
        deja = [_place("a", 10, 0, 2)]
        sessions = [_seance("a"), _seance("c")]
        _, poses = _lancer(sessions, deja, {"c": [(10, 0, 0), (10, 0, 3), (11, 0, 3)]})
        resultats.append(poses)
    assert resultats[0] == resultats[1] == resultats[2]


# ==========================================================================
# Le calcul des trous, isolé
# ==========================================================================


def test_le_calcul_des_trous_ne_compte_que_les_creneaux_intercales():
    assert _trous(set()) == 0
    assert _trous({3}) == 0
    assert _trous({0, 1, 2}) == 0
    assert _trous({0, 2}) == 1
    assert _trous({0, 5}) == 4


# ==========================================================================
# Ordre de TRAITEMENT : les prédécesseurs avant leurs successeurs
# ==========================================================================


def test_une_seance_est_traitee_avant_son_successeur_meme_manquant():
    """Cas trouvé le 27/08/2026 sur le run réel (cours WS107) : deux séances
    liées, TOUTES LES DEUX manquantes. Sans ordre topologique, la suivante
    pouvait être traitée EN PREMIER (moins de candidats à cet instant),
    n'ayant alors aucune information sur sa propre précédente — les bornes ne
    savent contraindre que contre des séances DÉJÀ posées."""
    premiere = _seance("premiere", code="WR107")
    premiere.sequence_order = 1
    suivante = _seance("suivante", code="WR107")
    suivante.sequence_order = 2

    # La suivante a délibérément PLUS de candidats que la précédente, pour que
    # l'ancien tri (uniquement par nombre de candidats) l'aurait traitée en
    # premier — précisément le scénario qui cassait l'ordre.
    creneaux = {
        "premiere": [(10, 0, 0)],
        "suivante": [(9, 0, 0), (10, 0, 1), (11, 0, 0), (12, 0, 0), (13, 0, 0)],
    }
    deja = [_place("ancre", 15, 0, 0)]  # établit l'horizon, cf. autres tests de ce module
    _, poses = _lancer([premiere, suivante], deja, creneaux)

    ordre_traitement = [sid for sid, *_ in poses]
    assert ordre_traitement.index("premiere") < ordre_traitement.index("suivante")

    par_id = {sid: (w, d, sl) for sid, w, d, sl in poses}
    assert par_id["suivante"][0] >= par_id["premiere"][0], (
        f"suivante en semaine {par_id['suivante'][0]}, premiere en semaine {par_id['premiere'][0]}"
    )


def test_une_chaine_de_trois_seances_manquantes_reste_dans_l_ordre():
    a = _seance("a", code="WR107"); a.sequence_order = 1
    b = _seance("b", code="WR107"); b.sequence_order = 2
    c = _seance("c", code="WR107"); c.sequence_order = 3
    creneaux = {
        "a": [(10, 0, 0)],
        "b": [(9, 0, 0), (10, 0, 0), (11, 0, 0)],
        "c": [(9, 0, 0), (10, 0, 0), (11, 0, 0), (12, 0, 0)],
    }
    deja = [_place("ancre", 15, 0, 0)]
    _, poses = _lancer([c, b, a], deja, creneaux)  # ordre d'entrée volontairement inversé
    ordre = [sid for sid, *_ in poses]
    assert ordre.index("a") < ordre.index("b") < ordre.index("c")


# ==========================================================================
# 4. Les SAE non planifiées par le solveur ne sont jamais complétées
# ==========================================================================


def test_une_sae_non_planifiee_par_le_solveur_n_est_jamais_completee():
    """Bug réel corrigé le 27/08/2026 (retour utilisateur, Kyllian Bresson :
    « les WS ne sont pas à placer, ce sera les enseignants qui les placeront
    pendant les périodes assignées ») : une SAE au préfixe "WS" (sauf
    `solver_scheduled_sae`, ex. WSA501D) n'a pas de créneau à choisir — sa
    date vient du calendrier officiel, jamais du remplissage automatique.
    221 séances de ce type se sont retrouvées posées sur des dates sans
    rapport avec leur fenêtre SAE réelle avant ce correctif."""
    sae_non_planifiee = _seance("sae-non-planifiee", code="WS107")
    sae_non_planifiee.sequence_order = 1
    creneaux = {"sae-non-planifiee": [(10, 0, 0), (11, 0, 0)]}
    deja = [_place("ancre", 15, 0, 0)]

    rapport, poses = _lancer([sae_non_planifiee], deja, creneaux)
    assert poses == [], "une SAE non planifiée par le solveur n'a jamais de créneau à choisir"


def test_une_sae_planifiee_par_le_solveur_reste_completee_normalement():
    """Symétrique : `solver_scheduled_sae` (ex. WSA501D) redevient une séance
    ordinaire, complétable comme n'importe quel cours."""
    sae_planifiee = _seance("sae-planifiee", code="WSA501D")
    sae_planifiee.semestre = "S5"
    sae_planifiee.sequence_order = 1
    creneaux = {"sae-planifiee": [(10, 0, 0)]}
    deja = [_place("ancre", 15, 0, 0)]

    _, poses = _lancer([sae_planifiee], deja, creneaux)
    assert [sid for sid, *_ in poses] == ["sae-planifiee"]
