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
    spread_weight: int | None = None
    arret_si_complet: bool | None = None
    referent_sae_strict: bool | None = None


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
            {
                "cle": cle, **infos, "parametres": taches.parametres_par_defaut(cle),
                "parametres_d_origine": taches.parametres_d_origine(cle), "source": _source(cle),
            }
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
    confiees = {str(a["course_code"]).upper() for a in reglages.sae_par_le_calcul(config)}
    modules = _modules_du_groupe(groupe)
    phases = _phases_des_sae(config)
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
            # Vrai : choix fait à l'écran, qu'on peut y défaire.
            "placement_saisi": code.upper() in confiees,
            "enseignants": [
                {"code": e["code"], "nom": e["nom"]} for e in modules.get(code, {}).get("enseignants", [])
            ],
            "phases": [
                {**p, "nom": next((e["nom"] for e in modules.get(code, {}).get("enseignants", [])
                                   if e["code"] == p["teacher_code"]), p["teacher_code"])}
                for p in phases.get(code.upper(), [])
            ],
        })
    return sorted(sortie, key=lambda s: (s["semestre"], s["code"]))


def _phases_des_sae(config) -> dict[str, list[dict]]:
    """Par SAE, les périodes d'encadrement : celles du fichier livré (sans
    `id`) puis celles saisies à l'écran."""
    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.config_loader import load_sae_teacher_phases

    saisies = {
        (str(a["course_code"]).upper(), str(a["teacher_code"]).upper(), a["debut"], a["fin"]): a
        for a in reglages.phases_sae(config)
    }
    sortie: dict[str, list[dict]] = {}
    for p in load_sae_teacher_phases(config):
        saisie = saisies.get((p.course_code, p.teacher_code, p.debut, p.fin))
        sortie.setdefault(p.course_code, []).append({
            "id": saisie["id"] if saisie else None,
            "origine": "ajoutee" if saisie else "livree",
            "teacher_code": p.teacher_code,
            "debut": p.debut,
            "fin": p.fin,
            "sauf": list(p.exclure),
            "motif": " ".join(str(p.note or "").split()),
        })
    for liste in sortie.values():
        liste.sort(key=lambda p: (p["debut"], p["teacher_code"]))
    return sortie


class PlacementSaeRequest(BaseModel):
    par_le_calcul: bool
    motif: str = ""


class PhaseSaeRequest(BaseModel):
    teacher_code: str
    debut: str
    fin: str
    motif: str = ""


def _sae(groupe: str, code: str) -> dict:
    sae = next((s for s in _sae_du_groupe(groupe) if s["code"].upper() == code.upper()), None)
    if sae is None:
        raise HTTPException(404, "Cette SAE n'appartient pas à ce semestre.")
    return sae


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
    sae = _sae(groupe, code)
    if body.dates and sae["placee_par_le_calcul"]:
        raise HTTPException(
            422, "Cette SAE est placée par le calcul : elle n'a pas de journées réservées. Défaites d'abord ce choix."
        )
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


