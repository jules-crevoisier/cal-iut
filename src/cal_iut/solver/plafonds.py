"""Plafonds hebdomadaires du calcul, par groupe de semestres.

Trois plafonds, en créneaux de 1 h 30 par semaine : celui d'un groupe
d'étudiants en formation initiale, celui d'un groupe d'alternants, celui d'un
enseignant. Ils se règlent sur l'écran « Nouveau semestre » (cf.
`ingestion/reglages.py`) ; sans réglage, ce sont les valeurs d'origine.

SOURCE UNIQUE pour le solveur, la complétion, la régénération d'une semaine
et les contrôles du tableau de bord : une règle vérifiée à une valeur et
appliquée à une autre n'est pas une règle (cf. `decomposed.FI_WEEKLY_CAP_SLOTS`).
Par groupe de semestres, pour qu'un plafond choisi pour le prochain semestre
ne change rien aux verdicts du semestre en service.
"""

from __future__ import annotations

from pathlib import Path

_CONFIG = Path(__file__).resolve().parents[3] / "data" / "config"

# Mêmes valeurs que `decomposed.FI_WEEKLY_CAP_SLOTS`, `FC_WEEKLY_CAP_SLOTS` et
# que le plafond enseignant de `solve_decomposed` (26 créneaux = 39 h).
ORIGINE = {"promo": 23, "alternants": 23, "enseignant": 26}
MINI, MAXI = 12, 30  # 30 créneaux : une semaine entière


def valider(valeurs: dict) -> dict[str, int]:
    """Les plafonds saisis, bornés. `ValueError` avec un message à afficher."""
    libelles = {"promo": "des étudiants", "alternants": "des alternants", "enseignant": "d'un enseignant"}
    propres: dict[str, int] = {}
    for cle, libelle in libelles.items():
        if cle not in valeurs or valeurs[cle] is None:
            continue
        valeur = valeurs[cle]
        if isinstance(valeur, bool) or not isinstance(valeur, int) or not MINI <= valeur <= MAXI:
            raise ValueError(f"Le plafond {libelle} doit être un nombre entier de créneaux entre {MINI} et {MAXI}.")
        propres[cle] = valeur
    return propres


def plafonds(groupe: str | None, config_dir: Path | None = None) -> dict[str, int]:
    """Les plafonds en vigueur pour ce groupe (« odd », « even »)."""
    sortie = dict(ORIGINE)
    if not groupe:
        return sortie
    try:
        from cal_iut.ingestion import reglages

        sortie.update(valider(reglages.plafonds_hebdo(config_dir or _CONFIG).get(str(groupe).lower(), {})))
    except Exception:  # noqa: BLE001 — un réglage illisible ne doit pas empêcher de calculer
        return dict(ORIGINE)
    return sortie


def plafonds_du_semestre(semestre: str | None, config_dir: Path | None = None) -> dict[str, int]:
    """Idem, à partir d'un semestre (« S2 »)."""
    if not semestre:
        return dict(ORIGINE)
    from cal_iut.calendar.academic import groupe_du_semestre

    return plafonds(groupe_du_semestre(semestre), config_dir)
