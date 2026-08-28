"""Saisie automatisée vers CELCAT — traduction, synchronisation, cadence.

Tout est testé SANS navigateur ni identifiants : c'est le but de la
séparation en trois couches (`mapping` / `sync` / `driver`). Le seul module
qui a besoin de Celcat (`driver.PilotePlaywright`) est remplacé ici par
`PiloteSimule`, strictement équivalent du point de vue de l'orchestration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cal_iut.celcat.driver import PiloteSimule, ResultatSaisie, Rythme, SaisieCelcat
from cal_iut.celcat.mapping import CelcatConfig, entree_pour_placement, load_celcat_config
from cal_iut.celcat import sync

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _journal_isole(tmp_path, monkeypatch):
    """Le journal de synchronisation ne doit jamais s'écrire dans le vrai
    dépôt : il représenterait alors des séances « déjà saisies dans Celcat »
    qui ne l'ont jamais été."""
    monkeypatch.setattr(sync, "_path", lambda: tmp_path / "celcat_sync.json")


@pytest.fixture
def cfg() -> CelcatConfig:
    return CelcatConfig(
        enseignants={"FLI": "20900", "KBR": "35543"},
        salles={"h111": "H.111", "h203": "H.023", "h101": "H.101"},
        types_seance={"TD": 4, "TP": 6, "CM": None},
        modules={"WR314D": "TSBZ2520", "WR101": "TSBZ2104"},
    )


def _entree(cfg, **kw):
    base = dict(
        session_id="s1", course_code="WR314D", session_type="TD", week=2, day=0,
        slot=0, duration_slots=1, teacher_codes=["FLI"], room_id="h111", groupe="TD AB",
    )
    base.update(kw)
    return entree_pour_placement(cfg, **base)


# --------------------------------------------------------------------------
# Traduction
# --------------------------------------------------------------------------


def test_une_seance_complete_est_prete(cfg) -> None:
    e = _entree(cfg)
    assert e.prete, e.bloquants
    assert e.code_enseignant == "20900"
    assert e.salle == "H.111"
    assert e.code_module == "TSBZ2520"
    assert e.type_seance == 4
    # Lundi = 0 chez nous, 1 côté Celcat (convention des scripts `.bat`).
    assert e.jour == 1


def test_un_bloc_de_3h_donne_UNE_entree_et_pas_deux(cfg) -> None:
    """L'ancien autoclicker émettait deux lignes consécutives pour un bloc
    de 3 h, ce qui crée deux séances dans Celcat au lieu d'une seule plage."""
    e = _entree(cfg, slot=3, duration_slots=2)
    assert (e.heure_debut, e.heure_fin) == ("14:00", "17:00")


def test_la_salle_203_devient_023(cfg) -> None:
    """Particularité signalée par l'utilisateur : « on n'a pas de salle 203
    dans notre Celcat, on utilise H.023 à la place »."""
    assert _entree(cfg, room_id="h203").salle == "H.023"


@pytest.mark.parametrize(
    "modif, motif",
    [
        (dict(teacher_codes=["INCONNU"]), "sans code Celcat"),
        (dict(teacher_codes=[]), "aucun enseignant"),
        (dict(room_id=None), "aucune salle"),
        (dict(room_id="h999"), "sans équivalent Celcat"),
        (dict(course_code="WR999"), "sans code Celcat"),
        (dict(session_type="CM"), "type de séance CM"),
    ],
)
def test_toute_donnee_manquante_bloque_avec_son_motif(cfg, modif, motif) -> None:
    """Rien n'est jamais deviné : Celcat sert aussi à PAYER les enseignants,
    une valeur inventée y créerait une séance fausse."""
    e = _entree(cfg, **modif)
    assert not e.prete
    assert any(motif in b for b in e.bloquants), e.bloquants


def test_plusieurs_enseignants_sont_signales_pas_tronques(cfg) -> None:
    e = _entree(cfg, teacher_codes=["FLI", "KBR"])
    assert not e.prete
    assert any("n'en accepte qu'un" in b for b in e.bloquants)


