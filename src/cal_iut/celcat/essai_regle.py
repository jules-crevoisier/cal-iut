"""Essai d'une règle d'envoi (`celcat.yaml::regles_envoi`) contre le vrai Celcat.

`cal-iut celcat-essai-regle --cours WR100BU` ou `--type PTUT` (docs/CELCAT.md
§ 5 ; alias historique : `celcat-essai-sans-module`). Deux demandes de
Kyllian Bresson (01/10/2026) : la visite de la BU de Valérie Mariot part en
« TD0 » sans matière ; toute séance PTUT part en « Projet », avec le module
du cours s'il est connu. Rien de cela n'a pu être essayé depuis
l'environnement de développement (pas de VPN de l'université) : cette
commande est faite pour être lancée par un administrateur, avec le VPN.

DEUX MODES, et le plus sûr par défaut :

- SIMULATION (défaut) : connexion en LECTURE (rôle `985_consultation`),
  résolution des identifiants comme le ferait le robot — salle, enseignant,
  catégorie, département, groupe, matière s'il y a lieu —, puis affichage
  de la charge EXACTE qui serait envoyée, après les mêmes garde-fous. Rien
  n'est écrit. Possible sur la base réelle (`--base URCA_2026`) : c'est même
  là qu'elle est la plus utile, pour vérifier que « TD0 », « Projet » et
  « T_MMI T29 » s'y trouvent bien.
- ÉCRITURE (`--ecrire`) : base d'ENTRAÎNEMENT seulement (`URCA_FORMATION`).
  Crée UN évènement, le relit, montre ce que Celcat en a gardé (catégorie,
  pondération, département, remarque, salle, groupe, enseignant, matières),
  puis le SUPPRIME et vérifie qu'il a disparu. Jamais la base réelle :
  refusé avant même de se connecter, puis une seconde fois par
  `verifier_avant_envoi`.

Les fonctions ci-dessous ne parlent à Celcat qu'à travers `page` : elles se
testent hors ligne avec un faux. Le réseau et le navigateur vivent dans
`cli.py::cmd_celcat_essai_regle`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cal_iut.celcat.categories import verifier_charge_categorie
from cal_iut.celcat.ecriture import (
    RessourceIntrouvable,
    _filtre_ressource,
    charge_utile,
    resoudre_groupe,
    resoudre_ids,
    verifier_avant_envoi,
)
from cal_iut.celcat.mapping import EntreeCelcat, session_id_depuis_notes
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT, BASE_PRODUCTION, TYPE_GROUPES
from cal_iut.celcat.rpc import (
    charger_edt,
    charger_ressources,
    enregistrer_evenement,
    event_id_retour,
    preparer_evenement,
)

# Groupe de la base d'entraînement : « BUT MMI S1 TD AB - 2024 », celui des
# canaris du 01/09 et du 05/09/2026 (`celcat_rpc.yaml`,
# `scripts/canari_rpc_formation.py`). Les identifiants de groupe de
# `celcat_groupes.yaml` sont ceux d'URCA_2026 : ils n'existent pas dans
# URCA_FORMATION.
GROUPE_CANARI_FORMATION = 47925


class EssaiRefuse(PermissionError):
    """Écrire ailleurs que dans la base d'entraînement : jamais."""


@dataclass
class ResultatEssai:
    entree: EntreeCelcat
    base: str
    group_id: int = 0
    groupe_lu: str = ""
    ids: dict = field(default_factory=dict)
    charge: dict = field(default_factory=dict)
    erreur: str = ""
    event_id: int | None = None
    relu: dict = field(default_factory=dict)
    supprime: bool | None = None
    detail_suppression: str = ""

    @property
    def ok(self) -> bool:
        return not self.erreur


