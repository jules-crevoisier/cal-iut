"""Brouillons d'emploi du temps — les relire, puis les publier (lot 3 du
chantier « Nouveau semestre depuis l'interface », 16/11/2026).

Un brouillon (`PlanningRun.etat == "brouillon"`, produit par l'écran
« Nouveau semestre ») n'a que ses placements calculés. Pour le relire dans
les vues habituelles, on construit un ÉTAT À PART, copie de l'état en
service où seuls changent les séances, les placements et le groupe de
semestres : le planning servi à tout le monde n'est pas touché, et rien de
ce qui lit `get_state()` (Celcat, sauvegardes, flux des enseignants) ne voit
le brouillon.
"""

from __future__ import annotations

import dataclasses
import threading

from cal_iut.api.state import AppState, etat_principal, get_repo, get_state
from cal_iut.db.models import PlanningRun
from cal_iut.solver.rooms import PlacedSessionWithRoom

GROUPES = {
    "odd": {"libelle": "Semestre impair", "semestres": ["S1", "S3", "S5"]},
    "even": {"libelle": "Semestre pair", "semestres": ["S2", "S4", "S6"]},
}


class BrouillonIntrouvable(LookupError):
    pass


def groupe_du_run(run: PlanningRun) -> str | None:
    """« odd » / « even » pour un run de groupe de semestres, sinon `None`
    (run historique d'un seul parcours)."""
    cle = (run.semestre or "").strip().lower()
    return cle if cle in GROUPES else None


def libelle_du_run(run: PlanningRun) -> str:
    groupe = groupe_du_run(run)
    if groupe:
        infos = GROUPES[groupe]
        return f"{infos['libelle']} ({', '.join(infos['semestres'])})"
    return f"{run.parcours} {run.semestre}"


def _resume(run: PlanningRun, placements: int) -> dict[str, object]:
    return {
        "run_id": run.id,
        "groupe": groupe_du_run(run),
        "libelle": libelle_du_run(run),
        # Heure UTC enregistrée sans fuseau : le dire, sinon le navigateur la
        # lit comme une heure locale.
        "cree_le": f"{run.created_at.isoformat(timespec='seconds')}+00:00" if run.created_at else None,
        "placements": placements,
    }


def lister() -> dict[str, object]:
    """Ce que montre l'écran : les brouillons, et ce qui est en service."""
    repo = get_repo()
    service = get_state()
    return {
        "brouillons": [_resume(run, nombre) for run, nombre in repo.brouillons()],
        "en_service": [
            {
                **_resume(run, nombre),
                "affiche": run.id == service.current_run_id,
                # Le planning du semestre en cours, servi par défaut : un
                # brouillon de ce semestre ne se publie pas.
                "en_cours": run.id == etat_principal().current_run_id,
            }
            for run, nombre in repo.runs_en_service()
        ],
    }


# ── État à part d'un brouillon ─────────────────────────────────────────

# Un seul brouillon gardé en mémoire : on en relit un à la fois, et l'état
# pèse quelques Mo. La clé porte la révision du planning en service, dont
# l'état du brouillon partage salles, groupes et calendrier.
_memo: tuple[tuple[int, int], AppState, dict[str, object]] | None = None
_verrou = threading.Lock()


