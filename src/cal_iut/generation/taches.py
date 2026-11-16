"""État d'une génération, sur disque.

Une génération dure de trente minutes à plusieurs heures. Les autres calculs
longs de l'application (`/solve/async`, `/regen/week`) vivent en mémoire dans
un thread du serveur : ils meurent à chaque redémarrage, et chaque push sur
`main` redéploie. Ici, tout l'état est dans un dossier du volume persistant
(`data/state/generations/<id>/`) et le calcul tourne dans un processus à
part (`generation/ouvrier.py`) :

- `etat.json` : paramètres, étape en cours, tentatives, résultat ;
- `battement` : fichier touché toutes les quinze secondes par l'ouvrier —
  c'est lui qui dit si le calcul est vivant (un numéro de processus ne
  prouve rien après un redémarrage du conteneur, où ils repartent de 1) ;
- `annuler` : sa présence demande l'arrêt ;
- `journal.log` : la sortie de l'ouvrier ;
- `sessions.json`, `meilleur.json`, `planning.json` : les séances à placer,
  le meilleur résultat du solveur, le résultat final.

Après un redémarrage, `reprendre_interrompues` relance l'ouvrier des
générations « en cours » qui ne battent plus : il reprend où il en était
(les tentatives déjà faites et le meilleur résultat sont gardés).

Ce module ne dépend ni de FastAPI ni du solveur : l'API et l'ouvrier
l'importent tous les deux.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
STATE_DIR = RACINE / "data" / "state"
GENERATIONS_DIR = STATE_DIR / "generations"

STATUTS_ACTIFS = ("en_attente", "en_cours")
STATUTS_FINIS = ("terminee", "echec", "annulee")

# Au-delà, l'ouvrier est tenu pour mort (il bat toutes les 15 s).
BATTEMENT_MAX_S = 90
PERIODE_BATTEMENT_S = 15
# Un calcul qui tombe à chaque reprise ne doit pas repartir indéfiniment.
REPRISES_MAX = 5
# Générations finies conservées (les plus récentes) ; les fichiers de travail
# d'une génération pèsent quelques Mo.
CONSERVEES = 10

ETAPES = (
    ("preparation", "Préparer les séances"),
    ("verification", "Vérifier les données"),
    ("calcul", "Calculer l'emploi du temps"),
    ("finition", "Attribuer les salles et compléter"),
    ("enregistrement", "Enregistrer le brouillon"),
)

GROUPES = {
    "odd": {"libelle": "Semestre impair", "semestres": ["S1", "S3", "S5"]},
    "even": {"libelle": "Semestre pair", "semestres": ["S2", "S4", "S6"]},
}

_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_verrou = threading.Lock()


class GenerationIntrouvable(KeyError):
    pass


class GenerationDejaEnCours(RuntimeError):
    def __init__(self, etat: dict) -> None:
        super().__init__(f"Une génération est déjà en cours ({etat['id']})")
        self.etat = etat


def coeurs_disponibles() -> int:
    return os.cpu_count() or 1


def parametres_par_defaut(groupe: str) -> dict:
    """Réglages de la recette, par groupe de semestres.

    Impair : ceux de `scripts/solve_until_ok.py` et de `docs/DATA.md` (24
    semaines pour laisser finir les alternants, formation initiale terminée
    en semaine 18, soit le 1er février). Pair : l'horizon vient du
    calendrier, sans date de fin anticipée pour la formation initiale.

    Un cœur est laissé au serveur web, qui continue de servir le planning en
    cours pendant le calcul.
    """
    if groupe not in GROUPES:
        raise ValueError(f"Groupe de semestres inconnu : {groupe!r}")
    commun = {
        "semestre_group": groupe,
        "tentatives": 6,
        "heures": 4.0,
        "spread_weight": 8,
        "num_workers": max(1, coeurs_disponibles() - 1),
        "arret_si_complet": True,
    }
    if groupe == "odd":
        return {**commun, "weeks": 24, "fi_max_week": 18}
    return {**commun, "weeks": None, "fi_max_week": None}


def valider_parametres(brut: dict) -> dict:
    """Paramètres complets et bornés, à partir d'une saisie partielle."""
    groupe = str(brut.get("semestre_group") or "")
    params = parametres_par_defaut(groupe)

    def _entier(cle: str, mini: int, maxi: int, *, optionnel: bool = False) -> None:
        if cle not in brut:
            return
        valeur = brut[cle]
        if valeur is None:
            if not optionnel:
                raise ValueError(f"« {cle} » est obligatoire")
            params[cle] = None
            return
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            raise ValueError(f"« {cle} » doit être un nombre entier")
        if not mini <= valeur <= maxi:
            raise ValueError(f"« {cle} » doit être compris entre {mini} et {maxi}")
        params[cle] = valeur

    _entier("tentatives", 1, 40)
    _entier("weeks", 4, 40, optionnel=True)
    _entier("fi_max_week", 1, 40, optionnel=True)
    _entier("spread_weight", 0, 100)
    _entier("num_workers", 1, max(1, coeurs_disponibles()))
    if "heures" in brut:
        heures = brut["heures"]
        if isinstance(heures, bool) or not isinstance(heures, int | float) or not 0.1 <= heures <= 24:
            raise ValueError("« heures » doit être compris entre 0,1 et 24")
        params["heures"] = float(heures)
    if "arret_si_complet" in brut:
        params["arret_si_complet"] = bool(brut["arret_si_complet"])
    return params


