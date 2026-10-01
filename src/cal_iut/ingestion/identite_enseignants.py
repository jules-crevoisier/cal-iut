"""Identité d'un enseignant : prénom, nom, type, téléphone (01/10/2026).

Demande de Kyllian Bresson (responsable), onglet « Enseignants & vacataires »
de Référence : prénom, nom, diminutif, code Celcat, mail, téléphone, et la
distinction Enseignant / Vacataire — « stockées dans la structure de données
existante [...] ne PAS créer une deuxième source de données indépendante ».

Ce module ne STOCKE rien. Il dit comment lire et écrire ces champs dans la
structure qui existe déjà :

- la liste des enseignants reste celle de `teacherLabels` (feuille des
  contraintes, maquette, `enseignants_supplementaires.yaml`, intervenants
  créés dans l'appli : `ingestion/enseignants.py`) ;
- le diminutif EST le code (`KBR`) : l'identifiant de partout, jamais
  modifiable ;
- prénom et nom sont DÉRIVÉS du nom complet que l'appli affiche déjà
  (`separer_nom`) ; une correction est une surcharge de
  `data/state/references.json` (`surcharges_reference`, champs `prenom` et
  `nom_famille`), comme le mail ou le nom complet ;
- type et téléphone : aucune source existante ne les porte (ni la feuille
  CONTRAINTES ENSEIGNANTS, ni la maquette, ni `teacher_contacts.yaml` —
  vérifié le 01/10/2026). Ils ne vivent donc QUE dans `references.json`
  (champs `type` et `telephone`) ; sans saisie : « à préciser ».

Le nom affiché partout (annuaire, fiche, « Nouvelle séance », Liens &
partage, flux .ics, API v1) reste le nom complet — recomposé « Prénom NOM »
dès qu'un prénom ou un nom a été corrigé (`appliquer`).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

TYPES: tuple[str, ...] = ("enseignant", "vacataire")
LIBELLES_TYPE: dict[str, str] = {"enseignant": "Enseignant", "vacataire": "Vacataire"}

# Champs d'identité stockés dans `references.json` (famille `enseignants`).
# `nom` (déjà là, 29/09/2026) reste le nom COMPLET corrigé d'un bloc.
CHAMP_PRENOM = "prenom"
CHAMP_NOM_FAMILLE = "nom_famille"
CHAMP_TELEPHONE = "telephone"
CHAMP_TYPE = "type"


# ── Prénom / nom ────────────────────────────────────────────────────────


def _en_capitales(mot: str) -> bool:
    return any(c.isalpha() for c in mot) and mot == mot.upper() and mot != mot.lower()


def _casse_prenom(mot: str) -> str:
    """« KYLLIAN » -> « Kyllian », « anne-laure » -> « Anne-Laure ». Un mot
    déjà en casse mixte (« McKenzie ») est gardé tel quel."""
    if mot != mot.upper() and mot != mot.lower():
        return mot
    return re.sub(r"(^|[-'’])(\w)", lambda m: m.group(1) + m.group(2).upper(), mot.lower())


def separer_nom(complet: str | None, code: str | None = None) -> tuple[str, str]:
    """`(prénom, NOM)` tirés d'un nom complet — MÊME règle que le frontend
    (`frontend/src/utils/nomEnseignant.ts::nomCourt`) :

    - si certains mots sont entièrement en capitales et d'autres non, les
      capitales sont le nom (« Thomas CASTELLENGO », « Barthélémy TOMASINA »,
      « Jean-Marc DE LA TOUR ») ;
    - sinon (tout en capitales « KYLLIAN BRESSON », ou casse normale
      « Anne-Laure Perrone », « Alexia Petit-Halajko »), le premier mot est le
      prénom et le reste le nom.

    Le prénom est remis en casse normale (« Kyllian »), le nom en capitales
    (« BRESSON ») : la convention « Prénom NOM ». Un nom complet vide, ou
    qui n'est que le code (`code`), rend `("", "")` : inconnu, pas « KBR »."""
    mots = " ".join(str(complet or "").split()).split(" ")
    mots = [m for m in mots if m]
    if not mots or (code and " ".join(mots).upper() == str(code).strip().upper()):
        return "", ""
    if len(mots) == 1:
        return "", mots[0].upper()
    capitales = [m for m in mots if _en_capitales(m)]
    if capitales and len(capitales) < len(mots):
        prenoms = [m for m in mots if not _en_capitales(m)]
        noms = capitales
    else:
        prenoms, noms = mots[:1], mots[1:]
    return " ".join(_casse_prenom(m) for m in prenoms), " ".join(noms).upper()


def recomposer(prenom: str, nom: str) -> str:
    """« Prénom NOM » (sans espace en trop si l'un manque)."""
    return " ".join(x for x in (str(prenom or "").strip(), str(nom or "").strip()) if x)


def normaliser_prenom(brut: str) -> str:
    """Espaces réduits ; « JEAN » / « jean » -> « Jean ». `ValueError` si vide."""
    texte = " ".join(str(brut or "").split())
    if not texte or not any(c.isalpha() for c in texte):
        raise ValueError("Le prénom est vide.")
    return " ".join(_casse_prenom(m) for m in texte.split(" "))


def normaliser_nom_famille(brut: str) -> str:
    """Espaces réduits, en capitales (« Petit-Halajko » -> « PETIT-HALAJKO »)."""
    texte = " ".join(str(brut or "").split())
    if not texte or not any(c.isalpha() for c in texte):
        raise ValueError("Le nom est vide.")
    return texte.upper()


# ── Type ────────────────────────────────────────────────────────────────


