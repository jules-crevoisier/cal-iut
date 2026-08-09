"""Fusion des exports maquette et progression."""

from cal_iut.models.entities import (
    Course,
    OrdonnancementPosition,
    SchedulingConstraint,
    Teacher,
    TeacherBlock,
    TeacherCorrection,
)


def _parse_parcours(parcours: str) -> tuple[str, str | None, str | None]:
    """Ex: BUT2-DEV-FI → (BUT2, DEV, FI)."""
    if parcours == "admin":
        return "admin", None, None
    parts = parcours.split("-")
    annee = parts[0]
    if len(parts) == 1:
        return annee, None, None
    if len(parts) == 2:
        return annee, parts[1], None
    return annee, parts[1], parts[2]


def _teacher_from_raw(raw: dict[str, object]) -> Teacher:
    return Teacher(
        code=str(raw["code"]),
        nom=str(raw["nom"]),
        prenom=str(raw["prenom"]),
    )


def _teacher_block_from_raw(raw: dict[str, object]) -> TeacherBlock:
    return TeacherBlock(
        teacher=_teacher_from_raw(raw),
        block=str(raw.get("block", "block1")),
        cm=float(raw.get("cm") or 0),
        td=float(raw.get("td") or 0),
        tp=float(raw.get("tp") or 0),
        ptut=float(raw.get("ptut") or 0),
        nbGpTd=int(raw.get("nbGpTd") or 1),
        nbGpTp=int(raw.get("nbGpTp") or 1),
    )


def merge_exports(
    maquette: list[dict[str, object]],
    progression: list[dict[str, object]],
) -> list[Course]:
    """Fusionne les deux exports par clé (code_matiere, semestre, parcours)."""
    maquette_index: dict[tuple[str, str, str], dict[str, object]] = {}
    for item in maquette:
        key = (str(item["code_matiere"]), str(item["semestre"]), str(item["parcours"]))
        maquette_index[key] = item

    courses: list[Course] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for prog in progression:
        key = (str(prog["code_matiere"]), str(prog["semestre"]), str(prog["parcours"]))
        seen_keys.add(key)
        maq = maquette_index.get(key, {})
        maquette_data = maq.get("maquette") or {}
        total = maq.get("total") or prog.get("volumes") or {}

        annee, filiere, mode = _parse_parcours(str(prog["parcours"]))
        groupes = prog.get("groupes") or maquette_data.get("groupes") or {}

        ordonnancement = [
            SchedulingConstraint(
                position=OrdonnancementPosition(str(o["position"])),
                target_course_code=str(o["code_matiere"]),
                target_course_name=str(o["nom_matiere"]),
                semestre=str(o["semestre"]),
            )
            for o in (prog.get("ordonnancement") or [])
        ]

        progression_data = prog.get("progression") or {}
        profs_raw = maq.get("profs") or []

        courses.append(
            Course(
                code=str(prog["code_matiere"]),
                name=str(prog["nom_matiere"]),
                semestre=str(prog["semestre"]),
                parcours=str(prog["parcours"]),
                annee=annee,
                filiere=filiere,
                mode=mode,
                codelement=prog.get("codelement") or maquette_data.get("codelement"),
                vet=maquette_data.get("vet"),
                lead=_teacher_from_raw(prog["lead"]),
                profs=[_teacher_block_from_raw(p) for p in profs_raw],
                volumes={
                    "cm": float((total.get("cm") or 0)),
                    "td": float((total.get("td") or 0)),
                    "tp": float((total.get("tp") or 0)),
                    "ptut": float((total.get("ptut") or 0)),
                },
                groupes_td=int(groupes.get("td") or 1),
                groupes_tp=int(groupes.get("tp") or 1),
                progression_defined=bool(progression_data.get("definie")),
                seance_sequence=list(progression_data.get("seances") or []),
                ordonnancement=ordonnancement,
                commentaire_edt=prog.get("commentaire_edt"),
                bloque=bool(maquette_data.get("bloque")),
                hors_service=bool(maquette_data.get("hors_service")),
            )
        )

    for key, maq in maquette_index.items():
        if key in seen_keys:
            continue
        annee, filiere, mode = _parse_parcours(str(maq["parcours"]))
        maquette_data = maq.get("maquette") or {}
        total = maq.get("total") or {}
        groupes = maquette_data.get("groupes") or {}

        courses.append(
            Course(
                code=str(maq["code_matiere"]),
                name=str(maq["nom_matiere"]),
                semestre=str(maq["semestre"]),
                parcours=str(maq["parcours"]),
                annee=annee,
                filiere=filiere,
                mode=mode,
                codelement=maquette_data.get("codelement"),
                vet=maquette_data.get("vet"),
                lead=_teacher_from_raw(maq["lead"]),
                profs=[_teacher_block_from_raw(p) for p in (maq.get("profs") or [])],
                volumes={
                    "cm": float(total.get("cm") or 0),
                    "td": float(total.get("td") or 0),
                    "tp": float(total.get("tp") or 0),
                    "ptut": float(total.get("ptut") or 0),
                },
                groupes_td=int(groupes.get("td") or 1),
                groupes_tp=int(groupes.get("tp") or 1),
                progression_defined=False,
                seance_sequence=[],
                ordonnancement=[],
                commentaire_edt=None,
                bloque=bool(maquette_data.get("bloque")),
                hors_service=bool(maquette_data.get("hors_service")),
            )
        )

    return sorted(courses, key=lambda c: (c.parcours, c.semestre, c.code))


def apply_teacher_corrections(
    courses: list[Course],
    corrections: list[TeacherCorrection],
) -> list[Course]:
    """
    Applique les corrections d'enseignant (cf. `TeacherCorrection`) après la
    fusion — `correct_teacher_code` est résolu par recoupement avec n'importe
    quel autre cours du jeu de données utilisant déjà ce code, jamais
    ressaisi à la main ici.
    """
    if not corrections:
        return courses

    teacher_by_code: dict[str, Teacher] = {}
    for c in courses:
        teacher_by_code.setdefault(c.lead.code, c.lead)
        for p in c.profs:
            teacher_by_code.setdefault(p.teacher.code, p.teacher)

    by_key = {(corr.course_code, corr.semestre, corr.parcours): corr for corr in corrections}

    result: list[Course] = []
    for c in courses:
        corr = by_key.get((c.code, c.semestre, c.parcours))
        if corr is None:
            result.append(c)
            continue

        correct = teacher_by_code.get(corr.correct_teacher_code)
        if correct is None:
            raise ValueError(
                f"TeacherCorrection {corr.course_code}/{corr.semestre}/{corr.parcours} : "
                f"correct_teacher_code={corr.correct_teacher_code!r} introuvable ailleurs "
                "dans le jeu de données (nom/prénom non résolvables)."
            )

        new_lead = correct if c.lead.code == corr.wrong_teacher_code else c.lead
        new_profs = [
            p.model_copy(update={"teacher": correct}) if p.teacher.code == corr.wrong_teacher_code else p
            for p in c.profs
        ]
        result.append(c.model_copy(update={"lead": new_lead, "profs": new_profs}))

    return result
