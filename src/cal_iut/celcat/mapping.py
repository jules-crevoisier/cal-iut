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

import re
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
    # Onglet « Codes Celcat » (30/09/2026). Par famille (`cours`, `salles`,
    # `enseignants`) :
    # - `connus` : les codes CONNUS avant toute saisie dans l'appli —
    #   `celcat.yaml`, puis pour les cours la maquette
    #   (`celcat_modules_maquette.yaml`). Verrouillés à l'écran ;
    # - `origines` : d'où vient le code qui part (« fichier », « maquette »,
    #   « maquette (corrigé M→C) », « appli ») ;
    # - `sans_code` : les entités à ne PAS envoyer, voulu —
    #   `{clé: {"motif", "source": "fichier"|"appli", ...}}`.
    connus: dict[str, dict[str, str]] = field(default_factory=dict)
    origines: dict[str, dict[str, str]] = field(default_factory=dict)
    sans_code: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    # « Nouvel intervenant » (30/09/2026) : pour chaque trigramme de la
    # section `enseignants` de `celcat.yaml` — « 0 » compris —, le nom que
    # porte son commentaire (`AGR: "38321"  # Gram AMBROISE`). Seule trace,
    # dans l'appli, de personnes que Celcat connaît sans que le planning les
    # connaisse : c'est ce qui permet d'avertir qu'un code « libre » est en
    # fait celui de quelqu'un d'autre dans Celcat.
    noms_fichier_enseignants: dict[str, str] = field(default_factory=dict)
    # Règles d'envoi (01/10/2026, `celcat.yaml::regles_envoi`) : des séances
    # qui partent avec une catégorie, une remarque et un département imposés,
    # et un module choisi par la règle. Par COURS (« WR100BU », clé : notre
    # code cours) et par TYPE de séance (« PTUT »).
    regles_cours: dict[str, RegleEnvoi] = field(default_factory=dict)
    regles_types: dict[str, RegleEnvoi] = field(default_factory=dict)

    def regle_sans_module(self, cours: str) -> RegleEnvoi | None:
        """La règle de COURS qui envoie ce cours sans aucun module, s'il y en
        a une — c'est elle qui retire le cours des codes module."""
        regle = self.regles_cours.get(str(cours or "").strip().upper())
        return regle if regle is not None and regle.module == MODULE_AUCUN else None


class ConfigCelcatInvalide(ValueError):
    """`celcat.yaml` contradictoire : refusé au chargement, jamais deviné."""


# Département des envois ordinaires (relevé le 31/08/2026, `celcat.yaml`) :
# celui d'une règle qui n'en précise pas.
DEPARTEMENT_PAR_DEFAUT = "T_MMI T29"

# `module:` d'une règle d'envoi.
MODULE_AUCUN = "aucun"   # aucune matière, jamais cherchée (WR100BU)
MODULE_COURS = "cours"   # la matière du COURS si son code est connu, sinon aucune (PTUT)


@dataclass(frozen=True)
class RegleEnvoi:
    """Une règle d'envoi de `celcat.yaml::regles_envoi`.

    Deux demandes de Kyllian Bresson (01/10/2026) :
    - la visite de la BU (WR100BU, code inventé, absent de Celcat) remonte
      pour les interventions de Valérie Mariot : catégorie « TD0 »
      (pondération 0), remarque « WR100BU », AUCUN module ;
    - toute séance de TYPE « PTUT » remonte en catégorie « Projet »
      (pondération 0), remarque « PTUT », avec le module du COURS quand il
      est connu, sans module sinon — jamais un module « PTUT ».
    La salle, le groupe et l'enseignant restent ceux de la séance.

    Déclarative : le code ne connaît AUCUN cours ni type par son nom.
    """

    cle: str          # « WR100BU » (cours) ou « PTUT » (type)
    portee: str       # « cours » ou « type »
    module: str       # MODULE_AUCUN ou MODULE_COURS
    categorie: str
    departement: str
    remarque: str
    # Trigrammes dont les interventions partent. Vide = toutes.
    enseignants: tuple[str, ...] = ()
    motif: str = ""

    def accepte(self, teacher_codes: list[str] | tuple[str, ...]) -> bool:
        """Le PREMIER enseignant (celui que Celcat recevra) est-il visé ?"""
        if not self.enseignants:
            return True
        return bool(teacher_codes) and str(teacher_codes[0]).strip().upper() in self.enseignants

    def motif_refus(self) -> str:
        return (
            f"{self.cle} : seules les interventions de {', '.join(self.enseignants)} "
            "sont envoyées (règle d'envoi de celcat.yaml)"
        )

    def libelle(self, code_module: str | None) -> str:
        """Ce que le plan affiche à côté de l'action (« à créer — … »)."""
        if self.module == MODULE_AUCUN:
            return f"sans module (règle {self.cle})"
        if code_module:
            return f"module du cours (règle {self.cle})"
        return f"sans module — cours sans code Celcat (règle {self.cle})"


