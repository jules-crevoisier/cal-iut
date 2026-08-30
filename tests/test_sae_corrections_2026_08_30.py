"""Corrections locales des journées SAE.

Demande du 30/08/2026, après vérification de Kyllian Bresson auprès de Marc
Nino (MNI, WSA501C — SAE de BUT3-CREACOM-FC) :

  « Il faut bien lui réserver le jeudi 24 septembre, le vendredi 25 septembre
  et le mercredi 4 novembre. Car il n'est pas disponible le lundi 23, le
  mardi 24 et le mercredi 25 novembre. Donc les étudiants n'ont pas de séance
  de SAE sur cette période, il faut donc placer des cours classiques sur ces
  jours. »

`contraintes/09_dates_sae.json` est RÉGÉNÉRÉ par
`scripts/build_contraintes.py` depuis le CSV de l'établissement : le
modifier à la main serait effacé au premier rebuild. D'où ce fichier de
correction, fusionné par-dessus — même mécanique que
`evenements_supplementaires.yaml` et `course_corrections.yaml`.

Le sens de la correction compte autant que son contenu : une journée SAE
ajoutée SANCTUARISE la journée (aucun cours classique n'y sera placé), une
journée retirée la REND aux cours classiques. Se tromper de sens laisse soit
des étudiants sans cours, soit une SAE sans intervenant.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from cal_iut.ingestion.planning_loader import appliquer_corrections_sae, load_sae_corrections

ROOT = Path(__file__).resolve().parents[1]


def _ecrire(dossier: Path, contenu: object) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "sae_corrections.yaml").write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    return dossier


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------


def test_sans_fichier_aucune_correction(tmp_path) -> None:
    ajouts, retraits = load_sae_corrections(tmp_path)
    assert ajouts == {} and retraits == {}


def test_les_dates_sont_lues_par_module(tmp_path) -> None:
    _ecrire(tmp_path, {
        "corrections": [{
            "course_code": "WSA501C",
            "ajouter": ["2026-09-24", "2026-09-25"],
            "retirer": ["2026-11-23"],
            "motif": "x", "demande_par": "y", "le": "2026-08-30",
        }]
    })
    ajouts, retraits = load_sae_corrections(tmp_path)
    assert ajouts["WSA501C"] == {date(2026, 9, 24), date(2026, 9, 25)}
    assert retraits["WSA501C"] == {date(2026, 11, 23)}


def test_le_motif_est_obligatoire(tmp_path) -> None:
    """Une journée SAE déplacée sans justification est indétricotable dans
    six mois — même principe que `evenements_supplementaires.yaml`."""
    _ecrire(tmp_path, {"corrections": [{"course_code": "WSA501C", "ajouter": ["2026-09-24"]}]})
    with pytest.raises(ValueError, match="motif"):
        load_sae_corrections(tmp_path)


def test_une_date_illisible_est_refusee(tmp_path) -> None:
    """Ignorée en silence, elle donnerait une réservation qu'on croit faite."""
    _ecrire(tmp_path, {
        "corrections": [{"course_code": "WSA501C", "ajouter": ["24/09/2026"], "motif": "x",
                         "demande_par": "y", "le": "2026-08-30"}]
    })
    with pytest.raises(ValueError, match="date"):
        load_sae_corrections(tmp_path)


def test_une_meme_date_ajoutee_et_retiree_est_refusee(tmp_path) -> None:
    """Contradiction : le résultat dépendrait de l'ordre d'application."""
    _ecrire(tmp_path, {
        "corrections": [{"course_code": "WSA501C", "ajouter": ["2026-11-23"], "retirer": ["2026-11-23"],
                         "motif": "x", "demande_par": "y", "le": "2026-08-30"}]
    })
    with pytest.raises(ValueError, match="à la fois"):
        load_sae_corrections(tmp_path)


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------


class _Fenetre:
    def __init__(self, codes, dates):
        self.course_codes = list(codes)
        self.dates = list(dates)


def test_une_date_retiree_disparait_de_la_fenetre() -> None:
    fenetres = [_Fenetre(["WSA501C"], [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)])]
    resultat = appliquer_corrections_sae(fenetres, {}, {"WSA501C": {date(2026, 11, 23), date(2026, 11, 25)}})
    assert [d for f in resultat for d in f.dates] == [date(2026, 11, 24)]


def test_une_fenetre_entierement_retiree_disparait() -> None:
    """Sinon elle resterait comme une fenêtre vide, et le jour continuerait
    d'apparaître comme « journée SAE » à l'écran."""
    fenetres = [_Fenetre(["WSA501C"], [date(2026, 11, 23)])]
    assert appliquer_corrections_sae(fenetres, {}, {"WSA501C": {date(2026, 11, 23)}}) == []


def test_une_date_ajoutee_cree_une_fenetre() -> None:
    resultat = appliquer_corrections_sae([], {"WSA501C": {date(2026, 9, 24)}}, {})
    assert len(resultat) == 1
    assert resultat[0].course_codes == ["WSA501C"]
    assert resultat[0].dates == [date(2026, 9, 24)]


def test_une_correction_ne_touche_pas_les_autres_modules() -> None:
    fenetres = [
        _Fenetre(["WSA501C"], [date(2026, 11, 23)]),
        _Fenetre(["WSA501D"], [date(2026, 11, 23)]),
    ]
    resultat = appliquer_corrections_sae(fenetres, {}, {"WSA501C": {date(2026, 11, 23)}})
    assert len(resultat) == 1 and resultat[0].course_codes == ["WSA501D"]


def test_sans_correction_les_fenetres_sont_intactes() -> None:
    fenetres = [_Fenetre(["WSA501C"], [date(2026, 10, 12)])]
    assert appliquer_corrections_sae(fenetres, {}, {}) is fenetres


# --------------------------------------------------------------------------
# Le fichier réel du dépôt
# --------------------------------------------------------------------------


def test_les_corrections_de_marc_nino_sont_declarees() -> None:
    ajouts, retraits = load_sae_corrections(ROOT / "data" / "config")
    assert ajouts.get("WSA501C") == {date(2026, 9, 24), date(2026, 9, 25), date(2026, 11, 4)}
    assert retraits.get("WSA501C") == {date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)}


def test_les_journees_sae_finales_correspondent_a_ses_disponibilites() -> None:
    """Le contrôle qui compte : après correction, CHAQUE journée de SAE doit
    tomber un jour où Marc Nino est disponible. C'est le décalage entre ces
    deux listes qui a causé le problème."""
    from cal_iut.ingestion.constraints_loader import load_all_constraints
    from cal_iut.ingestion.planning_loader import load_mmi_planning_for_semestres

    bundle = load_mmi_planning_for_semestres(ROOT, ["S5"])
    journees = {d for f in bundle.sae_windows if "WSA501C" in f.course_codes for d in f.dates}
    mni = next(t for t in load_all_constraints(ROOT).teachers if t.teacher_code == "MNI")
    dispos = {date.fromisoformat(d) for d in mni.allowed_dates}
    assert journees <= dispos, f"journées SAE hors de ses disponibilités : {sorted(journees - dispos)}"
    assert journees == dispos, f"disponibilités inutilisées : {sorted(dispos - journees)}"