# ── Lecture et écriture ────────────────────────────────────────────────


def _maintenant() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dossier(generation_id: str) -> Path:
    if not _ID.match(generation_id or ""):
        raise GenerationIntrouvable(generation_id)
    chemin = GENERATIONS_DIR / generation_id
    if not (chemin / "etat.json").exists():
        raise GenerationIntrouvable(generation_id)
    return chemin


def lire_dossier(chemin: Path) -> dict:
    return json.loads((chemin / "etat.json").read_text(encoding="utf-8"))


def lire(generation_id: str) -> dict:
    return lire_dossier(dossier(generation_id))


def ecrire(chemin: Path, etat: dict) -> None:
    """Écriture atomique : un lecteur ne voit jamais un fichier à moitié écrit."""
    etat["maj_le"] = _maintenant()
    temporaire = chemin / "etat.json.tmp"
    temporaire.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporaire, chemin / "etat.json")


def lister() -> list[dict]:
    """Toutes les générations, la plus récente d'abord."""
    if not GENERATIONS_DIR.exists():
        return []
    etats = []
    for chemin in GENERATIONS_DIR.iterdir():
        if not _ID.match(chemin.name) or not (chemin / "etat.json").exists():
            continue
        try:
            etats.append(lire_dossier(chemin))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(etats, key=lambda e: e["id"], reverse=True)


def active() -> dict | None:
    return next((e for e in lister() if e.get("statut") in STATUTS_ACTIFS), None)


def est_vivante(etat: dict) -> bool:
    """L'ouvrier a-t-il battu récemment ?"""
    try:
        age = time.time() - (GENERATIONS_DIR / etat["id"] / "battement").stat().st_mtime
    except OSError:
        return False
    return age < BATTEMENT_MAX_S