_CHAMPS_REGLE = {"enseignants", "module", "categorie", "remarque", "departement", "motif"}
_TYPES_SEANCE = {"CM", "TD", "TP", "PTUT"}


def _lire_regle(cle: str, table: str, valeur: object) -> RegleEnvoi:
    ou = f"celcat.yaml : règle d'envoi `regles_envoi.{table}.{cle}`"
    if not isinstance(valeur, dict):
        raise ConfigCelcatInvalide(f"{ou} doit être une table (module, categorie, remarque…).")
    inconnus = sorted(set(map(str, valeur)) - _CHAMPS_REGLE)
    if inconnus:
        raise ConfigCelcatInvalide(
            f"{ou}, champ(s) inconnu(s) : {', '.join(inconnus)} (attendus : {', '.join(sorted(_CHAMPS_REGLE))})."
        )
    module = str(valeur.get("module") or "").strip().lower()
    if module not in (MODULE_AUCUN, MODULE_COURS):
        raise ConfigCelcatInvalide(
            f"{ou} : `module` doit valoir « {MODULE_AUCUN} » (aucune matière) ou « {MODULE_COURS} » "
            "(la matière du cours si son code est connu) — à écrire explicitement."
        )
    categorie = " ".join(str(valeur.get("categorie") or "").split())
    if not categorie:
        raise ConfigCelcatInvalide(f"{ou} sans `categorie` (nom exact de la catégorie d'évènement Celcat).")
    departement = " ".join(str(valeur.get("departement") or DEPARTEMENT_PAR_DEFAUT).split())
    enseignants = valeur.get("enseignants") or []
    if isinstance(enseignants, str):
        enseignants = [enseignants]
    return RegleEnvoi(
        cle=cle,
        portee="cours" if table == "cours" else "type",
        module=module,
        categorie=categorie,
        departement=departement,
        remarque=" ".join(str(valeur.get("remarque") or cle).split()),
        enseignants=tuple(str(t).strip().upper() for t in enseignants if str(t).strip()),
        motif=" ".join(str(valeur.get("motif") or "").split()),
    )