@router.put("/sae/{groupe}/{code}/placement")
def confier_une_sae_au_calcul(groupe: str, code: str, body: PlacementSaeRequest, request: Request) -> dict:
    """Une SAE sans journées réservées peut être placée par le calcul,
    séance par séance, comme un module ordinaire."""
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    sae = _sae(groupe, code)
    if sae["placee_par_le_calcul"] and not sae["placement_saisi"]:
        raise HTTPException(409, "Ce choix vient des réglages d'origine : il ne se modifie pas depuis cet écran.")
    if body.par_le_calcul and (sae["dates_officielles"] or sae["dates_saisies"]):
        raise HTTPException(
            422,
            "Cette SAE a des journées réservées : ses séances s'y tiennent. "
            "Retirez d'abord ses dates pour la confier au calcul.",
        )
    try:
        reglages.confier_sae_au_calcul(
            taches.RACINE / "data" / "config", sae["code"], sae["semestre"], body.par_le_calcul, body.motif,
            _auteur(request),
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    return dates_des_sae(groupe)


@router.post("/sae/{groupe}/{code}/phases", status_code=201)
def ajouter_une_phase_de_sae(groupe: str, code: str, body: PhaseSaeRequest, request: Request) -> dict:
    """Un enseignant n'encadre la SAE que pendant cette période : il reste
    disponible pour ses cours les autres journées de la SAE. Sans période,
    il est tenu pour pris toutes les journées de la SAE."""
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    sae = _sae(groupe, code)
    enseignant = body.teacher_code.strip().upper()
    if enseignant not in {e["code"] for e in sae["enseignants"]}:
        raise HTTPException(422, f"{enseignant or 'Cet enseignant'} n'encadre pas {sae['code']}.")
    try:
        reglages.ajouter_phase_sae(
            taches.RACINE / "data" / "config",
            {"course_code": sae["code"], "semestre": sae["semestre"], "teacher_code": enseignant,
             "debut": body.debut, "fin": body.fin, "motif": body.motif},
            _auteur(request),
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    return dates_des_sae(groupe)


@router.delete("/sae/{groupe}/{code}/phases/{identifiant}")
def retirer_une_phase_de_sae(groupe: str, code: str, identifiant: str) -> dict:
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    if not any(p["id"] == identifiant for p in _sae(groupe, code)["phases"]):
        raise HTTPException(404, "Cette période n'existe pas pour cette SAE.")
    reglages.retirer_phase_sae(taches.RACINE / "data" / "config", identifiant)
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


# ── Règles de modules (lot 6) ─────────────────────────────────────────

_DUREES = {2: "3 h", 3: "4 h 30"}


class SeancesLonguesRequest(BaseModel):
    code: str
    type: str
    creneaux: int = 2
    motif: str = ""


class PeriodeRequest(BaseModel):
    code: str
    type: str | None = None
    debut: str | None = None
    fin: str | None = None
    motif: str = ""


class RepartitionRequest(BaseModel):
    code: str
    type: str | None = None
    mode: str = "alterne"
    ordre: list[str] = []
    motif: str = ""


class EtapeRequest(BaseModel):
    code: str
    type: str | None = None
    de: int | None = None
    a: int | None = None


class ProjetRequest(BaseModel):
    nom: str
    etapes: list[EtapeRequest]
    jours_par_semaine: int | None = None
    motif: str = ""


class OrdreRequest(BaseModel):
    code: str
    ordre: list[str]
    motif: str = ""


class DuoRequest(BaseModel):
    code: str
    enseignants: list[str]
    salles: list[str]
    # Groupes de TP de chacun : `{code enseignant: [lettres]}`. Vide = le
    # partage habituel de la maquette.
    groupes: dict[str, list[str]] = {}
    # TP (salles voisines) ou TD (même instant, salles habituelles) ; rangs en
    # séances de 1 h 30 par groupe, à partir de 1.
    type: str = "TP"
    de: int | None = None
    a: int | None = None
    motif: str = ""


_MODES = {
    "alterne": "À tour de rôle, une séance chacun",
    "par_groupes": "Par groupes entiers",
    "sequentiel": "L'un après l'autre",
}


def _regles_verrouillees(groupe: str) -> str | None:
    motif = _semestre_verrouille(groupe)
    if motif and "en service" in motif:
        return (
            f"Le {taches.GROUPES[groupe]['libelle'].lower()} est déjà en service : ses règles de modules "
            "ne se modifient pas depuis cet écran, ses séances changeraient sans nouveau calcul."
        )
    return motif


def _modules_du_groupe(groupe: str) -> dict[str, dict]:
    """Les modules du groupe, avec le nombre de séances de chaque type."""
    import re

    modules: dict[str, dict] = {}
    enseignants: dict[str, dict[str, str]] = {}
    hors_cm: dict[str, set[str]] = {}
    lettres: dict[str, set[str]] = {}
    lettres_td: dict[str, set[str]] = {}
    for s in _seances_du_groupe(groupe):
        type_ = getattr(s.session_type, "value", str(s.session_type))
        m = modules.setdefault(s.course_code, {
            "code": s.course_code, "nom": s.course_name, "semestre": s.semestre, "types": {},
        })
        # Une séance par cohorte : on compte les rangs, pas les groupes.
        m["types"].setdefault(type_, set()).add(s.sequence_order)
        for e in s.teachers:
            enseignants.setdefault(s.course_code, {})[e.code] = _nom_enseignant(e)
            if type_ in ("TD", "TP"):
                hors_cm.setdefault(s.course_code, set()).add(e.code)
        if type_ in ("TD", "TP"):
            for g in s.group_ids:
                lettre = re.search(rf"-{type_.lower()}-([a-z]{'+' if type_ == 'TD' else ''})$", g)
                if lettre:
                    cible = lettres if type_ == "TP" else lettres_td
                    cible.setdefault(s.course_code, set()).add(lettre.group(1).upper())
    for code, m in modules.items():
        m["types"] = {t: len(rangs) for t, rangs in sorted(m["types"].items())}
        m["enseignants"] = [
            {"code": c, "nom": n, "td_tp": c in hors_cm.get(code, set())}
            for c, n in sorted(enseignants.get(code, {}).items(), key=lambda p: p[1])
        ]
        m["groupes_tp"] = sorted(lettres.get(code, set()))
        m["groupes_td"] = sorted(lettres_td.get(code, set()))
    return modules


def _nom_enseignant(e) -> str:
    prenom = str(getattr(e, "prenom", "") or "").strip().title()
    nom = str(getattr(e, "nom", "") or "").strip().upper()
    return f"{prenom} {nom}".strip() or e.code


def _regles(groupe: str) -> dict:
    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.config_loader import load_double_sessions, load_session_date_windows

    config = taches.RACINE / "data" / "config"
    modules = _modules_du_groupe(groupe)
    semestres = set(taches.GROUPES[groupe]["semestres"])
    saisies_longues = {
        (a["course_code"], str(a.get("session_type"))): a for a in reglages.regles_de_modules(config, "doubles_seances")
    }
    saisies_periodes = reglages.regles_de_modules(config, "periodes_modules")

    longues = []
    for r in load_double_sessions(config):
        if r.course_code not in modules:
            continue
        # L'ajout refuse un module et un type déjà réglés : une règle saisie
        # n'en double jamais une livrée.
        saisie = saisies_longues.get((r.course_code, r.session_type.value))
        longues.append({
            "id": saisie["id"] if saisie else None,
            "origine": "ajoutee" if saisie else "livree",
            "code": r.course_code,
            "nom": modules[r.course_code]["nom"],
            "type": r.session_type.value,
            "creneaux": r.slots_per_session,
            "duree": _DUREES.get(r.slots_per_session, f"{r.slots_per_session} créneaux"),
            "motif": str(r.note or "").strip(),
        })

    periodes = []
    for r in load_session_date_windows(config, avec_saisies=False):
        if r.semestre not in semestres:
            continue
        periodes.append({
            "id": None,
            "origine": "livree",
            "code": r.course_code,
            "nom": modules.get(r.course_code, {}).get("nom", ""),
            "type": r.session_type.value if r.session_type else None,
            "rangs": list(r.sequence_orders),
            "debut": r.start_date,
            "fin": r.end_date,
            "dates": list(r.only_dates),
            "motif": str(r.note or "").strip(),
        })
    for a in saisies_periodes:
        if a.get("semestre") not in semestres:
            continue
        periodes.append({
            "id": a["id"],
            "origine": "ajoutee",
            "code": a["course_code"],
            "nom": modules.get(a["course_code"], {}).get("nom", ""),
            "type": a.get("session_type"),
            "rangs": [],
            "debut": a.get("debut"),
            "fin": a.get("fin"),
            "dates": [],
            "motif": str(a.get("motif") or ""),
        })
    return {
        "semestre_group": groupe,
        "verrouille": _regles_verrouillees(groupe),
        "modules": sorted(modules.values(), key=lambda m: (m["semestre"], m["code"])),
        "seances_longues": sorted(longues, key=lambda r: (r["code"], r["type"])),
        "periodes": sorted(periodes, key=lambda r: (r["code"], r["debut"] or "", r["fin"] or "")),
        **_regles_des_enseignants(config, modules, semestres),
        "projets": [
            {
                "id": a["id"],
                "nom": a.get("nom", ""),
                "semestre": a.get("semestre"),
                "jours_par_semaine": a.get("jours_par_semaine"),
                "etapes": [
                    {**e, "nom": modules.get(e["course_code"], {}).get("nom", "")} for e in a.get("etapes") or []
                ],
                "motif": str(a.get("motif") or ""),
            }
            for a in reglages.regles_de_modules(config, "projets_modules")
            if a.get("semestre") in semestres
        ],
    }


def _regles_des_enseignants(config, modules: dict[str, dict], semestres: set[str]) -> dict:
    """Répartitions, ordres et duos : les règles livrées et celles saisies à
    l'écran, pour les modules de ce semestre."""
    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.config_loader import (
        load_course_teacher_orders,
        load_rooms,
        load_teacher_distributions,
        load_teacher_duos,
    )

    def noms(code_module: str, codes) -> list[dict]:
        connus = {e["code"]: e["nom"] for e in modules[code_module]["enseignants"]}
        return [{"code": c, "nom": connus.get(c, c)} for c in codes]

    salles = {r.id: r.label for r in load_rooms(config) if not r.combines}
    saisies_rep = {
        (a["course_code"], a.get("session_type")): a for a in reglages.regles_de_modules(config, "repartitions")
    }
    saisies_ordres = {a["course_code"]: a for a in reglages.regles_de_modules(config, "ordres_enseignants")}
    saisies_duos = {
        (a["course_code"], tuple(a.get("teacher_codes") or ()), a.get("session_type") or "TP"): a
        for a in reglages.regles_de_modules(config, "duos")
    }

    repartitions = []
    for r in load_teacher_distributions(config):
        if r.course_code not in modules or r.semestre not in semestres:
            continue
        type_ = r.session_type.value if r.session_type else None
        saisie = saisies_rep.get((r.course_code, type_))
        saisie = saisie if saisie and saisie.get("mode") == r.mode else None
        repartitions.append({
            "id": saisie["id"] if saisie else None,
            "origine": "ajoutee" if saisie else "livree",
            "code": r.course_code,
            "nom": modules[r.course_code]["nom"],
            "type": type_,
            "mode": r.mode,
            "libelle": _MODES.get(r.mode, r.mode),
            "ordre": noms(r.course_code, r.teacher_order),
            "motif": str(r.note or "").strip(),
        })

    ordres = []
    for r in load_course_teacher_orders(config):
        if r.course_code not in modules or r.semestre not in semestres:
            continue
        saisie = saisies_ordres.get(r.course_code)
        saisie = saisie if saisie and list(saisie.get("teacher_order") or []) == list(r.teacher_order) else None
        ordres.append({
            "id": saisie["id"] if saisie else None,
            "origine": "ajoutee" if saisie else "livree",
            "code": r.course_code,
            "nom": modules[r.course_code]["nom"],
            "ordre": noms(r.course_code, r.teacher_order),
            "motif": str(r.note or "").strip(),
        })

    duos = []
    for d in load_teacher_duos(config):
        for code in d.course_codes:
            if code not in modules:
                continue
            type_duo = d.session_types[0] if d.session_types else "TP"
            saisie = saisies_duos.get((code, tuple(d.teacher_codes), type_duo))
            duos.append({
                "type": type_duo,
                "de": d.rang_de,
                "a": d.rang_a,
                "id": saisie["id"] if saisie else None,
                "origine": "ajoutee" if saisie else "livree",
                "code": code,
                "nom": modules[code]["nom"],
                "enseignants": noms(code, d.teacher_codes),
                "salles": [{"id": s, "label": salles.get(s, s)} for s in d.rare_rooms],
                "groupes": {c: list(g) for c, g in (d.group_overrides or {}).items()},
                "motif": str(d.note or "").strip(),
            })
    return {
        "salles": [{"id": i, "label": l} for i, l in sorted(salles.items(), key=lambda p: p[1])],
        "modes": [{"mode": m, "libelle": l} for m, l in _MODES.items()],
        "repartitions": sorted(repartitions, key=lambda r: (r["code"], r["type"] or "")),
        "ordres": sorted(ordres, key=lambda r: r["code"]),
        "duos": sorted(duos, key=lambda r: (r["code"], r["type"], r["enseignants"][0]["code"])),
    }


def _regles_changees() -> None:
    """Le solveur garde les fenêtres de dates en mémoire."""
    try:
        from cal_iut.solver import decomposed

        decomposed._session_date_windows.cache_clear()
    except Exception:  # noqa: BLE001 — un cache qu'on ne peut pas vider ne doit pas refuser la saisie
        pass


def _auteur(request: Request) -> str:
    return getattr(getattr(request.state, "user", None), "email", None) or "administrateur"


@router.get("/regles/{groupe}")
def regles_de_modules(groupe: str) -> dict:
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    return _regles(groupe)


@router.post("/regles/{groupe}/seances-longues", status_code=201)
def ajouter_des_seances_longues(groupe: str, body: SeancesLonguesRequest, request: Request) -> dict:
    """Les séances de ce type, pour ce module, sont regroupées en blocs de
    3 h ou 4 h 30. Refusé si le semestre est en service : ses séances
    changeraient d'identifiant, donc de place."""
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    etat = _regles(groupe)
    module = next((m for m in etat["modules"] if m["code"] == body.code), None)
    type_ = body.type.strip().upper()
    if module is None:
        raise HTTPException(404, "Ce module n'appartient pas à ce semestre.")
    if any(r["code"] == body.code and r["type"] == type_ for r in etat["seances_longues"]):
        raise HTTPException(409, f"Les {type_} de {body.code} sont déjà regroupés. Retirez la règle pour la changer.")
    if type_ in reglages.TYPES_DE_SEANCE and module["types"].get(type_, 0) < body.creneaux:
        raise HTTPException(
            422, f"{body.code} n'a pas assez de {type_} pour former un bloc de {_DUREES.get(body.creneaux, '?')}."
        )
    try:
        reglages.ajouter_regle_de_module(
            taches.RACINE / "data" / "config",
            "doubles_seances",
            {"course_code": body.code, "session_type": type_, "slots_per_session": body.creneaux, "motif": body.motif},
            _auteur(request),
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    return _regles(groupe)


@router.post("/regles/{groupe}/periodes", status_code=201)
def ajouter_une_periode(groupe: str, body: PeriodeRequest, request: Request) -> dict:
    """Les séances du module (ou d'un seul type) se placent dans cette
    période, bornes comprises."""
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    module = _modules_du_groupe(groupe).get(body.code)
    if module is None:
        raise HTTPException(404, "Ce module n'appartient pas à ce semestre.")
    type_ = (body.type or "").strip().upper() or None
    if type_ and type_ in reglages.TYPES_DE_SEANCE and not module["types"].get(type_):
        raise HTTPException(422, f"{body.code} n'a aucun {type_}.")
    try:
        reglages.ajouter_regle_de_module(
            taches.RACINE / "data" / "config",
            "periodes_modules",
            {
                "course_code": body.code, "semestre": module["semestre"], "session_type": type_,
                "debut": body.debut, "fin": body.fin, "motif": body.motif,
            },
            _auteur(request),
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _regles_changees()
    return _regles(groupe)


def _module_et_enseignants(etat: dict, code: str, codes: list[str], *, hors_cm: bool = False) -> dict:
    module = next((m for m in etat["modules"] if m["code"] == code), None)
    if module is None:
        raise HTTPException(404, "Ce module n'appartient pas à ce semestre.")
    connus = {e["code"] for e in module["enseignants"] if e["td_tp"] or not hors_cm}
    inconnus = [c for c in codes if c not in connus]
    if inconnus:
        quoi = "n'assure aucun TD ni TP de" if hors_cm else "n'enseigne pas dans"
        raise HTTPException(422, f"{', '.join(inconnus)} {quoi} {code}.")
    return module


def _enregistrer_regle(groupe: str, nom: str, entree: dict, request: Request) -> dict:
    from cal_iut.ingestion import reglages

    try:
        reglages.ajouter_regle_de_module(taches.RACINE / "data" / "config", nom, entree, _auteur(request))
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _regles_changees()
    return _regles(groupe)


@router.post("/regles/{groupe}/repartitions", status_code=201)
def ajouter_une_repartition(groupe: str, body: RepartitionRequest, request: Request) -> dict:
    """Comment les TD et les TP d'un module se partagent entre ses
    enseignants. Les volumes de chacun ne changent pas."""
    _refuser_si_source_verrouillee(groupe)
    etat = _regles(groupe)
    ordre = [c.strip().upper() for c in body.ordre if c.strip()]
    module = _module_et_enseignants(etat, body.code, ordre, hors_cm=True)
    if sum(1 for e in module["enseignants"] if e["td_tp"]) < 2:
        raise HTTPException(422, f"{body.code} n'a qu'un enseignant en TD et en TP : il n'y a rien à répartir.")
    type_ = (body.type or "").strip().upper() or None
    if type_ and type_ != "CM" and not module["types"].get(type_):
        raise HTTPException(422, f"{body.code} n'a aucun {type_}.")
    for r in etat["repartitions"]:
        if r["code"] == body.code and (r["type"] is None or type_ is None or r["type"] == type_):
            raise HTTPException(
                409, f"La répartition de {body.code} est déjà réglée. Retirez la règle pour la changer."
            )
    return _enregistrer_regle(groupe, "repartitions", {
        "course_code": body.code, "semestre": module["semestre"], "session_type": type_,
        "mode": body.mode, "teacher_order": ordre, "motif": body.motif,
    }, request)


@router.post("/regles/{groupe}/projets", status_code=201)
def ajouter_un_projet(groupe: str, body: ProjetRequest, request: Request) -> dict:
    """Plusieurs modules qui se suivent dans l'ordre donné, sur au plus N jours
    par semaine. Ce sont des préférences : le calcul les respecte quand il le peut."""
    _refuser_si_source_verrouillee(groupe)
    etat = _regles(groupe)
    modules = {m["code"]: m for m in etat["modules"]}
    codes = [e.code.strip().upper() for e in body.etapes]
    inconnus = [c for c in codes if c not in modules]
    if inconnus:
        raise HTTPException(422, f"Module inconnu dans ce semestre : {', '.join(inconnus)}.")
    semestres = {modules[c]["semestre"] for c in codes}
    if len(semestres) != 1:
        raise HTTPException(422, "Les étapes d'un projet appartiennent au même semestre.")
    return _enregistrer_regle(groupe, "projets_modules", {
        "nom": body.nom, "semestre": semestres.pop(), "jours_par_semaine": body.jours_par_semaine,
        "etapes": [{"course_code": e.code, "session_type": e.type, "de": e.de, "a": e.a} for e in body.etapes],
        "motif": body.motif,
    }, request)


@router.post("/regles/{groupe}/ordres", status_code=201)
def ajouter_un_ordre(groupe: str, body: OrdreRequest, request: Request) -> dict:
    """Les séances du premier enseignant se placent plutôt avant celles du
    suivant. C'est une préférence : le calcul la respecte quand il le peut."""
    _refuser_si_source_verrouillee(groupe)
    etat = _regles(groupe)
    ordre = [c.strip().upper() for c in body.ordre if c.strip()]
    module = _module_et_enseignants(etat, body.code, ordre)
    if any(r["code"] == body.code for r in etat["ordres"]):
        raise HTTPException(409, f"L'ordre des enseignants de {body.code} est déjà réglé. Retirez la règle pour la changer.")
    return _enregistrer_regle(groupe, "ordres_enseignants", {
        "course_code": body.code, "semestre": module["semestre"], "teacher_order": ordre, "motif": body.motif,
    }, request)


@router.post("/regles/{groupe}/duos", status_code=201)
def ajouter_un_duo(groupe: str, body: DuoRequest, request: Request) -> dict:
    """Deux enseignants font leurs séances en même temps, chacun avec ses
    groupes : les TP dans deux salles voisines, les TD dans leurs salles
    habituelles, éventuellement pour une partie seulement des séances."""
    _refuser_si_source_verrouillee(groupe)
    etat = _regles(groupe)
    duo = [c.strip().upper() for c in body.enseignants if c.strip()]
    module = _module_et_enseignants(etat, body.code, duo, hors_cm=True)
    type_ = (body.type or "TP").strip().upper()
    if type_ not in ("TD", "TP"):
        raise HTTPException(422, "Un duo concerne les TD ou les TP.")
    if not module["types"].get(type_):
        raise HTTPException(422, f"{body.code} n'a aucun {type_} : choisissez un autre type.")
    connues = {s["id"] for s in etat["salles"]}
    if any(s not in connues for s in body.salles):
        raise HTTPException(422, "Salle inconnue.")
    for r in etat["duos"]:
        deja = {e["code"] for e in r["enseignants"]} & set(duo)
        if r["code"] == body.code and r.get("type", "TP") == type_ and deja:
            raise HTTPException(409, f"{', '.join(sorted(deja))} fait déjà partie d'un duo de {type_} sur {body.code}.")
    groupes = {c.strip().upper(): sorted({g.strip().upper() for g in l if g.strip()}) for c, l in body.groupes.items()}
    groupes = {c: l for c, l in groupes.items() if l} or None
    if groupes:
        # Les groupes déjà confiés à un autre duo du module ne sont plus à prendre.
        pris = {
            g for r in etat["duos"] if r["code"] == body.code and r.get("type", "TP") == type_
            for lettres in r["groupes"].values() for g in lettres
        }
        existants = module["groupes_td"] if type_ == "TD" else module["groupes_tp"]
        if any(g not in existants or g in pris for lettres in groupes.values() for g in lettres):
            raise HTTPException(422, f"Un de ces groupes de {type_} n'existe pas ou appartient déjà à un autre duo.")
    etat = _enregistrer_regle(groupe, "duos", {
        "course_code": body.code, "semestre": module["semestre"], "teacher_codes": duo,
        "rare_rooms": body.salles, "group_overrides": groupes, "motif": body.motif,
        "session_type": type_, "rang_de": body.de, "rang_a": body.a,
    }, request)
    _duos_a_jour()
    return etat


def _duos_a_jour() -> None:
    """Les plannings déjà chargés par le serveur connaissent le nouveau duo
    sans redémarrage."""
    from cal_iut.api import state as etats
    from cal_iut.ingestion.config_loader import load_teacher_duos

    duos = load_teacher_duos(taches.RACINE / "data" / "config")
    for etat in etats.etats_charges():
        etat.teacher_duos = list(duos)


_LISTES = {
    "seances-longues": ("doubles_seances", "seances_longues"),
    "periodes": ("periodes_modules", "periodes"),
    "repartitions": ("repartitions", "repartitions"),
    "ordres": ("ordres_enseignants", "ordres"),
    "duos": ("duos", "duos"),
    "projets": ("projets_modules", "projets"),
}


@router.delete("/regles/{groupe}/{nom}/{identifiant}")
def retirer_une_regle(groupe: str, nom: str, identifiant: str) -> dict:
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    if nom not in _LISTES:
        raise HTTPException(404, "Règle inconnue.")
    reglage, liste = _LISTES[nom]
    etat = _regles(groupe)
    if not any(r["id"] == identifiant for r in etat[liste]):
        raise HTTPException(404, "Cette règle n'existe pas dans ce semestre.")
    reglages.retirer_regle_de_module(taches.RACINE / "data" / "config", reglage, identifiant)
    _regles_changees()
    if nom == "duos":
        _duos_a_jour()
    return _regles(groupe)


# ── Début et fin des cours du semestre ────────────────────────────────


class PeriodeDesCoursRequest(BaseModel):
    debut: str
    fin: str
    # Dernier jour de cours des alternants. Absent : inchangé. `null` : ils
    # finissent avec les autres.
    fin_alternants: str | None = None


def _vacances(calendrier, debut, fin) -> list[dict]:
    """Les coupures d'au moins trois jours ouvrés entre `debut` et `fin`."""
    from datetime import timedelta

    sortie, courante = [], []
    jour = debut
    while jour <= fin:
        if jour.weekday() < 5:
            if jour in calendrier.blocked_dates:
                courante.append(jour)
            else:
                if len(courante) >= 3:
                    sortie.append({"debut": courante[0].isoformat(), "fin": courante[-1].isoformat()})
                courante = []
        jour += timedelta(days=1)
    if len(courante) >= 3:
        sortie.append({"debut": courante[0].isoformat(), "fin": courante[-1].isoformat()})
    return sortie


def _periode(groupe: str) -> dict:
    from cal_iut.calendar.academic import (
        build_default_calendar_2026_2027,
        default_horizon_weeks,
        fin_des_alternants,
        fin_des_alternants_de_reference,
        periode_des_cours,
        periodes_de_reference,
        periodes_saisies,
        semaines_du_calcul,
    )
    from cal_iut.ingestion import reglages
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR

    calendrier = build_default_calendar_2026_2027()
    debut, fin = periode_des_cours(calendrier, groupe)
    origine = periodes_de_reference()[groupe]
    alternants = fin_des_alternants(groupe)
    alternants = alternants if alternants and alternants > fin else None
    alternants_origine = fin_des_alternants_de_reference(groupe)
    autre = "even" if groupe == "odd" else "odd"
    autre_debut, autre_fin = periode_des_cours(calendrier, autre)
    motif = _semestre_verrouille(groupe)
    if motif and "en service" in motif:
        motif = (
            f"Le {taches.GROUPES[groupe]['libelle'].lower()} est déjà en service : ses dates ne se modifient "
            "plus, tout son planning serait décalé."
        )
    return {
        "semestre_group": groupe,
        "verrouille": motif,
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "fin_alternants": alternants.isoformat() if alternants else None,
        "personnalise": groupe in periodes_saisies()
        or groupe in reglages.fins_alternants(taches.RACINE / "data" / "config"),
        "origine": {
            "debut": origine[0].isoformat(),
            "fin": origine[1].isoformat(),
            "fin_alternants": alternants_origine.isoformat() if alternants_origine else None,
        },
        "semaines": default_horizon_weeks(calendrier, SEMESTRE_GROUP_ANCHOR[groupe]),
        # Semaines de cours jusqu'au dernier jour des alternants, quand ils
        # finissent après les autres.
        "semaines_alternants": semaines_du_calcul(calendrier, groupe)[0],
        "vacances": _vacances(calendrier, debut, fin),
        "autre": {
            "libelle": taches.GROUPES[autre]["libelle"],
            "debut": autre_debut.isoformat(),
            "fin": autre_fin.isoformat(),
            "chevauche": debut <= autre_fin and autre_debut <= fin,
        },
    }


def _calendriers_a_jour() -> None:
    """Les plannings déjà chargés par le serveur lisent les nouvelles dates
    sans redémarrage."""
    from cal_iut.api import state as etats
    from cal_iut.calendar.academic import periodes_en_vigueur

    saisies = periodes_en_vigueur()
    for etat in etats.etats_charges():
        etat.calendar.periodes = dict(saisies)


@router.get("/periode/{groupe}")
def periode_des_cours_du_semestre(groupe: str) -> dict:
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    return _periode(groupe)


@router.put("/periode/{groupe}")
def fixer_la_periode_des_cours(groupe: str, body: PeriodeDesCoursRequest, request: Request) -> dict:
    """Premier et dernier jour de cours du semestre. Refusé si le semestre
    est en service : ses séances sont rangées par numéro de semaine depuis
    le début des cours, elles changeraient toutes de date."""
    from datetime import date

    from cal_iut.calendar.academic import build_default_calendar_2026_2027, teaching_weeks_until
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    calendrier = build_default_calendar_2026_2027()
    jours = {}
    for nom, brute in (("premier", body.debut), ("dernier", body.fin)):
        try:
            jour = date.fromisoformat(str(brute))
        except ValueError as exc:
            raise HTTPException(422, f"Le {nom} jour de cours n'est pas une date valide.") from exc
        if calendrier.date_to_week_day_any(jour) is None or jour in calendrier.blocked_dates:
            raise HTTPException(
                422,
                f"Le {jour.strftime('%d/%m/%Y')} n'est pas un jour de cours du calendrier "
                "(week-end, férié, vacances ou hors de l'année).",
            )
        jours[nom] = jour
    if jours["premier"] >= jours["dernier"]:
        raise HTTPException(422, "Le dernier jour de cours doit être après le premier.")
    lundi_suivant = jours["dernier"].fromordinal(jours["dernier"].toordinal() - jours["dernier"].weekday() + 7)
    if teaching_weeks_until(calendrier, jours["premier"], lundi_suivant) < 4:
        raise HTTPException(422, "Un semestre compte au moins quatre semaines de cours.")
    regler_alternants = "fin_alternants" in body.model_fields_set
    if regler_alternants and body.fin_alternants:
        try:
            alternants = date.fromisoformat(body.fin_alternants)
        except ValueError as exc:
            raise HTTPException(422, "Le dernier jour de cours des alternants n'est pas une date valide.") from exc
        if calendrier.date_to_week_day_any(alternants) is None or alternants in calendrier.blocked_dates:
            raise HTTPException(
                422,
                f"Le {alternants.strftime('%d/%m/%Y')} n'est pas un jour de cours du calendrier "
                "(week-end, férié, vacances ou hors de l'année).",
            )
        if alternants <= jours["dernier"]:
            raise HTTPException(
                422,
                "Le dernier jour de cours des alternants doit être après celui des autres étudiants. "
                "Laissez-le vide s'ils finissent en même temps.",
            )
    try:
        reglages.definir_dates_semestre(
            taches.RACINE / "data" / "config", groupe, body.debut, body.fin, _auteur(request)
        )
        if regler_alternants:
            reglages.definir_fin_alternants(
                taches.RACINE / "data" / "config", groupe, body.fin_alternants or None, _auteur(request)
            )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _calendriers_a_jour()
    return _periode(groupe)


@router.delete("/periode/{groupe}")
def revenir_aux_dates_d_origine(groupe: str, request: Request) -> dict:
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    reglages.definir_dates_semestre(taches.RACINE / "data" / "config", groupe, None, None, _auteur(request))
    reglages.definir_fin_alternants(taches.RACINE / "data" / "config", groupe, None, _auteur(request), oublier=True)
    _calendriers_a_jour()
    return _periode(groupe)


# ── Plafonds hebdomadaires du calcul ──────────────────────────────────


class PlafondsRequest(BaseModel):
    promo: int
    alternants: int
    enseignant: int


def _plafonds(groupe: str) -> dict:
    from cal_iut.ingestion import reglages
    from cal_iut.solver import plafonds as source

    motif = _semestre_verrouille(groupe)
    if motif and "en service" in motif:
        motif = (
            f"Le {taches.GROUPES[groupe]['libelle'].lower()} est déjà en service : ses plafonds ne se modifient "
            "plus, ils servent à contrôler son planning."
        )
    return {
        "semestre_group": groupe,
        "verrouille": motif,
        "plafonds": source.plafonds(groupe),
        "origine": dict(source.ORIGINE),
        "personnalise": bool(reglages.plafonds_hebdo(taches.RACINE / "data" / "config").get(groupe)),
        "mini": source.MINI,
        "maxi": source.MAXI,
    }


@router.get("/plafonds/{groupe}")
def plafonds_hebdomadaires(groupe: str) -> dict:
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    return _plafonds(groupe)


@router.put("/plafonds/{groupe}")
def regler_les_plafonds(groupe: str, body: PlafondsRequest, request: Request) -> dict:
    """Nombre maximal de créneaux de 1 h 30 par semaine pour un groupe
    d'étudiants, un groupe d'alternants, un enseignant. Vaut pour le calcul
    de ce semestre et pour les contrôles de son planning."""
    from cal_iut.ingestion import reglages
    from cal_iut.solver import plafonds as source

    _refuser_si_source_verrouillee(groupe)
    try:
        voulus = source.valider(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ecart = {c: v for c, v in voulus.items() if v != source.ORIGINE[c]}
    reglages.definir_plafonds_hebdo(taches.RACINE / "data" / "config", groupe, ecart, _auteur(request))
    return _plafonds(groupe)


@router.delete("/plafonds/{groupe}")
def revenir_aux_plafonds_d_origine(groupe: str, request: Request) -> dict:
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    reglages.definir_plafonds_hebdo(taches.RACINE / "data" / "config", groupe, {}, _auteur(request))
    return _plafonds(groupe)


class CoursHorsMaquetteRequest(BaseModel):
    code: str
    nom: str
    semestre: str
    parcours: str
    teacher_code: str
    teacher_nom: str = ""
    teacher_prenom: str = ""
    cm: int = 0
    td: int = 0
    tp: int = 0


def _parcours_par_semestre(groupe: str) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    """Par semestre du groupe, les promotions possibles ; par promotion, le
    nombre de groupes de TD et de TP."""
    from cal_iut.ingestion.config_loader import load_groups

    tailles: dict[str, dict[str, int]] = {}
    for g in load_groups(taches.RACINE / "data" / "config"):
        t = tailles.setdefault(g.parcours, {"td": 0, "tp": 0})
        if g.kind in t:
            t[g.kind] += 1
    possibles = {
        s: sorted(p for p in tailles if p.startswith(f"BUT{(int(s[1:]) + 1) // 2}"))
        for s in taches.GROUPES[groupe]["semestres"]
    }
    return possibles, tailles


def _cours_hors_maquette(groupe: str) -> dict:
    from cal_iut.ingestion import reglages

    config = taches.RACINE / "data" / "config"
    semestres = set(taches.GROUPES[groupe]["semestres"])
    possibles, _ = _parcours_par_semestre(groupe)
    enseignants: dict[str, dict] = {}
    for s in _seances_du_groupe(groupe):
        for e in s.teachers:
            enseignants.setdefault(e.code, {
                "code": e.code, "nom": str(e.nom or ""), "prenom": str(e.prenom or ""), "libelle": _nom_enseignant(e),
            })
    saisis = {(c["code"], c["parcours"]): c for c in reglages.cours_hors_maquette(config)}
    import yaml

    chemin = config / "additional_courses.yaml"
    livres = (yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}).get("courses", []) if chemin.exists() else []
    cours = [
        {
            "id": None, "origine": "livree", "code": str(c.get("code_matiere")), "nom": str(c.get("nom_matiere") or ""),
            "semestre": str(c.get("semestre")), "parcours": str(c.get("parcours")),
            "teacher_code": str((c.get("lead") or {}).get("code") or ""),
            **{t: int((c.get("total") or {}).get(t) or 0) for t in ("cm", "td", "tp")},
        }
        for c in livres if str(c.get("semestre")) in semestres
    ] + [
        {
            "id": c["id"], "origine": "ajoutee", "code": c["code"], "nom": c.get("nom") or "",
            "semestre": c["semestre"], "parcours": c["parcours"], "teacher_code": c["teacher_code"],
            **{t: int(c.get(t) or 0) for t in ("cm", "td", "tp")},
        }
        for c in saisis.values() if c["semestre"] in semestres
    ]
    motif = _semestre_verrouille(groupe)
    if motif and "en service" in motif:
        motif = (
            f"Le {taches.GROUPES[groupe]['libelle'].lower()} est déjà en service : on n'y ajoute plus de module "
            "depuis cet écran, ses séances changeraient sans nouveau calcul. Pour une séance ponctuelle, utilisez "
            "« Nouvel évènement » dans la vue d'une promotion."
        )
    return {
        "semestre_group": groupe,
        "verrouille": motif,
        "semestres": possibles,
        "enseignants": sorted(enseignants.values(), key=lambda e: e["libelle"]),
        "cours": sorted(cours, key=lambda c: (c["semestre"], c["code"])),
        "seances_maxi": reglages.SEANCES_MAXI,
    }


@router.get("/cours-hors-maquette/{groupe}")
def cours_hors_maquette(groupe: str) -> dict:
    if groupe not in taches.GROUPES:
        raise HTTPException(422, f"Groupe de semestres inconnu : {groupe!r}")
    return _cours_hors_maquette(groupe)


@router.post("/cours-hors-maquette/{groupe}", status_code=201)
def ajouter_un_cours_hors_maquette(groupe: str, body: CoursHorsMaquetteRequest, request: Request) -> dict:
    """Un module absent de la maquette officielle (intervention, atelier) :
    il est placé par le calcul comme les autres, avec un seul enseignant."""
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    possibles, tailles = _parcours_par_semestre(groupe)
    if body.parcours not in possibles.get(body.semestre, []):
        raise HTTPException(422, "Choisissez un semestre et une promotion de ce semestre.")
    code = body.code.strip().upper()
    if any(s.course_code == code and s.parcours == body.parcours for s in _seances_du_groupe(groupe)):
        raise HTTPException(422, f"Le module {code} existe déjà pour cette promotion.")
    try:
        reglages.ajouter_cours_hors_maquette(
            taches.RACINE / "data" / "config",
            {**body.model_dump(), "groupes_td": tailles[body.parcours]["td"], "groupes_tp": tailles[body.parcours]["tp"]},
            _auteur(request),
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _regles_changees()
    return _cours_hors_maquette(groupe)


@router.delete("/cours-hors-maquette/{groupe}/{identifiant}")
def retirer_un_cours_hors_maquette(groupe: str, identifiant: str) -> dict:
    from cal_iut.ingestion import reglages

    _refuser_si_source_verrouillee(groupe)
    if not reglages.retirer(taches.RACINE / "data" / "config", "cours_hors_maquette", identifiant, livree=False):
        raise HTTPException(404, "Module introuvable.")
    _regles_changees()
    return _cours_hors_maquette(groupe)


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
