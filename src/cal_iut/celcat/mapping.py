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


def _code_renseigne(valeur: object) -> str | None:
    """Un code Celcat utilisable, ou rien.

    « 0 » dans le YAML signifie « pas encore de code » (ALE, BMA, FCI, TMI) :
    c'est truthy en Python, donc `if v` le garderait et le pilote irait
    chercher l'enseignant « 0 ».
    """
    if valeur is None:
        return None
    texte = str(valeur).strip()
    if not texte or texte == "0":
        return None
    return texte


def load_celcat_config(config_dir: Path) -> CelcatConfig:
    path = config_dir / "celcat.yaml"
    if not path.exists():
        return CelcatConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CelcatConfig(
        enseignants={
            str(k).upper(): code
            for k, v in (data.get("enseignants") or {}).items()
            if (code := _code_renseigne(v))
        },
        salles={str(k): str(v) for k, v in (data.get("salles") or {}).items() if v},
        types_seance=dict(data.get("types_seance") or {}),
        modules={str(k).upper(): str(v) for k, v in (data.get("modules") or {}).items() if v},
    )


def libelle_groupe_celcat(groupe: str) -> str:
    """Notre libellé (« Promo BUT1 », « TD AB ») → fragment Celcat.

    Convention relevée le 31/08/2026 : « BUT MMI S1 TD AB », « BUT MMI S1 CM ».
    Les groupes CM s'appellent « Promo … » chez nous, « CM » chez eux.
    """
    nom = groupe.strip()
    if nom.lower().startswith("promo"):
        return "CM"
    return nom


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
    # Notre nom de type (« TD », « TP », « CM ») : c'est par lui que le
    # pilote retrouve le LIBELLÉ de la catégorie d'événement Celcat, la
    # valeur numérique ci-dessus n'étant qu'un index de position hérité des
    # `.bat` (cf. `celcat/formulaire.py::CarteFormulaire.categorie`).
    type_seance_nom: str = ""
    groupe: str = ""      # libellé du groupe, pour choisir le bon onglet Celcat
    # Semestre (« S2 ») : indispensable pour reconstituer le nom Celcat du
    # groupe, « BUT MMI S2 TD AB » — le libellé seul (« TD AB ») ne le porte
    # pas, et il n'y a aucun moyen de le deviner depuis l'index de semaine.
    semestre: str = ""
    # Lundi ISO de la semaine visée. L'index solveur ne suffit PAS : le
    # sélecteur de semaines de Celcat s'identifie par ses dates, et le piège
    # classique est d'y envoyer `semaine + 1` (cf. docs/MCP.md). Une semaine
    # mal choisie déverse une promotion entière sur les mauvaises dates.
    lundi: str = ""
    # Repris tel quel pour l'affichage/le journal, jamais envoyé à Celcat.
    course_code: str = ""
    bloquants: list[str] = field(default_factory=list)

    @property
    def prete(self) -> bool:
        return not self.bloquants

    @property
    def nom_groupe_celcat(self) -> str:
        """« TD AB » + « S2 » -> « BUT MMI S2 TD AB ».

        Sans le suffixe d'année de cohorte : une recherche sans lui retrouve
        le groupe (vérifié le 31/08/2026), ce qui évite d'avoir à deviner
        laquelle des cohortes est concernée.
        """
        return f"BUT MMI {self.semestre} {self.groupe}".strip()

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
    semestre: str = "",
    lundi: str = "",
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

    type_nom = session_type.strip().upper()
    type_celcat = cfg.types_seance.get(type_nom)
    # L'index numérique (TD=4, TP=6) est un héritage des `.bat`. Le pilote
    # désigne la catégorie par son LIBELLÉ (`[CM]`, `[TD]`, `[TP]`), relevé
    # le 01/09/2026. Un CM n'a pas d'index et n'en a plus besoin.
    if not type_nom:
        bloquants.append("type de séance manquant")
    elif type_celcat is None and type_nom != "CM":
        bloquants.append(f"type de séance {session_type} sans code Celcat")

    if "," in groupe:
        bloquants.append(
            f"plusieurs groupes ({groupe}) : Celcat n'en ouvre qu'un à la fois"
        )
    groupe_celcat = libelle_groupe_celcat(groupe)

    # Les deux repères de navigation. Ils ne servent pas à remplir un champ
    # du formulaire, mais à ATTEINDRE le bon endroit avant de le remplir :
    # sans eux le pilote saisirait la bonne séance sur le mauvais groupe ou la
    # mauvaise semaine — une erreur invisible dans un journal de réussites.
    if not semestre.strip():
        bloquants.append("semestre inconnu : nom du groupe Celcat introuvable")
    if not lundi.strip():
        bloquants.append(f"date de la semaine {week} inconnue : semaine Celcat non repérable")

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
        type_seance_nom=type_nom,
        groupe=groupe_celcat,
        semestre=semestre.strip(),
        lundi=lundi.strip(),
        course_code=course_code,
        bloquants=bloquants,
    )


def _lundi_iso(state: object, semestre: str, week: int) -> str:
    """Le LUNDI civil d'une semaine solveur, pour un semestre donné.

    Même calcul que `api/main.py::_date_iso(state, semestre, week, 0)`,
    reproduit ici plutôt qu'importé : `mapping.py` est une couche basse,
    `api/main.py` en dépend déjà — l'importer en retour créerait un cycle.
    """
    from datetime import timedelta

    from cal_iut.calendar.academic import semester_week_offset

    calendar = getattr(state, "calendar", None)
    if not semestre or calendar is None:
        return ""
    index = semester_week_offset(calendar, semestre) + week
    if 0 <= index < len(calendar.teaching_mondays):
        return (calendar.teaching_mondays[index] + timedelta(days=0)).isoformat()
    return ""


def entrees_pour_state(state: object) -> dict[str, EntreeCelcat]:
    """Même construction que `api/main.py::_entrees_celcat`, indexée par
    `session_id` — pour que `nuit.py` retrouve l'EntreeCelcat d'une session
    en file sans reconstruire la traduction à la main."""
    cfg = load_celcat_config(state.config_dir)
    libelle_groupe = {g.id: g.label for g in state.groups}
    entrees: dict[str, EntreeCelcat] = {}
    for p in state.timetable:
        session = state.sessions_by_id.get(p.session_id)
        semestre = getattr(session, "semestre", "") or ""
        entrees[p.session_id] = entree_pour_placement(
            cfg,
            session_id=p.session_id,
            course_code=p.course_code,
            session_type=str(getattr(getattr(session, "session_type", None), "value", "")) if session else "",
            week=p.week, day=p.day, slot=p.slot,
            duration_slots=max(1, getattr(session, "duration_slots", 1) or 1) if session else 1,
            teacher_codes=list(p.teacher_codes or []),
            room_id=getattr(p, "room_id", None),
            groupe=", ".join(libelle_groupe.get(g, g) for g in (p.group_ids or [])),
            semestre=semestre,
            lundi=_lundi_iso(state, semestre, p.week) if semestre else "",
        )
    return entrees