def lire_regles_envoi(data: dict) -> tuple[dict[str, RegleEnvoi], dict[str, RegleEnvoi]]:
    """La section `regles_envoi` de `celcat.yaml`, validée : `(par cours,
    par type)`.

    REFUSE plutôt que d'interpréter : une règle mal écrite enverrait des
    séances avec une catégorie de paie choisie au hasard. Refusés :
    - un cours aussi dans `sans_code_voulu.cours` (« jamais envoyé » ET
      « envoyé par une règle » à la fois) ;
    - un cours `module: aucun` qui a un code dans `modules` ;
    - un type inconnu (attendus : CM, TD, TP, PTUT) ;
    - `module` absent ou autre que « aucun » / « cours », catégorie vide ;
    - un champ inconnu (faute de frappe : « categories »…).
    """
    brut = data.get("regles_envoi") or {}
    if not isinstance(brut, dict) or set(map(str, brut)) - {"cours", "types"}:
        raise ConfigCelcatInvalide(
            "celcat.yaml : `regles_envoi` attend deux tables, `cours:` et/ou `types:`."
        )
    voulus = {str(k).strip().upper() for k in ((data.get("sans_code_voulu") or {}).get("cours") or {})}
    modules = {str(k).strip().upper(): v for k, v in (data.get("modules") or {}).items() if v}
    par_cours: dict[str, RegleEnvoi] = {}
    par_type: dict[str, RegleEnvoi] = {}
    for portee, cible in (("cours", par_cours), ("types", par_type)):
        table = brut.get(portee) or {}
        if not isinstance(table, dict):
            raise ConfigCelcatInvalide(f"celcat.yaml : `regles_envoi.{portee}` doit être une table.")
        for cle_brute, valeur in table.items():
            cle = str(cle_brute).strip().upper()
            regle = _lire_regle(cle, portee, valeur)
            if portee == "cours":
                if cle in voulus:
                    raise ConfigCelcatInvalide(
                        f"celcat.yaml : {cle} est à la fois dans `sans_code_voulu.cours` (jamais envoyé) et dans "
                        "`regles_envoi.cours` (envoyé par une règle). Retirez-le de l'une des deux sections."
                    )
                if regle.module == MODULE_AUCUN and cle in modules:
                    raise ConfigCelcatInvalide(
                        f"celcat.yaml : {cle} a un code module dans `modules` ({modules[cle]}) alors que sa règle "
                        "d'envoi dit `module: aucun`. Retirez l'un des deux."
                    )
            elif cle not in _TYPES_SEANCE:
                raise ConfigCelcatInvalide(
                    f"celcat.yaml : `regles_envoi.types.{cle}` : type de séance inconnu "
                    f"(attendus : {', '.join(sorted(_TYPES_SEANCE))})."
                )
            cible[cle] = regle
    return par_cours, par_type


def regle_pour(
    cfg: CelcatConfig, course_code: str, session_type: str, teacher_codes: list[str] | tuple[str, ...]
) -> tuple[RegleEnvoi | None, str]:
    """La règle d'envoi d'une séance : `(règle appliquée, motif de refus)`.

    ORDRE DE PRIORITÉ : la règle du COURS d'abord ; elle décide seule pour
    ses séances (y compris le refus d'un autre enseignant). Sinon la règle
    du TYPE de séance. Une règle passe devant « sans code (voulu) » et devant
    les codes module ordinaires : c'est le sens de « appliquées
    systématiquement à toutes les séances PTUT » (Kyllian, 01/10/2026).
    """
    regle = cfg.regles_cours.get(str(course_code or "").strip().upper()) or cfg.regles_types.get(
        str(session_type or "").strip().upper()
    )
    if regle is None:
        return None, ""
    if not regle.accepte(list(teacher_codes or [])):
        return None, regle.motif_refus()
    return regle, ""


_RE_LIGNE_ENSEIGNANT = re.compile(r"""^\s+["']?([A-Za-z]{1,6})["']?\s*:\s*["']?([^"'#\s]*)["']?\s*(?:#\s*(.*))?$""")


