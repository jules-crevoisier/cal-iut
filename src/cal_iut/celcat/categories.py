"""Catégories d'événement Celcat — CM ne doit jamais retomber en [TP].

L'ancien autoclicker (clickclick/robot01.js) ne connaissait que TD=4 sinon TP.
Un CM (index null) était donc saisi en [TP]. Le chemin RPC utilise les
libellés `[CM]` / `[TD]` / `[TP]` ; ce module refuse toute charge CM qui
n'a pas la catégorie CM, et détecte les écarts Live ↔ maquette.
"""

from __future__ import annotations

from dataclasses import dataclass

# IDs numériques relevés sur URCA (canari FORMATION / lecture Live).
# Source : data/releves/celcat-rpc-canari.json — evCatName [CM] → 430.
#
# [TD] et [TP] ajoutés le 07/09/2026, relevés sur URCA_2026 par
# `scripts/auditer_categories_celcat.py` (catalogue udlResources complet).
# Tant qu'ils manquaient, le filet était ASYMÉTRIQUE : il refusait un CM mal
# catégorisé mais laissait passer un TD portant l'identifiant du CM — la
# forme exacte du symptôme signalé par David Annebicque (« les TD sont
# aléatoirement indiqués en TD ou en CM »). Ne pas confondre avec les
# variantes voisines du même catalogue, qui ont leurs propres identifiants
# et ne doivent jamais être choisies à la place : [CM Capacite] 429,
# [CM bénévole] 845, [TD bénévole] 846, [TP bénévole] 847, TD0 465.
CATEGORIE_IDS: dict[str, int] = {
    "CM": 430,
    "TD": 433,
    "TP": 435,
}

LIBELLES: dict[str, str] = {
    "CM": "[CM]",
    "TD": "[TD]",
    "TP": "[TP]",
}


class CategorieRefusee(ValueError):
    """Charge d'écriture incompatible avec le type de séance cal-iut."""


def libelle_categorie(type_seance_nom: str) -> str:
    cle = (type_seance_nom or "").strip().upper()
    libelle = LIBELLES.get(cle)
    if not libelle:
        raise CategorieRefusee(
            f"type de séance « {type_seance_nom or '?'} » sans libellé Celcat "
            f"(attendu CM/TD/TP)"
        )
    return libelle


def categorie_live_coherente(type_seance_nom: str, ev_cat_name: str | None) -> bool:
    """True si la catégorie Live correspond au type maquette."""
    if not (type_seance_nom or "").strip():
        return False
    voulu = libelle_categorie(type_seance_nom)
    vu = (ev_cat_name or "").strip()
    return vu == voulu


def verifier_charge_categorie(charge: dict, *, type_seance_nom: str) -> None:
    """Refuse d'envoyer un CM/TD/TP sans catégorie, et un CM hors id [CM].

    Ne remplace pas `resoudre_ids` : c'est le filet avant `save`.
    Types hors CM/TD/TP : pas de filet (inconnu ≠ forcer [TP]).
    """
    cle = (type_seance_nom or "").strip().upper()
    if cle not in LIBELLES:
        return
    libelle = LIBELLES[cle]
    cat_id = charge.get("event_cat_id")
    if cat_id in (None, 0, "0", ""):
        raise CategorieRefusee(
            f"{cle} exige event_cat_id pour {libelle} — reçu vide "
            "(risque historique : CM saisi comme [TP])"
        )
    connu = CATEGORIE_IDS.get(cle)
    if connu is not None and int(cat_id) != connu:
        raise CategorieRefusee(
            f"{cle} attend event_cat_id={connu} ({libelle}), reçu {cat_id}"
        )


@dataclass(frozen=True)
class EcartCategorie:
    session_id: str
    course_code: str
    type_attendu: str
    event_id: int | None
    categorie_live: str
    motif: str


def type_depuis_identifiant(session_id: str) -> str:
    """Type porté par l'identifiant : « WR101-S1-TD-1-but1-td-ab » -> TD.

    Repli pour juger une séance que la maquette ne connaît pas (ou plus) —
    cas normal hors du serveur, où `state.timetable` est vide. Sans lui, un
    audit de catégories ne jugerait aucune séance et conclurait « aucun
    écart » : sur un sujet qui remonte dans OMEGA, un faux silence coûte
    plus cher qu'un doute affiché.

    Ne devine rien : seul un segment valant exactement CM, TD ou TP est
    retenu, sans quoi la réponse est vide et la séance reste non jugée.
    """
    for morceau in (session_id or "").upper().split("-"):
        if morceau in LIBELLES:
            return morceau
    return ""


def est_seance_cm(session_id: str, signature: str = "", session_type: str = "") -> bool:
    if (session_type or "").strip().upper() == "CM":
        return True
    if "-CM-" in (session_id or "").upper():
        return True
    return (signature or "").rstrip().endswith("|CM")


def inventaire_ecarts_categorie(
    *,
    journal: dict[str, dict],
    live_par_event_id: dict[int, object],
    type_par_session: dict[str, str],
) -> list[EcartCategorie]:
    """Compare type maquette / journal aux catégories Live (hors write)."""
    ecarts: list[EcartCategorie] = []
    for session_id, row in journal.items():
        if not isinstance(row, dict):
            continue
        sig = str(row.get("signature") or "")
        type_attendu = (type_par_session.get(session_id) or "").strip().upper()
        if not type_attendu and est_seance_cm(session_id, sig):
            type_attendu = "CM"
        if not type_attendu:
            continue
        brut_id = row.get("event_id")
        try:
            event_id = int(brut_id) if brut_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            event_id = None
        if event_id is None:
            continue
        ev = live_par_event_id.get(event_id)
        if ev is None:
            continue
        cat = str(getattr(ev, "categorie", None) or "").strip()
        if categorie_live_coherente(type_attendu, cat):
            continue
        code = ""
        if "|" in sig:
            # signature : …|module|type_idx|groupe — course_code vient surtout de l'id
            code = session_id.split("-")[0] if "-" in session_id else session_id
        ecarts.append(
            EcartCategorie(
                session_id=session_id,
                course_code=code,
                type_attendu=type_attendu,
                event_id=event_id,
                categorie_live=cat or "?",
                motif=(
                    f"{type_attendu} attendu {libelle_categorie(type_attendu)}, "
                    f"Live a {cat or '?'}"
                ),
            )
        )
    return ecarts
