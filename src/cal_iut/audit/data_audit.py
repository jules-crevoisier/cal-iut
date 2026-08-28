"""Audit des données sources et de leur interprétation.

Famille de bugs visée : **une donnée source mal comprise**. Les trois trouvées
le 25/08/2026 partagent le même profil — le parseur ne lève rien, produit
quelque chose de plausible, et ce quelque chose est faux :

- « mercredi 23/09/26 » lu comme « tous les mercredis de l'année » (le format
  numérique n'était pas reconnu, seul le nom du jour subsistait) ;
- « ALO : LOIZON ARIANESLO : LOIZON Sébastien » : le second trigramme, collé au
  prénom du premier, n'était jamais extrait ;
- un volume horaire attribué en totalité au premier enseignant d'un module
  partagé, parce que les séances étaient comptées en séances et les quotas en
  créneaux.

D'où deux angles ici : ce que le parseur a explicitement renoncé à interpréter
(`unresolved_tokens` — un aveu, à lire), et ce qu'il a interprété d'une manière
statistiquement suspecte (une contrainte anormalement large, un volume qui
n'atteint jamais un enseignant).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from cal_iut.audit.report import AuditReport, Finding, Severity
from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.models.entities import Course, TeacherAvailability
from cal_iut.models.session import SessionToPlace

# Un fragment typé « tous les mercredis » qui contient un nombre ressemblant à
# une date est presque toujours une date isolée mal interprétée.
_DATE_LIKE = re.compile(r"(?<!\d)\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?(?!\d)")


def audit_teacher_constraints(
    availability: list[TeacherAvailability],
    calendar: AcademicCalendar,
    report: AuditReport,
) -> None:
    source = "contraintes/05_enseignants_contraintes.json"
    jours_ouvrables = max(
        1,
        sum(
            1
            for w in range(len(calendar.teaching_mondays))
            for d in range(5)
            if (day := calendar.week_day_to_date(w, d)) is not None
            and day not in calendar.blocked_dates
            and day not in calendar.holidays
        ),
    )

    non_interpretes: list[str] = []
    for avail in availability:
        unresolved = list((avail.metadata or {}).get("unresolved_tokens") or [])
        for raw in unresolved:
            # Certaines formulations libres SONT reprises par un champ structuré :
            # « 1 ou 2 semaines /mois » (ARA) devient `monthly_cluster_max_weeks`.
            # Les signaler serait un faux positif.
            if avail.monthly_cluster_max_weeks and "mois" in raw.lower():
                continue
            non_interpretes.append(f"{avail.teacher_code} : « {raw} »")
    if non_interpretes:
        report.add(Finding(
            Severity.ALERTE,
            "donnees.contrainte_non_interpretee",
            f"{len(non_interpretes)} contrainte(s) enseignant n'ont PAS pu être traduites en "
            "créneaux : elles ne s'appliquent donc pas du tout.",
            quoi_faire=(
                "Reformuler la contrainte dans le CSV source sous une forme reconnue "
                "(« mardi après-midi », « jeudi 12 novembre 2026 », « du lundi 2 au "
                "vendredi 6 novembre 2026 »), puis relancer "
                "`python scripts/build_contraintes.py`."
            ),
            ou=source,
            details=non_interpretes,
        ))
    else:
        report.ok("donnees.contrainte_non_interpretee",
                  "toutes les contraintes enseignant ont été traduites en créneaux")

    # Un token RÉCURRENT dont le texte contient une date : cf. le bug VMA.
    suspects: list[str] = []
    for avail in availability:
        raw_indispo = str((avail.metadata or {}).get("raw_indisponibilites") or "")
        for fragment in re.split(r"\s+-\s+|\n", raw_indispo):
            if _DATE_LIKE.search(fragment) and not re.search(r"\d{4}", fragment):
                # Le fragment contient une date numérique : vérifier qu'elle a bien
                # produit une date et non un blocage hebdomadaire.
                dates = [
                    d for d in ((avail.metadata or {}).get("forbidden_dates") or [])
                ]
                if not dates:
                    suspects.append(f"{avail.teacher_code} : « {fragment.strip()} »")
    if suspects:
        report.add(Finding(
            Severity.ALERTE,
            "donnees.date_lue_comme_recurrence",
            f"{len(suspects)} fragment(s) contiennent une date numérique mais n'ont produit "
            "aucune date bloquée — probablement lus comme une indisponibilité HEBDOMADAIRE.",
            quoi_faire=(
                "Vérifier ces lignes dans le CSV. Écrire le mois en toutes lettres lève "
                "toute ambiguïté. Bug réel du 25/08/2026 : « mercredi 23/09/26 » bloquait "
                "tous les mercredis de l'année."
            ),
            ou=source,
            details=suspects,
        ))

    # Contrainte anormalement large : un enseignant bloqué presque tout le temps
    # est le symptôme classique d'une récurrence là où il fallait une date.
    for avail in availability:
        bloques = {tuple(x) for x in avail.forbidden_slots}
        dates_bloquees = len((avail.metadata or {}).get("forbidden_dates") or [])
        # « Jamais disponible » = plus AUCUN créneau libre dans la semaine type,
        # pas « au moins un créneau bloqué chaque jour » : KBR ne commence qu'à
        # 9h30 (5 créneaux bloqués, un par jour) et reste évidemment plaçable.
        libres = 6 * 5 - len(bloques)
        if avail.allowed_slots:
            libres = len({tuple(p) for p in avail.allowed_slots} - bloques)
        if libres <= 0:
            report.add(Finding(
                Severity.ERREUR,
                "donnees.enseignant_jamais_disponible",
                f"{avail.teacher_code} n'a plus AUCUN créneau libre dans la semaine type : "
                "aucune séance ne pourra lui être affectée.",
                quoi_faire="Vérifier sa ligne dans le CSV CONTRAINTES ENSEIGNANTS.",
                ou=source,
            ))
        elif libres <= 4:
            report.add(Finding(
                Severity.ALERTE,
                "donnees.enseignant_tres_contraint",
                f"{avail.teacher_code} n'a que {libres} créneau(x) libre(s) par semaine type.",
                quoi_faire=(
                    "Vérifier que c'est bien voulu. Un enseignant à ce point contraint "
                    "rend tout le reste de l'emploi du temps difficile à construire."),
                ou=source,
            ))
        if dates_bloquees > jours_ouvrables * 0.5:
            report.add(Finding(
                Severity.ALERTE,
                "donnees.trop_de_dates_bloquees",
                f"{avail.teacher_code} : {dates_bloquees} journées bloquées sur "
                f"{jours_ouvrables} jours ouvrables — plus de la moitié de l'année.",
                quoi_faire=(
                    "Vérifier s'il s'agit bien de dates ponctuelles. Un référent de "
                    "plusieurs SAE cumule vite : `data/config/sae_teacher_phases.yaml` "
                    "permet de restreindre ce cumul aux jours réellement encadrés."
                ),
                ou=source,
            ))


def audit_maquette(
    courses: list[Course],
    sessions: list[SessionToPlace],
    report: AuditReport,
    semestres: set[str] | None = None,
) -> None:
    """Volumes déclarés vs séances réellement produites, enseignant par enseignant.

    `semestres` borne l'audit au périmètre réellement ingéré : S2/S4/S6 sont hors
    périmètre 2026-2027 (cf. `pipeline.SEMESTRE_GROUPS`), leurs modules n'ont donc
    aucune séance et ce n'est pas un défaut.
    """
    sessions_par_cours: dict[str, list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        sessions_par_cours[f"{s.course_code}:{s.semestre}"].append(s)

    volume_perdu: list[str] = []
    prof_sans_seance: list[str] = []
    for course in courses:
        if course.parcours == "admin" or course.hors_service:
            continue
        if semestres is not None and course.semestre not in semestres:
            continue
        produites = sessions_par_cours.get(f"{course.code}:{course.semestre}", [])
        attendues = sum(int(course.volumes.get(k, 0) or 0) for k in ("cm", "td", "tp"))
        if attendues and not produites:
            volume_perdu.append(
                f"{course.code} ({course.semestre}) : {attendues} séance(s) au volume, 0 générée"
            )
            continue
        if not produites:
            continue
        # Un enseignant porteur de volume qui ne récupère aucune séance : c'est
        # exactement le bug WSA501D (34 créneaux à JSA, 0 à BTO).
        porteurs = {
            b.teacher.code
            for b in course.profs
            if any(int(getattr(b, k, 0) or 0) > 0 for k in ("cm", "td", "tp"))
        }
        servis = {code for s in produites for code in s.teacher_codes}
        oublies = sorted(porteurs - servis)
        if oublies:
            prof_sans_seance.append(
                f"{course.code} ({course.semestre}) : {', '.join(oublies)} "
                f"porte(nt) du volume mais n'a/n'ont aucune séance"
            )

    if volume_perdu:
        report.add(Finding(
            Severity.ERREUR, "donnees.volume_sans_seance",
            f"{len(volume_perdu)} module(s) déclarent des heures mais ne produisent aucune séance.",
            quoi_faire=(
                "Vérifier la progression du module et la répartition des volumes entre "
                "enseignants dans la maquette source."),
            ou="contraintes/07_modules_maquette_progression.json", details=volume_perdu))
    else:
        report.ok("donnees.volume_sans_seance", "tout module à volume produit bien des séances")

    if prof_sans_seance:
        report.add(Finding(
            Severity.ERREUR, "donnees.enseignant_sans_seance",
            f"{len(prof_sans_seance)} module(s) où un enseignant porteur de volume ne reçoit "
            "AUCUNE séance — son service disparaît de l'emploi du temps.",
            quoi_faire=(
                "Bug réel du 25/08/2026 sur WSA501D : le découpage comptait des séances "
                "là où la maquette compte des créneaux. Vérifier `_teacher_for_group` et "
                "les règles `double_sessions` / `teacher_distribution` du module."),
            ou="ingestion/normalize.py", details=prof_sans_seance))
    else:
        report.ok("donnees.enseignant_sans_seance",
                  "chaque enseignant porteur de volume reçoit au moins une séance")


def audit_sae(
    data_root: Path,
    report: AuditReport,
    scheduled: set[tuple[str, str]],
    semestres: set[str] | None = None,
) -> None:
    path = data_root / "contraintes" / "09_dates_sae.json"
    if not path.exists():
        report.add(Finding(
            Severity.ERREUR, "donnees.fichier_manquant",
            "contraintes/09_dates_sae.json est absent : aucune SAE ne sera sanctuarisée.",
            quoi_faire="Lancer `python scripts/build_contraintes.py`.", ou=str(path)))
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    sans_dates: list[str] = []
    for entry in data.get("sae", []):
        volumes = entry.get("volumes_etudiant_seances") or {}
        total = sum(int(volumes.get(k, 0) or 0) for k in ("cm", "td", "tp"))
        code, semestre = str(entry.get("code_matiere")), str(entry.get("semestre"))
        if semestres is not None and semestre not in semestres:
            continue
        if total and not entry.get("fenetres"):
            if (code.upper(), semestre) in scheduled:
                continue  # planifiée par le solveur : c'est un choix documenté
            sans_dates.append(f"{code} ({semestre}) : {total} séance(s), aucune date")
    if sans_dates:
        report.add(Finding(
            Severity.ALERTE, "donnees.sae_sans_dates",
            f"{len(sans_dates)} SAE ont des heures mais aucune date : elles ne sanctuarisent "
            "rien, et leurs heures n'apparaîtront nulle part.",
            quoi_faire=(
                "Soit renseigner les dates dans « DATES SAE », soit déclarer la SAE dans "
                "`course_scheduling_rules.yaml::solver_scheduled_sae` pour que le solveur "
                "la place lui-même."),
            ou="contraintes/09_dates_sae.json", details=sans_dates))
    else:
        report.ok("donnees.sae_sans_dates", "toute SAE à volume a des dates ou est planifiée")


def audit_evenements_fixes(data_root: Path, report: AuditReport) -> None:
    """Un événement horodaté bloque-t-il réellement un créneau ?

    Trouvé par test de propriété le 26/08/2026 : la grille n'a AUCUN créneau
    entre 12h30 et 14h (pause méridienne). Un événement saisi « 13h00 Conseil »
    sans heure de fin est donc lu, affiché, et ne bloque rien — il a l'air pris
    en compte sans l'être. Aucun événement réel n'était dans ce cas ce jour-là ;
    ce contrôle est là pour le jour où quelqu'un en saisira un.
    """
    from cal_iut.ingestion.planning_loader import _slots_for_interval

    path = data_root / "contraintes" / "10_dates_fixes.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    muets: list[str] = []
    for entry in data.get("evenements", []):
        debut = entry.get("debut_minutes")
        if debut is None:
            continue  # sans horaire, l'événement est un simple repère : normal
        if not _slots_for_interval(debut, entry.get("fin_minutes")):
            muets.append(
                f"{entry.get('date')} {entry.get('debut')} — {entry.get('motif', '')[:40]}"
            )
    if muets:
        report.add(Finding(
            Severity.ALERTE, "donnees.evenement_sans_creneau",
            f"{len(muets)} événement(s) horodaté(s) ne bloquent aucun créneau : leur horaire "
            "tombe dans la pause méridienne (12h30-14h), où la grille n'a rien à réserver.",
            quoi_faire=(
                "Renseigner une HEURE DE FIN dans « Dates MMI » pour que l'événement couvre "
                "les créneaux de l'après-midi, ou vérifier que l'horaire est correct."),
            ou="contraintes/10_dates_fixes.json", details=muets))
    else:
        report.ok("donnees.evenement_sans_creneau",
                  "tout événement horodaté bloque bien au moins un créneau")


def audit_calendrier(calendar: AcademicCalendar, report: AuditReport) -> None:
    if not calendar.teaching_mondays:
        report.add(Finding(
            Severity.ERREUR, "donnees.calendrier_vide",
            "Aucune semaine enseignable dans le calendrier : rien ne pourra être placé.",
            quoi_faire="Vérifier « INDISPONIBILITÉS IUT » puis relancer build_contraintes.",
            ou="contraintes/02_calendrier_iut.json"))
        return
    premier, dernier = calendar.teaching_mondays[0], calendar.teaching_mondays[-1]
    report.ok(
        "donnees.calendrier",
        f"{len(calendar.teaching_mondays)} semaines enseignables, du {premier} au {dernier}",
    )
    feries_ouvres = [d for d in calendar.holidays if d.weekday() < 5]
    if not feries_ouvres:
        report.add(Finding(
            Severity.ALERTE, "donnees.aucun_ferie",
            "Aucun jour férié en semaine dans le calendrier — inhabituel sur une année complète.",
            quoi_faire="Vérifier la section « JOURS FÉRIÉS » du fichier INDISPONIBILITÉS IUT.",
            ou="contraintes/02_calendrier_iut.json"))


def audit_generated_freshness(data_root: Path, report: AuditReport) -> None:
    """Les `contraintes/*.json` sont-ils plus récents que leurs sources ?

    Piège classique pour un nouvel utilisateur : éditer un CSV et lancer le
    solveur sans régénérer. Le fichier source est alors ignoré en silence.
    """
    src = data_root / "contraintes_update"
    out = data_root / "contraintes"
    if not src.is_dir() or not out.is_dir():
        return
    generes = [p for p in out.glob("*.json") if p.name[0].isdigit()]
    if not generes:
        return
    plus_recent_genere = max(p.stat().st_mtime for p in generes)
    # Une date plus récente ne prouve pas un contenu différent : un export
    # retéléchargé à l'identique fait avancer la date sans rien changer. Pour
    # les fichiers recopiés tels quels dans `contraintes/`, on tranche sur le
    # CONTENU — sinon le contrôle crie à tort, et un contrôle qui crie à tort
    # finit ignoré (cf. docs/DATA.md §66.7).
    en_retard = []
    for p in sorted(src.iterdir()):
        if not p.is_file() or p.stat().st_mtime <= plus_recent_genere:
            continue
        copie = out / p.name
        if copie.exists() and copie.read_bytes() == p.read_bytes():
            continue
        en_retard.append(p.name)
    if en_retard:
        report.add(Finding(
            Severity.ERREUR, "donnees.sources_plus_recentes",
            f"{len(en_retard)} fichier(s) source ont été modifiés APRÈS la dernière "
            "génération : leurs changements ne sont pas pris en compte.",
            quoi_faire="Lancer `python scripts/build_contraintes.py` puis `cal-iut ingest`.",
            ou="contraintes_update/", details=sorted(en_retard)))
    else:
        report.ok("donnees.fraicheur", "les contraintes générées sont à jour avec les sources")