def noms_commentes(texte: str) -> dict[str, str]:
    """`{TRIGRAMME: nom du commentaire}` de la section `enseignants:` d'un
    `celcat.yaml` (texte brut : PyYAML jette les commentaires). Une entrée
    sans commentaire rend le trigramme lui-même — elle existe, sans nom.
    Les précisions entre parenthèses (« (ajoutée le 22/09/2026 — …) ») ne
    font pas partie du nom."""
    noms: dict[str, str] = {}
    dans_section = False
    for ligne in texte.splitlines():
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        if not ligne[0].isspace():
            dans_section = ligne.split("#", 1)[0].strip() == "enseignants:"
            continue
        if not dans_section:
            continue
        m = _RE_LIGNE_ENSEIGNANT.match(ligne)
        if not m:
            continue
        code = m.group(1).upper()
        nom = re.sub(r"\s*\([^)]*\)", "", m.group(3) or "").strip()
        noms[code] = nom or code
    return noms


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
    """La table de correspondance, YAML d'abord, surcouche par-dessus.

    `celcat.yaml` vit dans l'image Docker : y ajouter une salle demandait un
    déploiement. Les correspondances ajoutées depuis l'écran vivent dans le
    volume partagé (`celcat/mappings.py`) et sont donc lues par le worker à
    son passage suivant, sans redémarrage.

    L'ordre est explicite : la surcouche a le dernier mot. Corriger depuis
    l'écran une entrée que le YAML a fausse doit marcher tout de suite — sans
    quoi on se retrouve à éditer deux endroits en se demandant lequel gagne.
    """
    from cal_iut.celcat import codes_maquette, mappings

    config_dir = Path(config_dir)
    path = config_dir / "celcat.yaml"
    data = {}
    texte = ""
    if path.exists():
        texte = path.read_text(encoding="utf-8")
        data = yaml.safe_load(texte) or {}

    enseignants = {
        str(k).upper(): code
        for k, v in (data.get("enseignants") or {}).items()
        if (code := _code_renseigne(v))
    }
    salles = {str(k): str(v) for k, v in (data.get("salles") or {}).items() if v}
    modules = {str(k).upper(): str(v) for k, v in (data.get("modules") or {}).items() if v}
    regles_cours, regles_types = lire_regles_envoi(data)
    # Cours envoyés SANS module par décision (`module: aucun`) : retirés de
    # tout ce qui pourrait leur donner un code module.
    regles = {c for c, r in regles_cours.items() if r.module == MODULE_AUCUN}
    origines: dict[str, dict[str, str]] = {
        "cours": {**dict.fromkeys(modules, "fichier"), **dict.fromkeys(regles, "regle")},
        "salles": dict.fromkeys(salles, "fichier"),
        "enseignants": dict.fromkeys(enseignants, "fichier"),
    }

    # « Sans code (voulu) » : le fichier d'abord, puis l'appli.
    sans_code: dict[str, dict[str, dict[str, str]]] = {"cours": {}, "salles": {}, "enseignants": {}}
    for famille, entrees in (data.get("sans_code_voulu") or {}).items():
        if famille not in sans_code or not isinstance(entrees, dict):
            continue
        for cle, motif in entrees.items():
            cle_propre = str(cle).strip() if famille == "salles" else str(cle).strip().upper()
            sans_code[famille][cle_propre] = {"motif": str(motif or "").strip(), "source": "fichier"}
    for famille_surcouche, entrees in mappings.sans_code_voulus().items():
        famille = _FAMILLE_ONGLET[famille_surcouche]
        for cle, entree in entrees.items():
            if famille == "cours" and cle in regles:
                # La règle du fichier a le dernier mot : un « sans code »
                # saisi dans l'appli avant elle ne l'annule pas en silence.
                continue
            sans_code[famille].setdefault(cle, {
                "motif": str(entree.get("motif") or ""), "source": "appli",
                "ajoute_le": str(entree.get("ajoute_le") or ""), "ajoute_par": str(entree.get("ajoute_par") or ""),
            })

    # Codes de la maquette (préenregistrés, `celcat/codes_maquette.py`) :
    # APRÈS le fichier, qui garde le dernier mot, et jamais pour un cours
    # « sans code (voulu) ».
    for cours, entree in codes_maquette.lire(config_dir).items():
        if cours not in modules and cours not in sans_code["cours"] and cours not in regles:
            modules[cours] = entree["code"]
            origines["cours"][cours] = entree["origine"]
    connus = {"cours": dict(modules), "salles": dict(salles), "enseignants": dict(enseignants)}

    # Saisies de l'appli, en dernier : les codes du plan, du worker et de la
    # file passent tous ici. Depuis le 30/09/2026 on ne saisit plus que ce
    # qui n'a pas de code connu ; une saisie plus ancienne sur un code connu
    # reste appliquée (rien ne casse) et l'écran la signale.
    for cle, valeur in mappings.table("enseignants").items():
        if code := _code_renseigne(valeur):
            enseignants[cle] = code
            origines["enseignants"][cle] = "appli"
    for cle, valeur in mappings.table("salles").items():
        salles[cle] = valeur
        origines["salles"][cle] = "appli"
    for cle, valeur in mappings.table("matieres").items():
        if cle.upper() in regles:
            # Envoyé SANS module par décision : un code saisi avant la règle
            # ne doit pas faire chercher une matière qui n'existe pas.
            continue
        modules[cle.upper()] = valeur
        origines["cours"][cle.upper()] = "appli"

    return CelcatConfig(
        enseignants=enseignants,
        salles=salles,
        types_seance=dict(data.get("types_seance") or {}),
        modules=modules,
        connus=connus,
        origines=origines,
        sans_code=sans_code,
        noms_fichier_enseignants={
            **{str(k).upper(): str(k).upper() for k in (data.get("enseignants") or {})},
            **noms_commentes(texte),
        },
        regles_cours=regles_cours,
        regles_types=regles_types,
    )


