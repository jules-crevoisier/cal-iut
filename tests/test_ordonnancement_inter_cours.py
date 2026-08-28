"""L'ordonnancement ENTRE cours différents (`metadata["ordonnancement"]`),
absent de `_build_sequence_neighbors` jusqu'au 27/08/2026.

Deux sources y figuraient déjà : la séquence propre à un cours
(`sequence_order`) et les paires inter-granularités d'une cohorte
(`cohort_sequence_pairs`, CM promo ↔ TD sous-groupe). Une troisième source
existe pourtant côté solveur — la relation « ce cours doit être entièrement
fini avant que cet autre commence » (`add_ordonnancement_constraints`, une
contrainte DURE) — et elle n'était répliquée NULLE PART côté API/rééquilibrage.

Conséquence mesurée sur le run réel du 26/08/2026 : le module de complétion
automatique, qui s'appuie sur `_movable_bounds` (donc sur `neighbors`) pour ne
proposer que des créneaux valables, plaçait des séances SANS AUCUNE
connaissance de cette relation. Le chevauchement inter-matières est passé de
495 à 993 semaines cumulées après complétion — exactement le défaut initial
signalé en tête de ce chantier (« des exemples de matière qui devait être
finie pour commencer »).
"""

from __future__ import annotations

from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import _build_sequence_neighbors, _movable_bounds


def _seance(sid, code, groupe, ordre=1, metadata=None):
    return SessionToPlace(
        id=sid, course_code=code, course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=ordre, group_ids=[groupe], teacher_codes=["MRI"],
        metadata=metadata or {},
    )


def _relation(position: str, target: str, semestre: str = "S1"):
    return {"position": position, "target_course_code": target, "semestre": semestre}


# ==========================================================================
# La relation devient un voisin, dans le bon sens
# ==========================================================================


def test_before_ajoute_la_cible_comme_successeur_de_la_source():
    """WR101 « before » WR103 : chaque séance WR101 doit précéder WR103."""
    a = _seance("a", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "g")
    voisins = _build_sequence_neighbors([a, b])
    preds_b, succs_a = voisins["b"][0], voisins["a"][1]
    assert "a" in preds_b, "WR103 devrait avoir WR101 comme prédécesseur"
    assert "b" in succs_a, "WR101 devrait avoir WR103 comme successeur"


def test_after_ajoute_la_cible_comme_predecesseur_de_la_source():
    """WR103 « after » WR101 : sémantique inverse de « before »."""
    a = _seance("a", "WR103", "g", metadata={"ordonnancement": [_relation("after", "WR101")]})
    b = _seance("b", "WR101", "g")
    voisins = _build_sequence_neighbors([a, b])
    assert "b" in voisins["a"][0], "WR103 devrait avoir WR101 comme prédécesseur (after)"
    assert "a" in voisins["b"][1], "WR101 devrait avoir WR103 comme successeur (after)"


def test_seul_le_groupe_partage_est_lie():
    """Sans groupe brut commun, la relation ne doit rien contraindre ici —
    même repli que le solveur (`add_ordonnancement_constraints`)."""
    a = _seance("a", "WR101", "groupe-x", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "groupe-y")
    voisins = _build_sequence_neighbors([a, b])
    assert voisins["a"] == ([], [])
    assert voisins["b"] == ([], [])


