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
        # Semestre et lundi sont désormais exigés : sans eux, le nom Celcat du
        # groupe et la semaine visée sont indevinables (cf. mapping.py).
        semestre="S2", lundi="2026-09-14",
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


def test_un_cm_est_saisissable_sans_index_numerique(cfg) -> None:
    """La catégorie se dépose par son libellé « [CM] », pas par un index."""
    e = _entree(cfg, session_type="CM", groupe="Promo BUT1", semestre="S1")
    assert e.prete, e.bloquants
    assert e.type_seance_nom == "CM"
    assert e.nom_groupe_celcat == "BUT MMI S1 CM"


def test_un_code_enseignant_zero_bloque(cfg) -> None:
    """« 0 » dans celcat.yaml = pas de code, pas une recherche de l'enseignant 0."""
    e = _entree(cfg, teacher_codes=["ALE"])
    assert not e.prete
    assert any("ALE" in b for b in e.bloquants)


def test_la_config_ignore_les_codes_zero() -> None:
    reelle = load_celcat_config(ROOT / "data" / "config")
    assert reelle.enseignants, "les codes enseignants doivent être renseignés"
    assert reelle.salles.get("h203") == "H.023"
    assert "ALE" not in reelle.enseignants
    assert "FCI" not in reelle.enseignants
    assert "WSA501D" not in reelle.modules


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


def test_la_saisie_peut_ignorer_les_bloquees_et_saisir_le_reste(cfg) -> None:
    """Décision du 01/09/2026 : ALE/BMA/FCI/TMI/WSA501D n'empêchent pas le reste."""
    pret = _entree(cfg)
    bloquee = _entree(cfg, session_id="s-manque", course_code="WR999")
    plan = sync.construire_plan([pret, bloquee], {2})
    pilote = PiloteSimule()
    res = SaisieCelcat(pilote, _rythme_instantane()).executer(
        plan, "user", "mdp", ignorer_bloquees=True,
    )
    assert res.creees == ["s1"]
    assert pilote.actions[0] == "connexion(user)"


def test_le_deroule_complet_est_rejoue_sans_navigateur(cfg) -> None:
    plan = sync.construire_plan([_entree(cfg), _entree(cfg, session_id="s2", slot=1)], {2})
    pilote = PiloteSimule()
    res = SaisieCelcat(pilote, _rythme_instantane()).executer(plan, "user", "mdp")
    assert len(res.creees) == 2
    assert pilote.actions[0] == "connexion(user)"
    assert pilote.actions[-1] == "fermeture"
    # Le pilote reçoit le nom CELCAT du groupe et la DATE du lundi : c'est ce
    # qu'il aura à retrouver là-bas, un index de semaine n'y désigne rien.
    assert any(a == "groupe(BUT MMI S2 TD AB, 2026-09-14)" for a in pilote.actions)


def test_s1_et_s5_meme_libelle_ne_sont_pas_melanges(cfg) -> None:
    """« TD AB » sans semestre collerait les S5 sur l'onglet S1."""
    s1 = _entree(cfg, session_id="s1", semestre="S1", lundi="2026-09-07")
    s5 = _entree(cfg, session_id="s5", semestre="S5", lundi="2026-09-07")
    plan = sync.construire_plan([s1, s5], {2})
    pilote = PiloteSimule()
    SaisieCelcat(pilote, _rythme_instantane()).executer(plan, "user", "mdp")
    assert "groupe(BUT MMI S1 TD AB, 2026-09-07)" in pilote.actions
    assert "groupe(BUT MMI S5 TD AB, 2026-09-07)" in pilote.actions


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


# --- Accès réseau : Celcat vit derrière le VPN AnyConnect de l'URCA -------
# Retour utilisateur 31/08/2026 : « on doit se connecter par VPN au réseau
# pour que cela fonctionne, c'est un client AnyConnect ». Ce qui compte
# n'est pas de monter le VPN — c'est que la saisie ne CLIQUE JAMAIS dans le
# vide quand il n'est pas là.


def test_saisie_refuse_de_demarrer_sans_reseau(cfg):
    """Rien ne doit partir vers Celcat si le VPN n'est pas monté."""
    from cal_iut.celcat.driver import AccesPerdu

    plan = sync.construire_plan([_entree(cfg)], {2})
    pilote = PiloteSimule()
    saisie = SaisieCelcat(pilote, _rythme_instantane(), verifier_acces=lambda: False)
    with pytest.raises(AccesPerdu):
        saisie.executer(plan, "user", "mdp")
    assert pilote.actions == [], "aucune action ne doit avoir été tentée"