# Famille de la surcouche (`mappings.py`) -> famille de l'onglet.
_FAMILLE_ONGLET = {"matieres": "cours", "salles": "salles", "enseignants": "enseignants"}


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
    # « Sans code (voulu) » (30/09/2026) : la séance n'est PAS envoyée, et
    # ce n'est pas un blocage à corriger. Le motif dit pourquoi.
    non_envoyee: str = ""
    # Règle d'envoi (01/10/2026, `celcat.yaml::regles_envoi`) : sa clé
    # (« WR100BU », « PTUT »), ce que le plan en dit, et ce qu'elle impose
    # côté Celcat. Vide = séance ordinaire : catégorie déduite du type,
    # matière obligatoire. Sous une règle, `code_module` peut être vide —
    # c'est voulu (`sans_module`).
    regle: str = ""
    regle_libelle: str = ""      # « sans module (règle WR100BU) »
    categorie_celcat: str = ""   # libellé Celcat exact (« TD0 », « Projet »)
    departement: str = ""        # libellé Celcat exact (« T_MMI T29 »)
    remarque: str = ""           # onglet « Remarques et personnaliser »

    @property
    def notes_celcat(self) -> str:
        """Le champ `notes` de l'évènement Celcat — sa « Remarque ».

        D'ordinaire notre `session_id`, seul. Avec une remarque imposée par
        une règle : « WR100BU — WR100BU-S1-TD-1-but1-td-ab ». La remarque
        voulue vient EN TÊTE (c'est elle que l'équipe lit dans Celcat), et
        l'identifiant reste dans le même champ, derrière le dernier « — » :
        `session_id_depuis_notes` le retrouve dans les deux formes.
        """
        if self.remarque:
            return f"{self.remarque}{SEPARATEUR_REMARQUE}{self.session_id}"
        return self.session_id

    @property
    def sans_module(self) -> bool:
        """Part sans aucune matière, par décision d'une règle."""
        return bool(self.regle) and not self.code_module

    @property
    def prete(self) -> bool:
        return not self.bloquants and not self.non_envoyee

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
        base = "|".join(
            str(x) for x in (
                self.semaine, self.jour, self.heure_debut, self.heure_fin,
                self.code_enseignant, self.salle, self.code_module,
                self.type_seance, self.groupe,
            )
        )
        if not self.regle:
            # Inchangée pour toutes les séances ordinaires : une signature
            # qui bouge ferait re-saisir tout le journal.
            return base
        return f"{base}|regle:{self.categorie_celcat}|{self.departement}|{self.remarque}"


# Entre la remarque imposée et notre identifiant, dans `notes`.
SEPARATEUR_REMARQUE = " — "


