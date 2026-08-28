"""Traduction d'un placement cal-iut vers une entrée Celcat.

Celcat est l'outil officiel de l'URCA (emplois du temps ET paie des
enseignants) et n'expose aucune API : la saisie se fait par automatisation
du navigateur (cf. `driver.py`). Ce module ne fait QUE la traduction de
données — il ne parle à rien, ne clique nulle part, et se teste donc
entièrement hors ligne.

Principe directeur : **rien n'est deviné**. Un code enseignant, un code
module ou un type de séance absent de `data/config/celcat.yaml` produit une
entrée marquée BLOQUÉE avec le motif exact, jamais une valeur inventée ni
une ligne silencieusement ignorée. Celcat sert aussi à payer les
enseignants : une séance fausse ou manquante n'y est pas un détail
d'affichage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Créneaux de l'IUT, identiques à `export/formatter.py::SLOT_TIMES` — Celcat
# attend des heures réelles ("08:00"), pas nos index de créneau.
SLOT_TIMES: list[tuple[str, str]] = [
    ("08:00", "09:30"),
    ("09:30", "11:00"),
    ("11:00", "12:30"),
    ("14:00", "15:30"),
    ("15:30", "17:00"),
    ("17:00", "18:30"),
]


@dataclass
class CelcatConfig:
    enseignants: dict[str, str] = field(default_factory=dict)
    salles: dict[str, str] = field(default_factory=dict)
    types_seance: dict[str, int | None] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)


def load_celcat_config(config_dir: Path) -> CelcatConfig:
    path = config_dir / "celcat.yaml"
    if not path.exists():
        return CelcatConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CelcatConfig(
        enseignants={str(k).upper(): str(v) for k, v in (data.get("enseignants") or {}).items() if v},
        salles={str(k): str(v) for k, v in (data.get("salles") or {}).items() if v},
        types_seance=dict(data.get("types_seance") or {}),
        modules={str(k).upper(): str(v) for k, v in (data.get("modules") or {}).items() if v},
    )


@dataclass
class EntreeCelcat:
    """Une séance prête (ou non) pour Celcat.

    `bloquants` vide = saisissable. Sinon, chaque motif dit précisément ce
    qui manque, pour que l'écran puisse l'afficher au lieu de faire échouer
    la saisie à mi-parcours devant un formulaire ouvert.
    """

    session_id: str
    semaine: int          # index solveur, tel qu'utilisé partout dans l'app
    jour: int             # 1 = lundi (convention Celcat, cf. scripts `.bat`)
    heure_debut: str
    heure_fin: str
    code_enseignant: str | None
    salle: str | None
    code_module: str | None
    type_seance: int | None
    groupe: str           # libellé du groupe, pour choisir le bon onglet Celcat
    # Repris tel quel pour l'affichage/le journal, jamais envoyé à Celcat.
    course_code: str = ""
    bloquants: list[str] = field(default_factory=list)

    @property
    def prete(self) -> bool:
        return not self.bloquants

    def signature(self) -> str:
        """Ce qui définit l'entrée CÔTÉ CELCAT. Sert à repérer qu'une séance
        déjà poussée a changé depuis (cf. `sync.py`) : deux placements de
        même signature n'ont rien à re-saisir, une signature différente doit
        être corrigée dans Celcat. Volontairement SANS les libellés
        d'affichage (`course_code`), qui peuvent changer sans qu'il y ait
        quoi que ce soit à modifier là-bas."""
        return "|".join(
            str(x) for x in (
                self.semaine, self.jour, self.heure_debut, self.heure_fin,
                self.code_enseignant, self.salle, self.code_module,
                self.type_seance, self.groupe,
            )
        )


def _salle_celcat(cfg: CelcatConfig, room_id: str | None) -> tuple[str | None, str | None]:
    if not room_id:
        return None, "aucune salle affectée"
    salle = cfg.salles.get(room_id)
    if not salle:
        return None, f"salle « {room_id} » sans équivalent Celcat (cf. data/config/celcat.yaml)"
    return salle, None


def entree_pour_placement(
    cfg: CelcatConfig,
    *,
    session_id: str,
    course_code: str,
    session_type: str,
    week: int,
    day: int,
    slot: int,
    duration_slots: int,
    teacher_codes: list[str],
    room_id: str | None,
    groupe: str,
) -> EntreeCelcat:
    """Traduit UN placement. `duration_slots` > 1 : l'heure de fin est celle
    du DERNIER créneau occupé — Celcat prend une plage, pas une répétition
    (l'ancien autoclicker, lui, émettait deux lignes consécutives pour un
    bloc de 3 h, ce qui créait deux séances au lieu d'une)."""
    bloquants: list[str] = []

    debut = SLOT_TIMES[slot][0] if 0 <= slot < len(SLOT_TIMES) else None
    dernier = slot + max(1, duration_slots) - 1
    fin = SLOT_TIMES[dernier][1] if 0 <= dernier < len(SLOT_TIMES) else None
    if debut is None or fin is None:
        bloquants.append(f"créneau hors plage (slot={slot}, durée={duration_slots})")

    # Un seul enseignant côté Celcat : le premier déclaré. Une séance à
    # plusieurs intervenants (duo) est signalée plutôt que tronquée en
    # silence — c'est à un humain de décider qui est saisi.
    code_ens: str | None = None
    if not teacher_codes:
        bloquants.append("aucun enseignant")
    else:
        trigramme = teacher_codes[0].upper()
        code_ens = cfg.enseignants.get(trigramme)
        if not code_ens:
            bloquants.append(f"enseignant {trigramme} sans code Celcat")
        if len(teacher_codes) > 1:
            bloquants.append(
                f"{len(teacher_codes)} enseignants ({', '.join(teacher_codes)}) : "
                "Celcat n'en accepte qu'un, à trancher à la main"
            )

    salle, motif_salle = _salle_celcat(cfg, room_id)
    if motif_salle:
        bloquants.append(motif_salle)

    code_module = cfg.modules.get(course_code.upper())
    if not code_module:
        bloquants.append(f"module {course_code} sans code Celcat")

    type_celcat = cfg.types_seance.get(session_type.upper())
    if type_celcat is None:
        bloquants.append(f"type de séance {session_type} sans code Celcat")

    return EntreeCelcat(
        session_id=session_id,
        semaine=week,
        jour=day + 1,  # 0 = lundi chez nous, 1 = lundi côté Celcat
        heure_debut=debut or "",
        heure_fin=fin or "",
        code_enseignant=code_ens,
        salle=salle,
        code_module=code_module,
        type_seance=type_celcat,
        groupe=groupe,
        course_code=course_code,
        bloquants=bloquants,
    )