def _construire_etat(run: PlanningRun) -> AppState:
    from cal_iut.ingestion.pipeline import run_ingestion

    service = get_state()
    groupe = groupe_du_run(run)
    resultat = run_ingestion(
        service.config_dir,
        parcours=None if groupe else run.parcours,
        semestre=None if groupe else run.semestre,
        semestre_group=groupe,
    )
    par_id = {s.id: s for s in resultat.sessions}
    # Le calcul ne garde que l'identifiant de la salle (« h009 ») ; les vues
    # affichent son libellé (« H.009 »).
    salles = {salle.id: salle.label for salle in service.rooms}
    placements = [
        PlacedSessionWithRoom(
            session_id=p.session_id, week=p.week, day=p.day, slot=p.slot,
            course_code=p.course_code,
            group_ids=par_id[p.session_id].group_ids,
            teacher_codes=par_id[p.session_id].teacher_codes,
            room_id=p.room_id, room_label=salles.get(p.room_id, p.room_id) if p.room_id else None,
        )
        for p in get_repo().placements_calcules(run.id)
        # Séance retirée de la maquette depuis le calcul : elle ne sera pas
        # publiée non plus (même règle qu'à la restauration du planning).
        if p.session_id in par_id
    ]
    return dataclasses.replace(
        service,
        sessions=resultat.sessions,
        courses=resultat.courses,
        sessions_by_id=par_id,
        timetable=placements,
        filter_parcours=None if groupe else run.parcours,
        filter_semestre=None if groupe else run.semestre,
        semestre_group=groupe,
        # Jamais d'écriture en base depuis cet état.
        current_run_id=None,
        last_status=run.status,
        last_objective_value=run.objective_value,
        last_gap_penalty=run.gap_penalty,
        corrections=[],
        restauration_erreur=None,
    )


def _charger(run_id: int) -> tuple[AppState, dict[str, object]]:
    global _memo
    from cal_iut.api import main as api
    from cal_iut.api import revision

    run = get_repo().get_brouillon(run_id)
    if run is None:
        raise BrouillonIntrouvable(run_id)
    cle = (run_id, revision.actuelle().numero)
    with _verrou:
        if _memo is not None and _memo[0] == cle:
            return _memo[1], _memo[2]
        a_part = _construire_etat(run)
        resultat = api._calculer_payload_app_state(a_part)
        resultat["brouillon"] = _resume(run, len(a_part.timetable))
        _memo = (cle, a_part, resultat)
        return a_part, resultat


def payload(run_id: int) -> dict[str, object]:
    """Même forme que `/app-state`, pour un brouillon. À ne pas modifier en
    place : partagé entre les requêtes."""
    return _charger(run_id)[1]


def etat(run_id: int) -> AppState:
    """L'état à part du brouillon (lecture seule)."""
    return _charger(run_id)[0]


def oublier() -> None:
    global _memo
    with _verrou:
        _memo = None


def supprimer(run_id: int) -> None:
    if not get_repo().supprimer_brouillon(run_id):
        raise BrouillonIntrouvable(run_id)
    oublier()


class PublicationRefusee(ValueError):
    pass


def calcule_avec_le_calendrier_actuel(run: object) -> bool:
    """Faux pour un brouillon créé avant le dernier changement de calendrier
    (changement d'année, ou correction de l'année en cours) : ses numéros de
    semaine ne désignent plus les mêmes dates."""
    from datetime import datetime, timezone

    from cal_iut.api import state as etats
    from cal_iut.ingestion import reglages

    try:
        en_cours = reglages.annee_en_cours(etats.etat_principal().config_dir)
        depuis = datetime.fromisoformat(en_cours["depuis"]) if en_cours and en_cours["depuis"] else None
    except (ValueError, TypeError):
        return True
    cree = getattr(run, "created_at", None)
    if depuis is None or cree is None:
        # Jamais changé d'année (ou retour à l'année d'origine sans trace).
        return True
    if cree.tzinfo is None:
        cree = cree.replace(tzinfo=timezone.utc)
    return cree >= depuis