def session_id_depuis_notes(notes: str) -> str:
    """Notre `session_id` dans le champ `notes` d'un évènement Celcat, quelle
    que soit sa forme : « WR101-S1-TD-1-but1-td-ab » (séance ordinaire) ou
    « WR100BU — WR100BU-S1-TD-1-but1-td-ab » (remarque imposée par une règle
    d'envoi). Un identifiant ne contient jamais « — »."""
    return str(notes or "").rsplit(SEPARATEUR_REMARQUE, 1)[-1].strip()


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
    ens_voulu = ""
    if not teacher_codes:
        bloquants.append("aucun enseignant")
    else:
        trigramme = teacher_codes[0].upper()
        code_ens = cfg.enseignants.get(trigramme)
        voulu_ens = (cfg.sans_code.get("enseignants") or {}).get(trigramme)
        if not code_ens and voulu_ens:
            ens_voulu = f"enseignant {trigramme} sans code Celcat, voulu : {voulu_ens.get('motif') or 'sans motif'}"
        elif not code_ens:
            bloquants.append(f"enseignant {trigramme} sans code Celcat")
        if len(teacher_codes) > 1:
            bloquants.append(
                f"{len(teacher_codes)} enseignants ({', '.join(teacher_codes)}) : "
                "Celcat n'en accepte qu'un, à trancher à la main"
            )

    salle, motif_salle = _salle_celcat(cfg, room_id)
    salle_voulue = (cfg.sans_code.get("salles") or {}).get(room_id or "")
    if motif_salle and salle_voulue:
        motif_salle = ""
        ens_voulu = ens_voulu or f"salle « {room_id} » sans équivalent Celcat, voulu : {salle_voulue.get('motif') or 'sans motif'}"
    if motif_salle:
        bloquants.append(motif_salle)

    # Règle d'envoi (01/10/2026, `celcat.yaml::regles_envoi`) : catégorie,
    # remarque et département imposés ; module selon la règle — « aucun »
    # (WR100BU : rien n'est cherché, le code est inventé) ou « cours » (PTUT :
    # le module du cours s'il est connu, AUCUN sinon, jamais un module
    # « PTUT »). Une règle passe devant « sans code (voulu) ».
    regle_appliquee, non_envoyee = regle_pour(cfg, course_code, session_type, teacher_codes)
    code_module: str | None = None
    if regle_appliquee is not None:
        if regle_appliquee.module == MODULE_COURS:
            code_module = cfg.modules.get(course_code.upper())
    elif not non_envoyee:
        code_module = cfg.modules.get(course_code.upper())
        voulu = (cfg.sans_code.get("cours") or {}).get(course_code.upper())
        if not code_module and voulu:
            non_envoyee = f"module {course_code} sans code Celcat, voulu : {voulu.get('motif') or 'sans motif'}"
        elif not code_module:
            bloquants.append(f"module {course_code} sans code Celcat")

    type_nom = session_type.strip().upper()
    type_celcat = cfg.types_seance.get(type_nom)
    # L'index numérique (TD=4, TP=6) est un héritage des `.bat`. Le pilote
    # désigne la catégorie par son LIBELLÉ (`[CM]`, `[TD]`, `[TP]`), relevé
    # le 01/09/2026. Un CM n'a pas d'index et n'en a plus besoin.
    # Sous une règle d'envoi, la catégorie est celle de la règle : le type
    # de la séance n'en décide plus (PTUT n'a pas de catégorie ordinaire).
    if regle_appliquee is not None:
        pass
    elif not type_nom:
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
        non_envoyee=non_envoyee or ens_voulu,
        regle=regle_appliquee.cle if regle_appliquee else "",
        regle_libelle=regle_appliquee.libelle(code_module) if regle_appliquee else "",
        categorie_celcat=regle_appliquee.categorie if regle_appliquee else "",
        departement=regle_appliquee.departement if regle_appliquee else "",
        remarque=regle_appliquee.remarque if regle_appliquee else "",
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
        # Même exclusion que `api/main.py::_entrees_celcat` et le hook
        # immédiat (`ops.py::_executer`) — un évènement à horaire libre
        # tombé dans la pause méridienne (retour Jules 23/09/2026) n'a
        # jamais d'entrée Celcat, SLOT_TIMES ci-dessus ne connaissant que
        # les six créneaux fixes.
        if (getattr(session, "metadata", None) or {}).get("pause_midi"):
            continue
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
