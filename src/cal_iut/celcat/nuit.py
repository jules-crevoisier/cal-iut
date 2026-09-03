"""Job de nuit : pousser les semaines validées + scanner les extras Live."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

from cal_iut.api.state import get_state
from cal_iut.celcat.ecriture import creer_manquants, resoudre_groupe, resoudre_ids
from cal_iut.celcat.etat import charger, live_actuel
from cal_iut.celcat.extras import enregistrer
from cal_iut.celcat.extras import lister as lister_extras
from cal_iut.celcat.file_attente import enfiler, lister, retirer_traites
from cal_iut.celcat.formulaire import charger_carte
from cal_iut.celcat.lecture import (
    EvenementCelcat,
    est_cours,
    est_fantome,
    est_ferie,
    evenement_depuis_rpc,
    indice_depuis_lundi,
)
from cal_iut.celcat.mapping import entrees_pour_state
from cal_iut.celcat.modification import ElementModification, modifier_manquants
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT
from cal_iut.celcat.ops import correspond_live
from cal_iut.celcat.rpc import masquer_semaine
from cal_iut.celcat.rpc_config import charger_methodes
from cal_iut.celcat.suppression import ElementSuppression, supprimer_manquants
from cal_iut.celcat.sync import marquer_saisi

# Même valeur que `scripts/pousser_manquants_celcat.py::PREMIERE_SEMAINE_CELCAT`
# — indice `weeks` 0 = cette semaine ISO. Dupliqué plutôt qu'importé d'un
# script : les scripts ne sont pas un module importable en amont de `src/`.
PREMIERE_SEMAINE_CELCAT = 34


def _event_id(row: dict[str, Any]) -> int | None:
    brut = row.get("event_id")
    if brut in (None, "", 0, "0"):
        return None
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def _group_ids_depuis_nom(nom: str) -> list[str]:
    if not nom.strip():
        return []
    state = get_state()
    cible = nom.strip().upper()
    for groupe in state.groups:
        label = str(getattr(groupe, "label", "") or "").strip()
        semestre = str(getattr(groupe, "semestre", "") or "").strip()
        compose = f"BUT MMI {semestre} {label}".strip().upper()
        if cible == compose or (label and label.upper() in cible):
            return [str(groupe.id)]
    return []


def _teacher_codes_depuis_nom(nom: str) -> list[str]:
    if not nom.strip():
        return []
    state = get_state()
    morceaux = nom.strip().upper()
    codes: list[str] = []
    for cours in state.courses:
        for bloc in getattr(cours, "profs", []) or []:
            prof = getattr(bloc, "teacher", None)
            if prof is None:
                continue
            nom_prof = f"{getattr(prof, 'nom', '')} {getattr(prof, 'prenom', '')}".upper()
            code = str(getattr(prof, "code", "") or "")
            if code and (getattr(prof, "nom", "").upper() in morceaux or morceaux in nom_prof):
                if code not in codes:
                    codes.append(code)
    return codes


def _code_depuis_ev(ev: EvenementCelcat) -> str:
    nom = (ev.module_nom or "").strip()
    if nom:
        return nom.split()[0]
    return (ev.module_code or "").strip()


def _evenements_depuis_page(page: Any) -> list[EvenementCelcat]:
    reponses = getattr(page, "reponses", None)
    if not isinstance(reponses, dict):
        return []
    bruts = reponses.get("udlTimetables.load")
    if not isinstance(bruts, list):
        return []
    evenements: list[EvenementCelcat] = []
    for brut in bruts:
        if not isinstance(brut, dict):
            continue
        groupes = brut.get("groups") if isinstance(brut.get("groups"), list) else []
        tete = groupes[0] if groupes and isinstance(groupes[0], dict) else {}
        gid = int(tete["id"]) if tete.get("id") is not None else 0
        gnom = str(tete.get("name") or "")
        evenements.append(evenement_depuis_rpc(brut, group_id=gid, groupe_nom=gnom))
    return evenements


def _a_un_match_caliut(ev: EvenementCelcat) -> bool:
    state = get_state()
    for placement in state.timetable:
        session = state.sessions_by_id.get(placement.session_id)
        if session is None:
            continue
        if correspond_live(session, placement, ev):
            return True
    return False


def _scanner_extras(page: Any, doc: dict[str, Any]) -> None:
    evenements = list(live_actuel())
    vus = {ev.event_id for ev in evenements}
    if page is not None:
        for ev in _evenements_depuis_page(page):
            if ev.event_id not in vus:
                evenements.append(ev)
                vus.add(ev.event_id)

    ignores = doc.get("ignores") if isinstance(doc.get("ignores"), dict) else {}
    existants = {str(x.get("id")): x for x in lister_extras()}

    for ev in evenements:
        if not est_cours(ev) or est_ferie(ev) or est_fantome(ev):
            continue
        extra_id = f"extra-{ev.event_id}"
        if extra_id in ignores or str(ev.event_id) in ignores:
            continue
        deja = existants.get(extra_id)
        if deja and deja.get("statut") in ("ignore", "ajoute"):
            continue
        if _a_un_match_caliut(ev):
            continue
        code = _code_depuis_ev(ev)
        group_ids = _group_ids_depuis_nom(ev.groupe_nom)
        teacher_codes = _teacher_codes_depuis_nom(ev.enseignant)
        semaine = ev.indice_semaine
        enregistrer(
            {
                "id": extra_id,
                "statut": "ouvert",
                "course_code": code,
                "module_nom": ev.module_nom,
                "libelle": ev.module_nom,
                "event_id": ev.event_id,
                "groupe": ev.groupe_nom,
                "group_ids": group_ids,
                "teacher_codes": teacher_codes,
                "jour": ev.jour,
                "heure_debut": ev.heure_debut,
                "heure_fin": ev.heure_fin,
                "salle": ev.salle,
                "enseignant": ev.enseignant,
                "semaine": semaine,
            }
        )


def _masque_pour(entree: Any) -> str:
    """Masque `weeks` (54 caractères, 1×Y) pour une entrée — calcul PUR
    (aucun RPC) : `lundi` -> indice `weeks`. Ne lève jamais : un lundi
    absent ou hors calendrier retombe sur un masque vide, que
    `verifier_avant_envoi` refusera proprement en aval (SemainesNonRestreintes)."""
    try:
        if not str(getattr(entree, "lundi", "") or "").strip():
            return "N" * 54
        from datetime import date

        indice = indice_depuis_lundi(
            date.fromisoformat(entree.lundi), premiere_semaine_celcat=PREMIERE_SEMAINE_CELCAT
        )
        return masquer_semaine(longueur=54, indice=indice)
    except Exception:  # noqa: BLE001
        return "N" * 54


def _ids_pour(page: Any, entree: Any) -> dict:
    """Résout module/salle/personnel/catégorie/département Celcat via le
    catalogue RPC (`page`). Sur un échec de résolution (catalogue
    indisponible, ressource inconnue), retombe sur `{}` : l'écriture réelle
    (creer_manquants/modifier_manquants) refusera alors proprement via ses
    propres garde-fous plutôt que de faire échouer tout le job de nuit."""
    try:
        state = get_state()
        carte = charger_carte(state.config_dir)
        categorie = carte.categorie(entree.type_seance_nom)
        return resoudre_ids(page, entree, categorie=categorie)
    except Exception:  # noqa: BLE001
        return {}


def _group_id_pour(page: Any, entree: Any, group_id_connu: object) -> int:
    """Préfère le `group_id` déjà porté par le job (posé par `ops.py` ou par
    le job lui-même) ; sinon résout via le catalogue RPC, sinon 0 (échec
    encaissé en aval, jamais une exception qui arrête le job de nuit)."""
    if group_id_connu not in (None, ""):
        try:
            return int(group_id_connu)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    try:
        return resoudre_groupe(page, entree.nom_groupe_celcat)
    except Exception:  # noqa: BLE001
        return 0


def _consommer_file(
    page: Any, doc: dict[str, Any], *, base: str, production_autorisee: bool
) -> None:
    """Draine `file_attente.lister()` et appelle la primitive RPC adaptée à
    chaque job (create/update/delete). Un job traité (succès OU refus de
    garde-fou) est retiré de la file ; un job en échec RPC/réseau y reste
    pour la prochaine nuit — jamais un `vider()` global."""
    jobs = lister()
    if not jobs:
        return

    state = get_state()
    entrees = entrees_pour_state(state)
    methodes = charger_methodes(Path(state.config_dir))
    a_retirer: list[dict[str, Any]] = []

    # --- create : un appel par job, comme les scripts existants (ids/masque
    # ne sont pas garantis homogènes entre deux jobs différents). ---------
    for job in jobs:
        if job.get("action") != "create":
            continue
        entree = entrees.get(str(job.get("session_id") or ""))
        if entree is None:
            continue
        group_id = _group_id_pour(page, entree, job.get("group_id"))
        ids = _ids_pour(page, entree)
        masque = _masque_pour(entree)
        resultat = creer_manquants(
            page,
            [entree],
            group_id=group_id,
            ids=ids,
            masque=masque,
            methode=methodes.methode_ecriture,
            base=base,
            production_autorisee=production_autorisee,
        )
        for sid, eid in resultat.crees:
            marquer_saisi(entree, event_id=eid, group_id=group_id)
            a_retirer.append(job)

    # --- update : un seul lot, ElementModification porte déjà ses propres
    # ids/masque/group_id (contrairement à creer_manquants). ---------------
    elements_m: list[ElementModification] = []
    jobs_m: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if job.get("action") != "update":
            continue
        sid = str(job.get("session_id") or "")
        entree = entrees.get(sid)
        eid = job.get("event_id")
        if entree is None or eid in (None, ""):
            continue
        group_id = _group_id_pour(page, entree, job.get("group_id"))
        elements_m.append(
            ElementModification(
                entree=entree,
                event_id=int(eid),
                group_id=group_id,
                ids=_ids_pour(page, entree),
                masque=_masque_pour(entree),
            )
        )
        jobs_m[sid] = job
    if elements_m:
        resultat_m = modifier_manquants(
            page,
            elements_m,
            methode=methodes.methode_ecriture,
            base=base,
            production_autorisee=production_autorisee,
        )
        gid_par_session = {el.entree.session_id: el.group_id for el in elements_m}
        for sid, eid in resultat_m.modifiees:
            job = jobs_m.get(sid)
            if job is None:
                continue
            a_retirer.append(job)
            entree = entrees.get(sid)
            if entree is not None:
                marquer_saisi(entree, event_id=eid, group_id=gid_par_session.get(sid))

    # --- delete : group_id vient du job (row.get("group_id")), jamais résolu
    # ici — c'est `ops.py` qui le pose à l'enfilage. ------------------------
    elements_s: list[ElementSuppression] = []
    jobs_s: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if job.get("action") != "delete":
            continue
        sid = str(job.get("session_id") or "")
        eid = job.get("event_id")
        gid = job.get("group_id")
        if eid in (None, "") or gid in (None, ""):
            continue
        elements_s.append(ElementSuppression(session_id=sid, event_id=int(eid), group_id=int(gid)))
        jobs_s[sid] = job
    if elements_s:
        resultat_s = supprimer_manquants(
            page,
            elements_s,
            methode=methodes.methode_suppression,
            base=base,
            production_autorisee=production_autorisee,
        )
        for sid in resultat_s.supprimees:
            job = jobs_s.get(sid)
            if job is not None:
                a_retirer.append(job)
        for sid, _motif in resultat_s.refusees:
            job = jobs_s.get(sid)
            if job is not None:
                a_retirer.append(job)

    if a_retirer:
        retirer_traites(a_retirer)


def executer_job_nuit(
    page: Any = None, *, base: str = BASE_ENTRAINEMENT, production_autorisee: bool = False
) -> None:
    from datetime import datetime

    from cal_iut.celcat.etat import sauver, semaines_celcat_passees

    doc = charger()
    if not doc.get("saisie_active"):
        return

    validees = {int(s) for s in (doc.get("semaines_validees") or [])}
    deja_lancees = {int(s) for s in (doc.get("semaines_lancees") or [])}
    passees = set(semaines_celcat_passees())
    semaines = validees - deja_lancees - passees
    state = get_state()
    journal = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}

    places = [p for p in state.timetable if p.week in semaines]
    ids_places = {p.session_id for p in places}

    for placement in places:
        row = journal.get(placement.session_id)
        eid = _event_id(row) if isinstance(row, dict) else None
        if eid is None:
            enfiler(
                {
                    "action": "create",
                    "session_id": placement.session_id,
                    "semaine": placement.week,
                }
            )
        else:
            enfiler(
                {
                    "action": "update",
                    "session_id": placement.session_id,
                    "event_id": eid,
                    "semaine": placement.week,
                }
            )

    for session_id, row in journal.items():
        if not isinstance(row, dict):
            continue
        try:
            sem = int(row.get("semaine", -1))
        except (TypeError, ValueError):
            continue
        if sem not in semaines or session_id in ids_places:
            continue
        eid = _event_id(row)
        if eid is None:
            continue
        enfiler(
            {
                "action": "delete",
                "session_id": session_id,
                "event_id": eid,
                "semaine": sem,
            }
        )

    _scanner_extras(page, doc)

    if page is not None:
        _consommer_file(page, doc, base=base, production_autorisee=production_autorisee)

    doc = charger()
    lancees = {int(s) for s in (doc.get("semaines_lancees") or [])}
    doc["semaines_lancees"] = sorted(lancees | semaines)
    doc["dernier_job"] = {"lance_le": datetime.now(UTC).isoformat()}
    sauver(doc)