def test_la_config_reelle_du_depot_se_charge(cfg) -> None:
    """`data/config/celcat.yaml` doit rester lisible et cohérent."""
    reelle = load_celcat_config(ROOT / "data" / "config")
    assert reelle.enseignants, "les codes enseignants doivent être renseignés"
    assert reelle.salles.get("h203") == "H.023", "la particularité 203 -> 023 doit tenir"


# --------------------------------------------------------------------------
# Synchronisation : c'est elle qui permet de RE-pousser une semaine modifiée
# --------------------------------------------------------------------------


def test_une_seance_jamais_saisie_est_a_creer(cfg) -> None:
    plan = sync.construire_plan([_entree(cfg)], {2})
    assert [e.session_id for e in plan.a_creer] == ["s1"]
    assert not plan.a_modifier and not plan.inchangees


def test_une_seance_inchangee_n_est_pas_re_saisie(cfg) -> None:
    e = _entree(cfg)
    sync.marquer_saisi(e)
    plan = sync.construire_plan([e], {2})
    assert [x.session_id for x in plan.inchangees] == ["s1"]
    assert not plan.a_creer and not plan.a_modifier


def test_une_seance_deplacee_est_a_modifier(cfg) -> None:
    """Le cas qui justifie tout ce mécanisme (retour utilisateur : « si l'on
    modifie le planning de semaines déjà envoyées, cela modifie dessus »)."""
    sync.marquer_saisi(_entree(cfg))
    plan = sync.construire_plan([_entree(cfg, slot=4)], {2})
    assert [e.session_id for e in plan.a_modifier] == ["s1"]


def test_un_changement_de_salle_seul_declenche_une_modification(cfg) -> None:
    sync.marquer_saisi(_entree(cfg))
    plan = sync.construire_plan([_entree(cfg, room_id="h101")], {2})
    assert [e.session_id for e in plan.a_modifier] == ["s1"]


def test_une_seance_disparue_est_a_supprimer(cfg) -> None:
    """Sinon Celcat garde des cours fantômes — et peut payer des heures qui
    n'ont pas lieu."""
    sync.marquer_saisi(_entree(cfg))
    plan = sync.construire_plan([], {2})
    assert plan.a_supprimer == ["s1"]


def test_une_semaine_hors_lot_n_est_jamais_vue_comme_supprimee(cfg) -> None:
    """Piège central : sans bornage par semaine, saisir la semaine 3
    proposerait de supprimer TOUT ce qui a été saisi les autres semaines."""
    sync.marquer_saisi(_entree(cfg, week=2))
    plan = sync.construire_plan([_entree(cfg, session_id="s2", week=3)], {3})
    assert plan.a_supprimer == []


def test_une_seance_bloquee_n_est_ni_creee_ni_comptee_comme_faite(cfg) -> None:
    plan = sync.construire_plan([_entree(cfg, course_code="WR999")], {2})
    assert plan.bloquees and not plan.a_creer


# --------------------------------------------------------------------------
# Exécution
# --------------------------------------------------------------------------


def _rythme_instantane() -> Rythme:
    z = (0.0, 0.0)
    return Rythme(entre_actions=z, entre_seances=z, entre_groupes=z, pause_longue_toutes_les=0, pause_longue=z)


def test_la_saisie_refuse_de_demarrer_s_il_reste_des_bloquees(cfg) -> None:
    """Mieux vaut ne pas ouvrir le navigateur du tout que s'arrêter au
    milieu d'un formulaire, dans un Celcat à moitié rempli."""
    plan = sync.construire_plan([_entree(cfg, course_code="WR999")], {2})
    pilote = PiloteSimule()
    with pytest.raises(ValueError, match="non saisissable"):
        SaisieCelcat(pilote, _rythme_instantane()).executer(plan, "user", "mdp")
    assert pilote.actions == [], "aucune action ne doit avoir eu lieu"