def test_une_relation_sans_cours_cible_dans_les_donnees_est_ignoree_sans_planter():
    a = _seance("a", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR999")]})
    voisins = _build_sequence_neighbors([a])
    assert voisins["a"] == ([], [])


def test_plusieurs_seances_de_chaque_cote_sont_toutes_liees():
    """max(source) < min(target) pour TOUTE paire — pas seulement les voisins
    immédiats — sinon la borne calculée par `_movable_bounds` serait fausse
    dès que plus de deux séances existent de chaque côté."""
    a1 = _seance("a1", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    a2 = _seance("a2", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b1 = _seance("b1", "WR103", "g")
    b2 = _seance("b2", "WR103", "g")
    voisins = _build_sequence_neighbors([a1, a2, b1, b2])
    assert set(voisins["a1"][1]) == {"b1", "b2"}
    assert set(voisins["a2"][1]) == {"b1", "b2"}
    assert set(voisins["b1"][0]) == {"a1", "a2"}
    assert set(voisins["b2"][0]) == {"a1", "a2"}


# ==========================================================================
# La borne calculée par `_movable_bounds` en tient compte
# ==========================================================================


def test_movable_bounds_interdit_la_source_apres_la_cible_deja_placee():
    """Le cas dominant du run réel : WR103 (target) déjà placé en semaine 6,
    WR101 (source, « before ») ne doit pas pouvoir déborder au-delà.

    Bornée à la SEMAINE (`<=`), pas à l'instant précis (`<`) : les deux cours
    peuvent légitimement partager une semaine, l'ordre fin (jour/créneau) au
    sein de cette semaine n'est pas du ressort de `_movable_bounds` — c'est la
    même granularité que les deux autres sources déjà en place.
    """
    a = _seance("a", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "g")
    voisins = _build_sequence_neighbors([a, b])
    lo, hi = _movable_bounds("a", voisins, {"b": 6}, weeks=24)
    assert hi <= 6, f"WR101 pourrait encore être placé semaine {hi}, après WR103 (semaine 6)"
    # Sans la coupe, cette borne serait restée (0, 23) : la relation doit
    # RÉELLEMENT restreindre l'intervalle, pas juste ne pas l'élargir.
    assert hi < 23


def test_movable_bounds_interdit_la_cible_avant_la_source_deja_placee():
    a = _seance("a", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "g")
    voisins = _build_sequence_neighbors([a, b])
    lo, hi = _movable_bounds("b", voisins, {"a": 6}, weeks=24)
    assert lo >= 6, f"WR103 pourrait encore être placé semaine {lo}, avant WR101 (semaine 6)"
    assert lo > 0


def test_deux_seances_manquantes_simultanement_restent_libres():
    """Ni l'une ni l'autre n'est encore placée : aucune borne réelle — le
    même patron d'auto-correction que les deux autres sources (les deux
    finissent par se contraindre l'une l'autre dès que l'une des deux est
    posée)."""
    a = _seance("a", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "g")
    voisins = _build_sequence_neighbors([a, b])
    lo, hi = _movable_bounds("a", voisins, {}, weeks=24)
    assert (lo, hi) == (0, 23)


# ==========================================================================
# Les deux sources déjà existantes ne sont pas cassées par l'ajout
# ==========================================================================


def test_la_sequence_propre_au_cours_fonctionne_toujours():
    a = _seance("a", "WR101", "g", ordre=1)
    b = _seance("a2", "WR101", "g", ordre=2)
    voisins = _build_sequence_neighbors([a, b])
    assert voisins["a"][1] == ["a2"]
    assert voisins["a2"][0] == ["a"]


def test_les_deux_sources_se_cumulent_sur_une_meme_seance():
    """Une séance peut être à la fois la suite de son propre cours ET la
    cible d'une relation inter-cours : les deux doivent coexister."""
    a1 = _seance("a1", "WR101", "g", ordre=1)
    a2 = _seance("a2", "WR101", "g", ordre=2, metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "g")
    voisins = _build_sequence_neighbors([a1, a2, b])
    assert "a2" in voisins["b"][0]
    assert "a1" in voisins["a2"][0]


def test_include_ordonnancement_false_desactive_la_troisieme_source():
    """Trouvé le 27/08/2026 en réparant un run réel : combiner la borne
    inter-cours (souple côté solveur) à la borne même-cours peut produire un
    [lo,hi] impossible (lo > hi) alors qu'aucune des deux prise seule n'est en
    violation dure. `include_ordonnancement=False` retombe aux deux sources
    d'origine, jamais suffisantes SEULES pour créer une fenêtre vide."""
    a = _seance("a", "WR101", "g", metadata={"ordonnancement": [_relation("before", "WR103")]})
    b = _seance("b", "WR103", "g")

    avec = _build_sequence_neighbors([a, b])
    assert "b" in avec["a"][1]

    sans = _build_sequence_neighbors([a, b], include_ordonnancement=False)
    assert sans["a"] == ([], [])
    assert sans["b"] == ([], [])


def test_include_ordonnancement_false_garde_les_deux_autres_sources():
    """Le désactivage ne doit couper QUE la 3e source — la séquence propre au
    cours et les paires de cohorte restent actives."""
    a = _seance("a", "WR101", "g", ordre=1)
    b = _seance("a2", "WR101", "g", ordre=2)
    voisins = _build_sequence_neighbors([a, b], include_ordonnancement=False)
    assert voisins["a"][1] == ["a2"]
    assert voisins["a2"][0] == ["a"]
