"""Carte du formulaire de création d'événement Celcat.

Les libellés vivent dans `data/config/celcat_formulaire.yaml`, relevés à
l'écran (URCA_2026 pour Détails, URCA_2025 pour Ressources, 01/09/2026).
Le pilote refuse d'écrire tant que `manques()` n'est pas vide.

CE QUI EST SÛR par ailleurs : les cinq champs de ressource se remplissent
par GLISSER-DÉPOSER depuis la liste de gauche — catégorie, département,
enseignant, salle, matière. C'est l'apport de l'ancien autoclicker
(`clickclick/robot01.js`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from cal_iut.celcat.navigateur import (
    TYPE_CATEGORIES_EVENEMENT,
    TYPE_DEPARTEMENTS,
    TYPE_MATIERES,
    TYPE_PERSONNEL,
    TYPE_SALLES,
)

# Ressource de gauche où prendre la valeur de chaque champ, et onglet où le
# champ se trouve. Relevé de l'ordre des icônes de l'ancien autoclicker, qui
# correspond exactement à `navigateur.ICONES` : matières < salles <
# personnel < équipes < groupes < départements < catégories.
RESSOURCE_DU_CHAMP: dict[str, tuple[int, str]] = {
    "categorie": (TYPE_CATEGORIES_EVENEMENT, "details"),
    "departement": (TYPE_DEPARTEMENTS, "details"),
    "enseignant": (TYPE_PERSONNEL, "ressources"),
    "salle": (TYPE_SALLES, "ressources"),
    "matiere": (TYPE_MATIERES, "ressources"),
}

# Ce qu'il faut avoir relevé pour qu'une saisie soit possible. Un seul
# manque suffit à refuser : un formulaire à moitié rempli puis enregistré
# produit une séance fausse, pas une séance incomplète.
#
# `heure` est UN champ, pas deux. L'inspecteur relevé le 01/09/2026 affiche
# « Heure: » suivi d'un seul champ portant l'intervalle entier — « 7:00
# AM-11:59 PM ». Il n'y a pas de `heure_debut` / `heure_fin` séparés, et il
# n'y a pas non plus de bouton texte de validation : c'est l'icône
# `enregistrer` de la barre qui commet, et elle se repère à son image.
CHAMPS_REQUIS = ("jour", "heure")


class FormulaireNonReleve(RuntimeError):
    """La carte du formulaire n'est pas complète — le message dit quoi faire."""