def choisir_entree(
    entrees: dict[str, EntreeCelcat], *, cours: str = "", type_seance: str = "", seance: str = ""
) -> EntreeCelcat:
    """La séance à essayer : celle demandée, ou la première qui part sous la
    règle — de préférence sur « TD AB », le groupe des canaris de la base
    d'entraînement."""
    cours = cours.strip().upper()
    type_seance = type_seance.strip().upper()

    def _visee(e: EntreeCelcat) -> bool:
        if cours:
            return e.course_code.upper() == cours
        return e.type_seance_nom.upper() == type_seance

    cible = cours or f"type {type_seance}"
    if seance:
        entree = entrees.get(seance)
        if entree is None:
            raise LookupError(f"séance {seance} absente du planning (aucun placement)")
        if not _visee(entree):
            raise LookupError(f"séance {seance} : ce n'est pas une séance de {cible}")
        return entree
    candidates = [e for e in entrees.values() if _visee(e)]
    if not candidates:
        raise LookupError(
            f"aucune séance de {cible} placée au planning"
            + (" — `--seance <id> --comme-type` essaie une autre séance comme si elle était de ce type" if type_seance else "")
        )
    sous_regle = [e for e in candidates if e.regle]
    if not sous_regle:
        motifs = sorted({e.non_envoyee or "; ".join(e.bloquants) for e in candidates})
        raise LookupError(
            f"aucune séance de {cible} ne part sous une règle d'envoi (celcat.yaml::regles_envoi) — "
            f"{' | '.join(m for m in motifs if m) or 'pas de règle'}"
        )
    sous_regle.sort(key=lambda e: (e.groupe != "TD AB", e.semaine, e.jour, e.heure_debut))
    return sous_regle[0]


def entree_comme_type(state: Any, session_id: str, type_seance: str) -> EntreeCelcat:
    """La séance `session_id` traduite COMME SI elle était du type demandé.

    Pour essayer une règle de type (« PTUT ») quand le planning n'a encore
    aucune séance de ce type : une vraie séance (vrais groupe, salle,
    enseignant, cours) sert de support. Réservé à l'essai — jamais au plan
    ni au robot."""
    from cal_iut.celcat.mapping import _lundi_iso, entree_pour_placement, load_celcat_config

    placement = next((p for p in state.timetable if p.session_id == session_id), None)
    if placement is None:
        raise LookupError(f"séance {session_id} absente du planning (aucun placement)")
    session = state.sessions_by_id.get(session_id)
    libelle_groupe = {g.id: g.label for g in state.groups}
    semestre = str(getattr(session, "semestre", "") or "")
    return entree_pour_placement(
        load_celcat_config(state.config_dir),
        session_id=session_id,
        course_code=placement.course_code,
        session_type=type_seance,
        week=placement.week, day=placement.day, slot=placement.slot,
        duration_slots=max(1, getattr(session, "duration_slots", 1) or 1) if session else 1,
        teacher_codes=list(placement.teacher_codes or []),
        room_id=getattr(placement, "room_id", None),
        groupe=", ".join(libelle_groupe.get(g, g) for g in (placement.group_ids or [])),
        semestre=semestre,
        lundi=_lundi_iso(state, semestre, placement.week) if semestre else "",
    )


def _nom_groupe(page: Any, group_id: int) -> str:
    try:
        lots = charger_ressources(page, TYPE_GROUPES, _filtre_ressource(record_ids=[group_id]))
    except Exception:  # noqa: BLE001 — un nom en moins, jamais un échec
        return ""
    for enreg in lots:
        nom = str(enreg.get("name") or enreg.get("unique_name") or "").strip()
        if nom:
            return nom
    return ""


def resoudre_groupe_essai(page: Any, entree: EntreeCelcat, *, base: str, group_id: int | None) -> tuple[int, str]:
    """Le groupe Celcat de l'essai, et la façon dont il a été trouvé."""
    if group_id:
        return int(group_id), "imposé par --group-id"
    try:
        return resoudre_groupe(page, entree.nom_groupe_celcat), "celcat_groupes.yaml"
    except Exception as exc:
        if base == BASE_ENTRAINEMENT:
            return GROUPE_CANARI_FORMATION, (
                f"groupe des canaris de la base d'entraînement ({entree.nom_groupe_celcat} "
                f"introuvable ici : {exc})"
            )
        raise


def preparer(
    page: Any,
    entree: EntreeCelcat,
    *,
    base: str,
    masque: str,
    group_id: int | None = None,
) -> ResultatEssai:
    """Résout et construit la charge, SANS rien écrire. Toute erreur de
    résolution ou de garde-fou est rendue dans `erreur` — c'est exactement
    ce qui bloquerait la séance dans le robot."""
    res = ResultatEssai(entree=entree, base=base)
    try:
        res.group_id, origine = resoudre_groupe_essai(page, entree, base=base, group_id=group_id)
        res.groupe_lu = f"{_nom_groupe(page, res.group_id) or '?'} (group_id {res.group_id}, {origine})"
        res.ids = resoudre_ids(page, entree, categorie=entree.categorie_celcat)
        charge = charge_utile(entree, group_id=res.group_id, ids=res.ids, masque=masque, event_id=0)
        verifier_charge_categorie(
            charge, type_seance_nom=entree.type_seance_nom, categorie_regle=entree.categorie_celcat,
            sans_module=entree.sans_module,
        )
        # Simulation sur la base réelle : on vérifie le masque, pas le droit
        # d'écrire (qui n'est pas demandé).
        verifier_avant_envoi(charge, base=base, production_autorisee=base == BASE_PRODUCTION)
        res.charge = preparer_evenement(charge)
    except RessourceIntrouvable as exc:
        res.erreur = f"introuvable dans Celcat : {exc}"
    except Exception as exc:  # noqa: BLE001
        res.erreur = f"{type(exc).__name__} : {exc}"
    return res