def normaliser_type(brut: str) -> str:
    """`enseignant` ou `vacataire` (casse et accents indifférents), ou `ValueError`."""
    texte = unicodedata.normalize("NFD", str(brut or "").strip().lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    if texte in TYPES:
        return texte
    raise ValueError("Type inconnu : choisissez « Enseignant » ou « Vacataire ».")


# ── Téléphone ───────────────────────────────────────────────────────────

# Formats acceptés (01/10/2026) :
# - français : 10 chiffres commençant par 0 (« 06 12 34 56 78 »,
#   « 06.12.34.56.78 », « 0612345678 »), ou +33 / 0033 suivi de 9 chiffres
#   (« +33 6 12 34 56 78 », « +33 (0)6 12 34 56 78 ») ;
# - international : « + » ou « 00 », indicatif, 8 à 15 chiffres en tout
#   (norme E.164 : « +44 20 7946 0958 », « +262 692 12 34 56 »).
# Stocké au format E.164 (« +33612345678 ») : une seule écriture par numéro,
# quelle que soit la saisie. Affiché « 06 12 34 56 78 » (`formater_telephone`).

_RE_SEPARATEURS = re.compile(r"[\s.\-/]+")


def normaliser_telephone(brut: str) -> str:
    """Numéro au format E.164 (« +33612345678 »), ou `ValueError` lisible."""
    texte = str(brut or "").strip()
    texte = texte.removeprefix("tel:").strip()
    if not texte:
        raise ValueError("Le numéro de téléphone est vide.")
    # « +33 (0)6… » : le (0) français se retire.
    texte = re.sub(r"\(\s*0\s*\)", "", texte)
    texte = _RE_SEPARATEURS.sub("", texte).replace("(", "").replace(")", "")
    erreur = ValueError(
        f"« {str(brut).strip()} » n'est pas un numéro de téléphone valide "
        "(formes attendues : 06 12 34 56 78 ou +33 6 12 34 56 78)."
    )
    if texte.startswith("00"):
        texte = "+" + texte[2:]
    if texte.startswith("+"):
        chiffres = texte[1:]
        if not chiffres.isdigit() or chiffres.startswith("0"):
            raise erreur
        if chiffres.startswith("33"):
            national = chiffres[2:]
            if len(national) != 9 or national.startswith("0"):
                raise erreur
            return "+33" + national
        if not 8 <= len(chiffres) <= 15:
            raise erreur
        return "+" + chiffres
    if texte.isdigit() and len(texte) == 10 and texte.startswith("0") and texte[1] != "0":
        return "+33" + texte[1:]
    raise erreur


def formater_telephone(e164: str | None) -> str:
    """« +33612345678 » -> « 06 12 34 56 78 » ; un numéro étranger reste en
    E.164 (« +442079460958 »), sans deviner son découpage."""
    texte = str(e164 or "").strip()
    if texte.startswith("+33") and len(texte) == 12 and texte[3:].isdigit():
        national = "0" + texte[3:]
        return " ".join(national[i : i + 2] for i in range(0, 10, 2))
    return texte


# ── Lecture : la surcouche appliquée aux noms existants ─────────────────


def surcharges_identite() -> dict[str, dict[str, str]]:
    """`{CODE: {champ: valeur}}` pour prénom, nom, type et téléphone saisis
    dans l'appli. Ne lève jamais (lecture, cf. `surcharges_reference`)."""
    from cal_iut.ingestion import surcharges_reference

    sortie: dict[str, dict[str, str]] = {}
    for champ in (CHAMP_PRENOM, CHAMP_NOM_FAMILLE, CHAMP_TYPE, CHAMP_TELEPHONE):
        for code, valeur in surcharges_reference.valeurs("enseignants", champ).items():
            sortie.setdefault(code.strip().upper(), {})[champ] = valeur
    return sortie


def identite(code: str, nom_complet: str, surcharges: dict[str, str] | None = None) -> dict[str, Any]:
    """Prénom, nom, nom complet affiché et type d'UN enseignant.

    `nom_complet` : le nom que l'appli affiche AVANT toute correction de
    prénom ou de nom (fichier, maquette, ou nom complet corrigé). Sans
    correction de prénom ni de nom, il reste le nom affiché tel quel —
    aucun écran ne change ; avec, le nom affiché devient « Prénom NOM »."""
    s = surcharges or {}
    prenom_base, nom_base = separer_nom(nom_complet, code)
    prenom = s.get(CHAMP_PRENOM) or prenom_base
    nom = s.get(CHAMP_NOM_FAMILLE) or nom_base
    corrige = bool(s.get(CHAMP_PRENOM) or s.get(CHAMP_NOM_FAMILLE))
    affiche = recomposer(prenom, nom) if corrige and recomposer(prenom, nom) else (nom_complet or code)
    type_ = s.get(CHAMP_TYPE)
    return {
        "prenom": prenom,
        "nom": nom,
        "nomComplet": affiche,
        "type": type_ if type_ in TYPES else None,
        "prenomFichier": prenom_base,
        "nomFichier": nom_base,
    }


def appliquer(libelles: dict[str, str]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """`(libellés recomposés, identités)` pour tout `libelles` (code -> nom
    complet affiché). Les codes sans correction gardent leur libellé."""
    surcharges = surcharges_identite()
    nouveaux: dict[str, str] = {}
    identites: dict[str, dict[str, Any]] = {}
    for code, nom in libelles.items():
        ident = identite(code, nom, surcharges.get(code.strip().upper()))
        nouveaux[code] = ident["nomComplet"]
        identites[code] = {"prenom": ident["prenom"], "nom": ident["nom"], "type": ident["type"]}
    return nouveaux, identites