def test_le_deroule_complet_est_rejoue_sans_navigateur(cfg) -> None:
    plan = sync.construire_plan([_entree(cfg), _entree(cfg, session_id="s2", slot=1)], {2})
    pilote = PiloteSimule()
    res = SaisieCelcat(pilote, _rythme_instantane()).executer(plan, "user", "mdp")
    assert len(res.creees) == 2
    assert pilote.actions[0] == "connexion(user)"
    assert pilote.actions[-1] == "fermeture"
    assert any(a.startswith("groupe(TD AB") for a in pilote.actions)


def test_le_mot_de_passe_n_est_jamais_journalise(cfg) -> None:
    plan = sync.construire_plan([_entree(cfg)], {2})
    pilote = PiloteSimule()
    SaisieCelcat(pilote, _rythme_instantane()).executer(plan, "user", "SECRET-123")
    assert not any("SECRET-123" in a for a in pilote.actions)


def test_un_echec_isole_n_interrompt_pas_les_suivantes(cfg) -> None:
    class PiloteCapricieux(PiloteSimule):
        def creer_seance(self, entree):
            if entree.session_id == "s1":
                raise RuntimeError("champ refusé par Celcat")
            super().creer_seance(entree)

    plan = sync.construire_plan([_entree(cfg), _entree(cfg, session_id="s2", slot=1)], {2})
    res = SaisieCelcat(PiloteCapricieux(), _rythme_instantane()).executer(plan, "user", "mdp")
    assert [c for c, _ in res.echecs] == ["s1"]
    assert res.creees == ["s2"], "la séance suivante doit quand même être saisie"


def test_la_saisie_peut_etre_interrompue_proprement(cfg) -> None:
    """Bouton « stop » de l'interface : vérifié ENTRE deux séances, jamais
    au milieu d'un formulaire."""
    plan = sync.construire_plan(
        [_entree(cfg), _entree(cfg, session_id="s2", slot=1), _entree(cfg, session_id="s3", slot=2)], {2}
    )
    pilote = PiloteSimule()
    appels = {"n": 0}

    def doit_continuer() -> bool:
        appels["n"] += 1
        return appels["n"] <= 2  # laisse passer la 1re séance puis arrête

    res = SaisieCelcat(pilote, _rythme_instantane()).executer(plan, "u", "m", doit_continuer=doit_continuer)
    assert res.interrompu
    assert len(res.creees) < 3
    assert "fermeture" in pilote.actions, "le navigateur doit être refermé même interrompu"


def test_chaque_seance_saisie_est_journalisee_immediatement(cfg) -> None:
    """Permet de reprendre là où on s'est arrêté si la session est coupée,
    au lieu de tout re-saisir."""
    plan = sync.construire_plan([_entree(cfg)], {2})
    SaisieCelcat(PiloteSimule(), _rythme_instantane(), journaliser=sync.marquer_saisi).executer(plan, "u", "m")
    assert "s1" in sync.journal()
    # Deuxième passage : plus rien à faire.
    assert sync.construire_plan([_entree(cfg)], {2}).total_actions == 0


# --------------------------------------------------------------------------
# Cadence
# --------------------------------------------------------------------------


def test_les_pauses_sont_aleatoires_et_non_constantes() -> None:
    """Une cadence parfaitement régulière est justement ce qui trahit un
    script (retour utilisateur : « pas trop rapide pour pas être détecté »)."""
    r = Rythme()
    tirages = {round(__import__("random").uniform(*r.entre_seances), 4) for _ in range(30)}
    assert len(tirages) > 5, "les pauses doivent varier"
    assert r.entre_seances[0] > 1.0, "au moins une seconde entre deux séances"


def test_le_resultat_dit_ce_qui_a_ete_fait() -> None:
    res = ResultatSaisie(creees=["a"], modifiees=["b"], echecs=[("c", "boum")])
    texte = res.resume()
    assert "1 créée" in texte and "1 modifiée" in texte and "1 en échec" in texte