def test_saisie_sarrete_quand_le_reseau_tombe_en_cours(cfg):
    """Une coupure en cours n'accumule pas les échecs : on s'arrête net."""
    joignable = {"oui": True}

    class PiloteQuiPerdLeReseau(PiloteSimule):
        def creer_seance(self, entree):
            joignable["oui"] = False
            raise RuntimeError("page morte")

    plan = sync.construire_plan([_entree(cfg)], {2})
    res = SaisieCelcat(
        PiloteQuiPerdLeReseau(), _rythme_instantane(), verifier_acces=lambda: joignable["oui"]
    ).executer(plan, "user", "mdp")
    assert res.interrompu and res.acces_perdu
    assert len(res.echecs) == 1, "on s'arrête à la première, on n'enchaîne pas"
    assert "injoignable" in res.resume()


def test_diagnostic_distingue_vpn_absent_et_service_en_panne():
    """Un nom qui ne résout pas et un service muet n'appellent pas le même
    geste : le message doit le dire."""
    from cal_iut.celcat import reseau

    d = reseau.verifier("https://celcat-qui-nexiste-pas.invalid/")
    assert not d and d.vpn_monte is False
    assert "VPN" in d.detail


def test_aucun_secret_dans_les_messages_de_vpn():
    from cal_iut.celcat import reseau

    assert "hunter2" not in reseau._sans_secret("échec pour hunter2 ici", "hunter2")


def test_l_absence_de_client_vpn_se_constate_sans_planter(monkeypatch):
    """`client_disponible` cherchait OpenConnect avec `shutil.which` sans que
    `shutil` soit importé : sur une machine sans AnyConnect — donc sur tout
    poste où l'on découvre l'outil — le diagnostic levait un `NameError` au
    lieu de répondre « aucun client VPN ». L'erreur ne se voyait pas depuis
    Windows avec AnyConnect installé, où la première branche sort avant."""
    from cal_iut.celcat import reseau

    monkeypatch.setattr(reseau, "chemin_vpncli", lambda: None)
    monkeypatch.setattr(reseau, "CHEMINS_OPENCONNECT", ())
    monkeypatch.setattr(reseau.shutil, "which", lambda _: None)
    assert reseau.client_disponible() == (None, None)
    assert reseau.etat_vpn() == "aucun client VPN (ni AnyConnect ni OpenConnect)"


def test_acces_direct_essaye_avant_de_monter_le_vpn(monkeypatch):
    """Sur site, Celcat répond sans VPN : on ne monte rien pour rien.

    Retour utilisateur 31/08/2026 : « toujours tester si on peut accéder à
    Celcat sans le VPN au cas où on soit sur site, avant de passer par le
    VPN ».
    """
    from cal_iut.celcat import reseau

    tentatives = []
    monkeypatch.setattr(
        reseau, "verifier", lambda url, **kw: reseau.Diagnostic(True, "sur site", vpn_monte=None)
    )
    monkeypatch.setattr(
        reseau, "connecter", lambda **kw: tentatives.append("vpn") or reseau.Diagnostic(True, "")
    )
    assert reseau.exiger_acces("https://celcat-lv.univ-reims.fr/", monter_le_vpn=True)
    assert tentatives == [], "aucun VPN ne doit être monté quand l'accès direct marche"


def test_le_vpn_est_monte_seulement_si_l_acces_direct_echoue(monkeypatch):
    from cal_iut.celcat import reseau

    etats = iter(
        [reseau.Diagnostic(False, "pas de DNS", vpn_monte=False), reseau.Diagnostic(True, "ok")]
    )
    tentatives = []
    monkeypatch.setattr(reseau, "verifier", lambda url, **kw: next(etats))
    monkeypatch.setattr(
        reseau,
        "connecter",
        lambda **kw: (tentatives.append("vpn"), reseau.Diagnostic(True, "monté"))[1],
    )
    assert reseau.exiger_acces("https://celcat-lv.univ-reims.fr/", monter_le_vpn=True)
    assert tentatives == ["vpn"]


def test_client_vpn_detecte_openconnect_sur_linux(monkeypatch):
    """Le serveur de production est un conteneur Linux : pas de .exe Cisco."""
    from pathlib import Path

    from cal_iut.celcat import reseau

    monkeypatch.setattr(reseau, "chemin_vpncli", lambda: None)
    monkeypatch.setattr(reseau, "chemin_openconnect", lambda: Path("/usr/sbin/openconnect"))
    outil, chemin = reseau.client_disponible()
    assert outil == "openconnect" and chemin == Path("/usr/sbin/openconnect")
