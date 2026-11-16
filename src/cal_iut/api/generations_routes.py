"""Écran « Nouveau semestre » — générer un emploi du temps complet depuis
l'interface (lot 2, 16/11/2026). Routes réservées aux administrateurs.

L'API ne calcule rien : elle crée la génération, lance l'ouvrier
(`generation/ouvrier.py`, processus détaché) et relit son état sur disque
(`generation/taches.py`). Le résultat est un BROUILLON : le planning en
service n'est pas modifié et rien ne part vers Celcat.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cal_iut.api import accounts
from cal_iut.generation import taches, verification
from cal_iut.ingestion import mmi_previ

router = APIRouter(prefix="/generations", dependencies=[Depends(accounts.require_role("admin"))])


class GenerationRequest(BaseModel):
    semestre_group: str = Field(description="« odd » (S1, S3, S5) ou « even » (S2, S4, S6)")
    tentatives: int | None = None
    heures: float | None = None
    weeks: int | None = None
    fi_max_week: int | None = None
    num_workers: int | None = None


class SourceRequest(BaseModel):
    semestre_group: str = Field(description="« odd » (S1, S3, S5) ou « even » (S2, S4, S6)")


def _source(groupe: str) -> dict:
    """D'où viennent la maquette et la progression de ce groupe : la copie
    livrée avec l'application, ou ce qui a été récupéré depuis MMI Prévi.
    Jamais le contenu (noms d'enseignants, commentaires internes)."""
    copie = mmi_previ.etat_de_la_copie(taches.RACINE, groupe)
    if copie is None:
        return {"origine": "copie_livree"}
    return {"origine": "mmi_previ", **copie}


def _refuser_si_source_verrouillee(groupe: str) -> None:
    """Changer la maquette d'un semestre déjà publié changerait ses séances
    au prochain redémarrage du serveur, sans nouveau calcul. Et pendant une
    génération, le solveur relit la progression en cours de route."""
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    if taches.active() is not None:
        raise HTTPException(409, "Une génération est en cours. Attendez sa fin ou arrêtez-la avant de changer les sources.")
    from cal_iut.api.brouillons import groupe_du_run
    from cal_iut.api.state import get_repo

    if any(groupe_du_run(run) == groupe for run, _ in get_repo().runs_en_service()):
        raise HTTPException(
            409,
            f"Le {taches.GROUPES[groupe]['libelle'].lower()} est déjà en service : sa maquette ne se remplace pas "
            "depuis cet écran, ses séances changeraient sans nouveau calcul.",
        )


def _resume(etat: dict) -> dict:
    """Ce que la liste affiche d'une génération (sans les constats ni la
    liste des séances non placées)."""
    resultat = etat.get("resultat") or {}
    return {
        "id": etat["id"],
        "statut": etat["statut"],
        "semestre_group": etat["parametres"]["semestre_group"],
        "cree_le": etat.get("cree_le"),
        "cree_par": etat.get("cree_par"),
        "termine_le": etat.get("termine_le"),
        "run_id": etat.get("run_id"),
        "placees": resultat.get("placees"),
        "a_placer": resultat.get("a_placer"),
        "non_placees": len(resultat.get("non_placees") or []) if resultat else None,
    }


def _detail(etat: dict) -> dict:
    actif = etat["statut"] in taches.STATUTS_ACTIFS
    return {
        **etat,
        # Une génération « en cours » qui ne bat plus attend sa reprise
        # (redémarrage du serveur pendant le calcul).
        "vivante": taches.est_vivante(etat) if actif else False,
        "annulation_demandee": actif and (taches.dossier(etat["id"]) / "annuler").exists(),
        "journal": taches.fin_du_journal(etat["id"]),
    }


@router.get("")
def lister_generations() -> dict:
    etats = taches.lister()
    active = next((e for e in etats if e["statut"] in taches.STATUTS_ACTIFS), None)
    return {
        "groupes": [
            {"cle": cle, **infos, "parametres": taches.parametres_par_defaut(cle), "source": _source(cle)}
            for cle, infos in taches.GROUPES.items()
        ],
        "mmi_previ_configure": mmi_previ.configure(),
        "coeurs": taches.coeurs_disponibles(),
        "active": _detail(active) if active else None,
        "generations": [_resume(e) for e in etats],
    }


@router.post("", status_code=201)
def lancer_generation(body: GenerationRequest, request: Request) -> dict:
    demande = {cle: valeur for cle, valeur in body.model_dump().items() if valeur is not None}
    utilisateur = getattr(request.state, "user", None)
    par = getattr(utilisateur, "email", None) or "administrateur"
    if body.semestre_group in taches.GROUPES and taches.active() is None:
        # « À régler avant de générer » : même contrôle que celui affiché à
        # l'écran, refait ici parce que les données ont pu changer depuis.
        restants = [c for c in verification.avant_de_generer(body.semestre_group)["constats"] if c["bloquant"]]
        if restants:
            raise HTTPException(
                409,
                f"{len(restants)} point(s) à régler avant de générer : "
                + " ; ".join(c["message"] for c in restants[:3]),
            )
    try:
        etat = taches.creer(demande, par)
    except taches.GenerationDejaEnCours as exc:
        raise HTTPException(409, "Une génération est déjà en cours. Attendez sa fin ou annulez-la.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    taches.lancer(etat["id"])
    return _detail(etat)


@router.post("/sources/mmi-previ")
def recuperer_depuis_mmi_previ(body: SourceRequest, request: Request) -> dict:
    """Télécharge la maquette et la progression du semestre choisi depuis
    MMI Prévi et en fait la source des prochaines générations."""
    _refuser_si_source_verrouillee(body.semestre_group)
    utilisateur = getattr(request.state, "user", None)
    par = getattr(utilisateur, "email", None) or "administrateur"
    try:
        resultat = mmi_previ.recuperer(taches.RACINE, body.semestre_group, par)
    except mmi_previ.JetonAbsent as exc:
        raise HTTPException(503, str(exc)) from exc
    except mmi_previ.ErreurMmiPrevi as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"semestre_group": body.semestre_group, **resultat, "source": _source(body.semestre_group)}


@router.delete("/sources/mmi-previ/{groupe}")
def revenir_a_la_copie_livree(groupe: str) -> dict:
    _refuser_si_source_verrouillee(groupe)
    mmi_previ.supprimer_copie(taches.RACINE, groupe)
    return {"semestre_group": groupe, "source": _source(groupe)}


# ── Dates des SAE (lot 6) ─────────────────────────────────────────────


class DatesSaeRequest(BaseModel):
    dates: list[str] = Field(default_factory=list)


def _semestre_verrouille(groupe: str) -> str | None:
    """Pourquoi les dates SAE de ce groupe ne se modifient pas (None : elles
    se modifient). Même règle que pour la maquette."""
    try:
        _refuser_si_source_verrouillee(groupe)
    except HTTPException as exc:
        if exc.status_code == 422:
            raise
        return str(exc.detail)
    return None


def _sae_du_groupe(groupe: str) -> list[dict]:
    """Les SAE à volume des semestres du groupe, avec leurs journées : celles
    du fichier de l'établissement, et celles saisies à l'écran."""
    import json

    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae
    from cal_iut.ingestion.planning_loader import load_sae_corrections

    config = taches.RACINE / "data" / "config"
    chemin = taches.RACINE / "contraintes" / "09_dates_sae.json"
    if not chemin.exists():
        return []
    semestres = set(taches.GROUPES[groupe]["semestres"])
    saisies = reglages.dates_sae(config)
    try:
        corrigees = load_sae_corrections(config)[0]
    except ValueError:
        corrigees = {}
    par_solveur = load_solver_scheduled_sae(config)
    sortie = []
    for entree in json.loads(chemin.read_text(encoding="utf-8")).get("sae", []):
        code, semestre = str(entree.get("code_matiere") or "").strip(), str(entree.get("semestre") or "")
        volumes = entree.get("volumes_etudiant_seances") or {}
        seances = sum(int(volumes.get(k, 0) or 0) for k in ("cm", "td", "tp"))
        if semestre not in semestres or not code or not seances:
            continue
        officielles = sorted(
            {str(d) for f in entree.get("fenetres") or [] for d in f.get("dates") or []}
            | {d.isoformat() for d in corrigees.get(code, set())}
        )
        sortie.append({
            "code": code,
            "nom": str(entree.get("nom_matiere") or ""),
            "semestre": semestre,
            "parcours": str(entree.get("parcours_source") or ""),
            "seances": seances,
            "dates_officielles": officielles,
            "dates_saisies": saisies.get(code.upper(), []),
            "placee_par_le_calcul": (code.upper(), semestre) in par_solveur,
        })
    return sorted(sortie, key=lambda s: (s["semestre"], s["code"]))


@router.get("/sae/{groupe}")
def dates_des_sae(groupe: str) -> dict:
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    return {"semestre_group": groupe, "verrouille": _semestre_verrouille(groupe), "sae": _sae_du_groupe(groupe)}


@router.put("/sae/{groupe}/{code}")
def saisir_les_dates_d_une_sae(groupe: str, code: str, body: DatesSaeRequest, request: Request) -> dict:
    """Remplace les journées saisies à l'écran pour cette SAE. Refusé si le
    semestre est déjà en service : ses cours classiques ont été placés avec
    les dates d'alors."""
    from datetime import date

    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.constraints_loader import load_all_constraints

    _refuser_si_source_verrouillee(groupe)
    if code.upper() not in {s["code"].upper() for s in _sae_du_groupe(groupe)}:
        raise HTTPException(404, "Cette SAE n'appartient pas à ce semestre.")
    calendrier = load_all_constraints(taches.RACINE).calendar
    for brute in body.dates:
        try:
            jour = date.fromisoformat(str(brute))
        except ValueError as exc:
            raise HTTPException(422, f"Date invalide : {brute}") from exc
        if calendrier.date_to_week_day_any(jour) is None:
            raise HTTPException(
                422, f"Le {jour.strftime('%d/%m/%Y')} n'est pas un jour de cours du calendrier (week-end, férié ou vacances)."
            )
    utilisateur = getattr(request.state, "user", None)
    par = getattr(utilisateur, "email", None) or "administrateur"
    try:
        reglages.definir_dates_sae(taches.RACINE / "data" / "config", code, body.dates, par)
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    return dates_des_sae(groupe)


# ── Séances annulées (lot 6) ──────────────────────────────────────────


class AnnulationRequest(BaseModel):
    session_id: str
    motif: str = ""


def _annulations_verrouillees(groupe: str) -> str | None:
    motif = _semestre_verrouille(groupe)
    if motif and "en service" in motif:
        return (
            f"Le {taches.GROUPES[groupe]['libelle'].lower()} est déjà en service : ses séances annulées "
            "ne se modifient pas depuis cet écran, son planning changerait sans nouveau calcul."
        )
    return motif


def _seances_du_groupe(groupe: str) -> list:
    """Toutes les séances du groupe, annulées comprises."""
    import warnings

    from cal_iut.ingestion.pipeline import run_ingestion

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_ingestion(taches.RACINE / "data" / "config", semestre_group=groupe, avec_annulees=True).sessions


def _libelle_seance(seance, groupes: dict[str, str]) -> str:
    """« TD 3 · TD AB » : le type, le rang dans le module, le groupe."""
    import re

    type_ = getattr(seance.session_type, "value", str(seance.session_type))
    rang = re.match(rf"^{re.escape(seance.course_code)}-{re.escape(seance.semestre)}-[^-]+-(\d+)", seance.id)
    texte = f"{type_} {rang.group(1)}" if rang else seance.id
    qui = ", ".join(groupes.get(g, g) for g in seance.group_ids)
    return f"{texte} · {qui}" if qui else texte


def _libelles_des_groupes() -> dict[str, str]:
    from cal_iut.ingestion.config_loader import load_groups

    return {g.id: g.label for g in load_groups(taches.RACINE / "data" / "config")}


def _annulations(groupe: str) -> dict:
    from cal_iut.ingestion.config_loader import load_seances_annulees_entries

    seances = _seances_du_groupe(groupe)
    par_id = {s.id: s for s in seances}
    groupes = _libelles_des_groupes()
    semestres = set(taches.GROUPES[groupe]["semestres"])
    annulees = []
    for entree in load_seances_annulees_entries(taches.RACINE / "data" / "config"):
        seance = par_id.get(entree["session_id"])
        morceaux = entree["session_id"].split("-")
        # Une annulation dont la séance n'existe plus (la maquette a changé)
        # reste affichée dans son semestre, pour qu'on puisse la retirer.
        if seance is None and not (len(morceaux) > 1 and morceaux[1] in semestres):
            continue
        annulees.append({
            **entree,
            "existe": seance is not None,
            "code": seance.course_code if seance else morceaux[0],
            "nom": seance.course_name if seance else "",
            "libelle": _libelle_seance(seance, groupes) if seance else entree["session_id"],
        })
    modules: dict[str, dict] = {}
    for s in seances:
        m = modules.setdefault(s.course_code, {"code": s.course_code, "nom": s.course_name, "semestre": s.semestre, "seances": 0})
        m["seances"] += 1
    return {
        "semestre_group": groupe,
        "verrouille": _annulations_verrouillees(groupe),
        "annulees": sorted(annulees, key=lambda a: a["session_id"]),
        "modules": sorted(modules.values(), key=lambda m: (m["semestre"], m["code"])),
    }


@router.get("/annulations/{groupe}")
def seances_annulees(groupe: str) -> dict:
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    return _annulations(groupe)


@router.get("/annulations/{groupe}/seances")
def seances_d_un_module(groupe: str, code: str) -> dict:
    """Les séances d'un module, pour choisir celle qu'on annule."""
    from cal_iut.ingestion.config_loader import load_seances_annulees

    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    annulees = load_seances_annulees(taches.RACINE / "data" / "config")
    groupes = _libelles_des_groupes()
    return {
        "code": code,
        "seances": [
            {"id": s.id, "libelle": _libelle_seance(s, groupes), "annulee": s.id in annulees}
            for s in _seances_du_groupe(groupe)
            if s.course_code.upper() == code.upper()
        ],
    }


@router.post("/annulations/{groupe}", status_code=201)
def annuler_une_seance(groupe: str, body: AnnulationRequest, request: Request) -> dict:
    """La séance ne sera pas placée à la prochaine génération. Refusé si le
    semestre est en service : son planning perdrait la séance au prochain
    redémarrage, sans que personne l'ait décidé à cet écran."""
    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.config_loader import load_seances_annulees

    _refuser_si_source_verrouillee(groupe)
    config = taches.RACINE / "data" / "config"
    session_id = body.session_id.strip()
    if session_id not in {s.id for s in _seances_du_groupe(groupe)}:
        raise HTTPException(404, "Cette séance n'existe pas dans ce semestre.")
    if session_id in load_seances_annulees(config):
        raise HTTPException(409, "Cette séance est déjà annulée.")
    utilisateur = getattr(request.state, "user", None)
    par = getattr(utilisateur, "email", None) or "administrateur"
    try:
        reglages.annuler_seance(config, session_id, body.motif, par)
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    return _annulations(groupe)


@router.delete("/annulations/{groupe}")
def retablir_une_seance(groupe: str, session_id: str) -> dict:
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    config = taches.RACINE / "data" / "config"
    entree = next((e for e in _annulations(groupe)["annulees"] if e["session_id"] == session_id), None)
    if entree is None:
        raise HTTPException(404, "Cette séance n'est pas annulée dans ce semestre.")
    reglages.retablir_seance(config, session_id, livree=entree["origine"] == "livree")
    return _annulations(groupe)


@router.get("/verification/{groupe}")
def a_regler_avant_de_generer(groupe: str) -> dict:
    """Ce qu'il reste à régler dans les données de ce semestre avant de
    lancer le calcul. Une seconde environ ; ne lance pas le solveur."""
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    try:
        return verification.avant_de_generer(groupe)
    except verification.GenerationEnCours as exc:
        raise HTTPException(409, "Une génération est en cours : la vérification reprendra à sa fin.") from exc


@router.get("/{generation_id}")
def lire_generation(generation_id: str) -> dict:
    try:
        return _detail(taches.lire(generation_id))
    except taches.GenerationIntrouvable as exc:
        raise HTTPException(404, "Génération introuvable.") from exc


@router.post("/{generation_id}/annuler")
def annuler_generation(generation_id: str) -> dict:
    try:
        return _detail(taches.demander_annulation(generation_id))
    except taches.GenerationIntrouvable as exc:
        raise HTTPException(404, "Génération introuvable.") from exc