def resume_evenement(brut: dict) -> dict:
    """Ce que Celcat a gardé d'un évènement, lisiblement."""

    def noms(cle: str) -> list[str]:
        sortie = []
        for item in brut.get(cle) or []:
            if isinstance(item, dict):
                sortie.append(str(item.get("name") or item.get("unique_name") or item.get("id") or "?"))
        return sortie

    return {
        "event_id": brut.get("event_id"),
        "categorie": brut.get("evCatName"),
        "event_cat_id": brut.get("event_cat_id"),
        # La pondération est portée par la CATÉGORIE (champ en lecture seule
        # de l'évènement, refusé à l'écriture : `rpc.CHAMPS_CLIENT`).
        "ponderation": brut.get("evCatWeighting"),
        "departement": brut.get("deptName"),
        "dept_id": brut.get("dept_id"),
        "remarque (notes)": brut.get("notes"),
        "session_id lu dans notes": session_id_depuis_notes(str(brut.get("notes") or "")),
        # Les champs « personnaliser » de l'onglet « Remarques et
        # personnaliser », s'ils existent : à comparer à ce que montre
        # l'inspecteur de Celcat (cf. docs/CELCAT.md).
        "custom1": brut.get("custom1"),
        "custom2": brut.get("custom2"),
        "custom3": brut.get("custom3"),
        "salles": noms("rooms"),
        "groupes": noms("groups"),
        "enseignants": noms("staff"),
        "matieres": noms("modules"),
        "jour": brut.get("day_of_week"),
        "debut": brut.get("start_time"),
        "fin": brut.get("end_time"),
        "semaines (Y)": str(brut.get("weeks") or "").count("Y"),
    }


def _relire(page: Any, event_id: int, group_id: int) -> dict | None:
    for brut in charger_edt(page, group_ids=[group_id]):
        brut_id = brut.get("event_id") if brut.get("event_id") is not None else brut.get("id")
        if brut_id is not None and int(brut_id) == int(event_id):
            return brut
    return None


def ecrire_relire_supprimer(
    page: Any,
    res: ResultatEssai,
    *,
    methode: str,
    methode_suppression: str,
    avant_suppression: Any = None,
) -> ResultatEssai:
    """Crée l'évènement préparé, le relit, le supprime. Base d'entraînement
    SEULEMENT. La suppression est tentée dès que l'évènement existe, même si
    la relecture échoue."""
    from cal_iut.celcat.suppression import supprimer_evenement

    if res.base != BASE_ENTRAINEMENT:
        raise EssaiRefuse(
            f"écriture refusée sur {res.base} : l'essai n'écrit que dans {BASE_ENTRAINEMENT}"
        )
    if not res.ok or not res.charge:
        raise EssaiRefuse(f"rien à écrire : {res.erreur or 'charge vide'}")
    # Deuxième verrou, celui de toute écriture : URCA_2026 sans --production
    # est refusé ici aussi.
    verifier_avant_envoi(res.charge, base=res.base, production_autorisee=False)
    retour = enregistrer_evenement(page, res.charge, methode=methode)
    res.event_id = event_id_retour(retour)
    if not res.event_id:
        res.erreur = f"Celcat n'a pas rendu d'event_id : {retour!r}"
        return res
    try:
        brut = _relire(page, res.event_id, res.group_id)
        res.relu = resume_evenement(brut) if brut is not None else {"erreur": "évènement non relu"}
        if avant_suppression is not None:
            avant_suppression(res)
    finally:
        try:
            supprimer_evenement(
                page,
                res.event_id,
                group_id=res.group_id,
                methode=methode_suppression,
                base=res.base,
                production_autorisee=False,
            )
            res.supprime = _relire(page, res.event_id, res.group_id) is None
            res.detail_suppression = "supprimé, absent à la relecture" if res.supprime else "TOUJOURS PRÉSENT après suppression"
        except Exception as exc:  # noqa: BLE001
            res.supprime = False
            res.detail_suppression = f"suppression en échec : {type(exc).__name__} : {exc}"
    return res