def publier(run_id: int) -> dict[str, object]:
    """Met un brouillon en service : il devient le planning de son groupe
    de semestres, à côté de celui de l'autre groupe (`semestres_charges`).

    Refusé pour le semestre EN COURS : son planning est celui que Celcat
    suit séance par séance, le remplacer d'un coup y ferait partir des
    centaines de créations et de suppressions. Un semestre déjà en service
    se corrige dans les vues, pas en republiant.
    """
    from cal_iut.api import main as api
    from cal_iut.api import revision, sauvegardes_db, semestres_charges
    from cal_iut.api import state as etats

    repo = get_repo()
    run = repo.get_brouillon(run_id)
    if run is None:
        raise BrouillonIntrouvable(run_id)
    groupe = groupe_du_run(run)
    if groupe is None:
        raise PublicationRefusee("Seul un brouillon de semestre impair ou pair se publie depuis l'interface.")
    principal = etats.etat_principal()
    if not calcule_avec_le_calendrier_actuel(run):
        raise PublicationRefusee(
            "Ce brouillon a été calculé avec un autre calendrier (l'année universitaire a changé depuis) : "
            "ses séances tomberaient aux mauvaises dates. Relancez une génération."
        )
    en_service = semestres_charges.runs_par_groupe()
    if en_service:
        en_cours = semestres_charges.groupe_en_cours(
            sorted({*en_service, groupe}), principal.calendar, api._today()
        )
        if groupe == en_cours:
            raise PublicationRefusee(
                f"Le {GROUPES[groupe]['libelle'].lower()} est le semestre en cours : son planning ne se remplace pas "
                "depuis l'interface. Corrigez-le dans les vues."
            )
    sauvegardes_db.sauvegarder_avant_remplacement(principal.db_path)
    remplace = en_service.get(groupe)
    publie = repo.publier_run(run_id, {salle.id: salle.label for salle in principal.rooms})
    oublier()
    semestres_charges.restaurer(principal)
    revision.incrementer("brouillon_publie")
    return {
        "publie": publie.id,
        "groupe": groupe,
        "libelle": libelle_du_run(publie),
        "remplace": remplace.id if remplace is not None else None,
        "semestres_charges": semestres_charges.pour_payload(),
    }


# ── Routes (administrateurs) ───────────────────────────────────────────

from fastapi import APIRouter, Depends, HTTPException, Response  # noqa: E402

from cal_iut.api import accounts  # noqa: E402

router = APIRouter(prefix="/brouillons", dependencies=[Depends(accounts.require_role("admin"))])


@router.get("")
def lister_brouillons() -> dict[str, object]:
    return lister()


@router.get("/{run_id}/app-state")
def lire_brouillon(run_id: int) -> Response:
    """Le brouillon sous la forme de `/app-state` : l'interface l'affiche
    dans les vues habituelles, en lecture seule."""
    from cal_iut.api import cache_http

    try:
        contenu = payload(run_id)
    except BrouillonIntrouvable as exc:
        raise HTTPException(404, "Ce brouillon n'existe pas ou a déjà été publié.") from exc
    return Response(
        cache_http.serialiser_json(contenu),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{run_id}/timetable")
def lire_placements_du_brouillon(
    run_id: int,
    group_id: str | None = None,
    teacher_code: str | None = None,
    room_id: str | None = None,
    week: int | None = None,
) -> Response:
    """Même réponse que `/timetable`, sur les placements du brouillon."""
    from cal_iut.api import cache_http
    from cal_iut.api import main as api

    try:
        a_part = etat(run_id)
    except BrouillonIntrouvable as exc:
        raise HTTPException(404, "Ce brouillon n'existe pas ou a déjà été publié.") from exc
    reponse = api._calculer_timetable(group_id, teacher_code, room_id, week, state=a_part)
    return Response(
        cache_http.serialiser_json(reponse),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{run_id}/controles/doublons")
def doublons_du_brouillon(run_id: int, semaine: int | None = None) -> dict[str, object]:
    """Même réponse que `/controles/doublons`, sur le brouillon : salles ou
    enseignants pris deux fois dans l'emploi du temps calculé."""
    from cal_iut.api import doublons

    try:
        a_part = etat(run_id)
    except BrouillonIntrouvable as exc:
        raise HTTPException(404, "Ce brouillon n'existe pas ou a déjà été publié.") from exc
    return {"doublons": doublons.doublons(a_part, semaine)}


@router.post("/{run_id}/publier")
def publier_brouillon(run_id: int) -> dict[str, object]:
    """Met le brouillon en service (cf. `publier`)."""
    try:
        return publier(run_id)
    except BrouillonIntrouvable as exc:
        raise HTTPException(404, "Ce brouillon n'existe pas ou a déjà été publié.") from exc
    except PublicationRefusee as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/{run_id}")
def supprimer_brouillon(run_id: int) -> dict[str, object]:
    try:
        supprimer(run_id)
    except BrouillonIntrouvable as exc:
        raise HTTPException(404, "Ce brouillon n'existe pas ou a déjà été publié.") from exc
    return {"supprime": run_id}