def fin_du_journal(generation_id: str, lignes: int = 40) -> list[str]:
    try:
        texte = (dossier(generation_id) / "journal.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return texte.splitlines()[-lignes:]


# ── Cycle de vie ───────────────────────────────────────────────────────


def creer(parametres: dict, par: str) -> dict:
    """Crée la génération (sans la lancer). Une seule à la fois : le calcul
    occupe presque tous les processeurs."""
    params = valider_parametres(parametres)
    with _verrou:
        en_cours = active()
        if en_cours is not None:
            raise GenerationDejaEnCours(en_cours)
        maintenant = datetime.now()
        generation_id = f"{maintenant:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        chemin = GENERATIONS_DIR / generation_id
        chemin.mkdir(parents=True)
        etat = {
            "id": generation_id,
            "statut": "en_attente",
            "parametres": params,
            "cree_le": _maintenant(),
            "cree_par": par,
            "etapes": [{"cle": cle, "libelle": libelle, "statut": "a_faire"} for cle, libelle in ETAPES],
            "tentatives": [],
            "meilleur": None,
            "verification": None,
            "resultat": None,
            "run_id": None,
            "erreur": None,
            "reprises": 0,
        }
        ecrire(chemin, etat)
        _purger_anciennes()
        return etat


def _purger_anciennes() -> None:
    import shutil

    finies = [e for e in lister() if e.get("statut") in STATUTS_FINIS]
    for etat in finies[CONSERVEES:]:
        shutil.rmtree(GENERATIONS_DIR / etat["id"], ignore_errors=True)


def lancer(generation_id: str) -> int:
    """Démarre l'ouvrier dans un processus détaché ; rend son numéro."""
    chemin = dossier(generation_id)
    (chemin / "battement").touch()
    journal = (chemin / "journal.log").open("ab")
    try:
        processus = subprocess.Popen(
            [sys.executable, "-u", "-m", "cal_iut.generation.ouvrier", str(chemin)],
            cwd=RACINE,
            stdout=journal,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        journal.close()
    return processus.pid


def demander_annulation(generation_id: str) -> dict:
    """Demande l'arrêt. L'ouvrier s'arrête de lui-même en quelques secondes ;
    s'il ne tourne plus (redémarrage en cours de calcul), la génération est
    close ici."""
    chemin = dossier(generation_id)
    etat = lire_dossier(chemin)
    if etat["statut"] not in STATUTS_ACTIFS:
        return etat
    (chemin / "annuler").touch()
    if not est_vivante(etat):
        etat["statut"] = "annulee"
        etat["termine_le"] = _maintenant()
        _clore_etapes(etat, "annulee")
        ecrire(chemin, etat)
    return etat


def _clore_etapes(etat: dict, statut: str) -> None:
    for etape in etat["etapes"]:
        if etape["statut"] == "en_cours":
            etape["statut"] = statut


def arreter_groupe(pid: int) -> None:
    """Arrête un processus et ses enfants (l'ouvrier lance `cal-iut solve`
    dans son propre groupe)."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def reprendre_interrompues() -> list[str]:
    """Relance les générations « en cours » dont l'ouvrier ne bat plus
    (redémarrage du serveur pendant le calcul). Rend les identifiants
    relancés. Au-delà de `REPRISES_MAX`, la génération est mise en échec."""
    relancees: list[str] = []
    for etat in lister():
        if etat.get("statut") not in STATUTS_ACTIFS or est_vivante(etat):
            continue
        chemin = GENERATIONS_DIR / etat["id"]
        if (chemin / "annuler").exists():
            demander_annulation(etat["id"])
            continue
        if int(etat.get("reprises") or 0) >= REPRISES_MAX:
            etat["statut"] = "echec"
            etat["erreur"] = (
                f"Le calcul s'est interrompu {REPRISES_MAX} fois de suite. "
                "Le journal ci-dessous dit où."
            )
            etat["termine_le"] = _maintenant()
            _clore_etapes(etat, "echec")
            ecrire(chemin, etat)
            continue
        etat["reprises"] = int(etat.get("reprises") or 0) + 1
        ecrire(chemin, etat)
        lancer(etat["id"])
        relancees.append(etat["id"])
    return relancees


def surveiller_reprises(delai_s: float = BATTEMENT_MAX_S + 30) -> threading.Thread | None:
    """Au démarrage du serveur : s'il reste une génération « en cours »,
    attend qu'un ouvrier encore vivant ait eu le temps de battre, puis
    relance ceux qui ne le sont plus. Sans génération en cours, ne fait rien."""
    if active() is None:
        return None

    def _attendre() -> None:
        time.sleep(delai_s)
        try:
            reprendre_interrompues()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Reprise des générations interrompues en échec")

    fil = threading.Thread(target=_attendre, daemon=True, name="generations-reprise")
    fil.start()
    return fil