@dataclass(frozen=True)
class CarteFormulaire:
    """Les repères TEXTE du formulaire, tels que relevés à l'écran.

    Uniquement des libellés affichés, jamais de coordonnées : les pixels de
    l'ancien autoclicker ne valaient que pour un écran de 2560×1440 à 75 %
    de zoom, sur macOS — c'est précisément ce qui l'a rendu inutilisable
    ailleurs.
    """

    onglet_details: str = ""
    onglet_ressources: str = ""
    jour: str = ""
    # Un seul champ, portant l'intervalle : « 7:00 AM-11:59 PM ».
    heure: str = ""
    # Facultatif : aucun bouton texte de validation n'a été vu à l'écran, la
    # barre d'icônes suffit. Le champ reste là pour le jour où une version de
    # Celcat en afficherait un.
    validation_horaire: str = ""
    # Libellé affiché à gauche de chaque champ de ressource, dans l'onglet
    # indiqué par `RESSOURCE_DU_CHAMP`.
    champs: dict[str, str] = field(default_factory=dict)
    # Libellé Celcat de la catégorie d'événement, par type de séance chez
    # nous : {"TD": "[TD]", "TP": "[TP]", "CM": "[CM]"}.
    #
    # Pourquoi ici et pas dans `celcat.yaml::types_seance` : là-bas, TD=4 et
    # TP=6 sont des INDEX DE POSITION dans un déroulant, hérités des `.bat`
    # d'origine. Un index de position ne se cherche pas par son texte, et
    # compter des lignes pour tomber sur la quatrième est précisément le
    # genre de clic à l'aveugle qui a créé un événement fantôme le
    # 01/09/2026. Les 38 catégories ayant été relevées, la désigner par son
    # LIBELLÉ est à la fois possible et sûr.
    categories: dict[str, str] = field(default_factory=dict)
    # Décalage VERTICAL, en pixels, entre un libellé et le champ qu'il
    # désigne : le champ est SOUS son libellé, pas à sa droite.
    #
    # C'est la correction la plus importante du relevé du 01/09/2026. On
    # avait supposé un décalage horizontal de 120 px, d'après les
    # coordonnées de l'ancien autoclicker. Mesuré à l'écran : « Jour: » est
    # en (952, 737) et sa valeur « Mon » en (956, 770) ; « Heure: » en
    # (1090, 737) et sa valeur en (1136, 770). Soit +33 px vers le BAS, à
    # x quasi constant. Avec l'ancienne hypothèse, viser à droite de
    # « Jour: » tombait sur (1072, 737) — c'est-à-dire sur le libellé
    # « Heure: » lui-même, à 18 px près. On aurait donc saisi l'heure dans
    # le champ du jour.
    decalage_champ_y: int = 32

    def manques(self) -> list[str]:
        """Ce qui reste à relever, nommé pour être affichable tel quel."""
        absents = [nom for nom in CHAMPS_REQUIS if not str(getattr(self, nom, "")).strip()]
        if not self.onglet_details.strip():
            absents.append("onglet_details")
        if not self.onglet_ressources.strip():
            absents.append("onglet_ressources")
        absents += [
            f"champs.{nom}" for nom in RESSOURCE_DU_CHAMP if not str(self.champs.get(nom, "")).strip()
        ]
        return absents

    def categorie(self, type_seance_nom: str) -> str:
        """Libellé Celcat de la catégorie, ou lève en disant lequel manque."""
        libelle = str(self.categories.get((type_seance_nom or "").upper(), "")).strip()
        if not libelle:
            raise FormulaireNonReleve(
                f"catégorie d'événement Celcat inconnue pour un {type_seance_nom or '?'} : "
                "renseignez `categories` dans data/config/celcat_formulaire.yaml "
                "(libellé exact, ex. « [TD] »). Rien n'a été écrit dans Celcat."
            )
        return libelle

    @property
    def confirmee(self) -> bool:
        return not self.manques()

    def exiger_complete(self) -> None:
        if self.confirmee:
            return
        raise FormulaireNonReleve(
            "Le formulaire de création Celcat n'a pas encore été relevé : "
            + ", ".join(self.manques())
            + ". Lancez une session supervisée avec "
            "`PilotePlaywright.relever_formulaire()` (base URCA_FORMATION), puis "
            "reportez les libellés dans data/config/celcat_formulaire.yaml. "
            "Rien n'a été écrit dans Celcat."
        )

    def libelle_champ(self, nom: str) -> str:
        libelle = str(self.champs.get(nom, "")).strip()
        if not libelle:
            raise FormulaireNonReleve(f"libellé du champ « {nom} » non relevé.")
        return libelle

    def onglet_du_champ(self, nom: str) -> str:
        _, onglet = RESSOURCE_DU_CHAMP[nom]
        return self.onglet_details if onglet == "details" else self.onglet_ressources

    def ressource_du_champ(self, nom: str) -> int:
        return RESSOURCE_DU_CHAMP[nom][0]


def charger_carte(config_dir: Path) -> CarteFormulaire:
    """Lit `celcat_formulaire.yaml`. Absent = carte vide, donc saisie refusée."""
    chemin = Path(config_dir) / "celcat_formulaire.yaml"
    if not chemin.exists():
        return CarteFormulaire()
    data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    champs = {str(k): str(v) for k, v in (data.get("champs") or {}).items() if v}
    categories = {
        str(k).upper(): str(v) for k, v in (data.get("categories") or {}).items() if v
    }
    return CarteFormulaire(
        onglet_details=str(data.get("onglet_details") or ""),
        onglet_ressources=str(data.get("onglet_ressources") or ""),
        jour=str(data.get("jour") or ""),
        heure=str(data.get("heure") or ""),
        validation_horaire=str(data.get("validation_horaire") or ""),
        champs=champs,
        categories=categories,
        decalage_champ_y=int(data.get("decalage_champ_y") or 32),
    )
