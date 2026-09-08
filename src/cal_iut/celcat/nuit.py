"""Job de nuit : pousser les semaines validées + scanner les extras Live."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from cal_iut.api.state import get_state
from cal_iut.celcat.ecriture import creer_manquants, resoudre_groupe, resoudre_ids
from cal_iut.celcat.etat import charger, live_actuel
from cal_iut.celcat.extras import enregistrer
from cal_iut.celcat.extras import lister as lister_extras
from cal_iut.celcat.file_attente import (
    cle_job,
    enfiler,
    lister,
    repousser_en_fin,
    retirer_traites,
)
from cal_iut.celcat.formulaire import charger_carte
from cal_iut.celcat.instantane import lire as lire_instantane
from cal_iut.celcat.lecture import (
    EvenementCelcat,
    est_cours,
    est_fantome,
    est_ferie,
    evenement_depuis_rpc,
    indice_depuis_lundi,
)
from cal_iut.celcat.logs import append as journaliser
from cal_iut.celcat.mapping import entrees_pour_state
from cal_iut.celcat.modification import ElementModification, modifier_manquants
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT
from cal_iut.celcat.ops import correspond_live
from cal_iut.celcat.planification import contexte as contexte_comparaison
from cal_iut.celcat.planification import jobs_depuis_lignes
from cal_iut.celcat.planification import lignes as lignes_comparaison
from cal_iut.celcat.rpc import masquer_semaine
from cal_iut.celcat.rpc_config import charger_methodes
from cal_iut.celcat.suppression import ElementSuppression, supprimer_manquants
from cal_iut.celcat.sync import marquer_saisi, marquer_supprime

# Même valeur que `scripts/pousser_manquants_celcat.py::PREMIERE_SEMAINE_CELCAT`
# — indice `weeks` 0 = cette semaine ISO. Dupliqué plutôt qu'importé d'un
# script : les scripts ne sont pas un module importable en amont de `src/`.
PREMIERE_SEMAINE_CELCAT = 34


def _event_id(row: dict[str, Any]) -> int | None:
    brut = row.get("event_id")
    if brut in (None, "", 0, "0"):
        return None
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def _group_ids_depuis_nom(nom: str) -> list[str]:
    if not nom.strip():
        return []
    state = get_state()
    cible = nom.strip().upper()
    for groupe in state.groups:
        label = str(getattr(groupe, "label", "") or "").strip()
        semestre = str(getattr(groupe, "semestre", "") or "").strip()
        compose = f"BUT MMI {semestre} {label}".strip().upper()
        if cible == compose or (label and label.upper() in cible):
            return [str(groupe.id)]
    return []


def _teacher_codes_depuis_nom(nom: str) -> list[str]:
    if not nom.strip():
        return []
    state = get_state()
    morceaux = nom.strip().upper()
    codes: list[str] = []
    for cours in state.courses:
        for bloc in getattr(cours, "profs", []) or []:
            prof = getattr(bloc, "teacher", None)
            if prof is None:
                continue
            nom_prof = f"{getattr(prof, 'nom', '')} {getattr(prof, 'prenom', '')}".upper()
            code = str(getattr(prof, "code", "") or "")
            if code and (getattr(prof, "nom", "").upper() in morceaux or morceaux in nom_prof):
                if code not in codes:
                    codes.append(code)
    return codes


def _code_depuis_ev(ev: EvenementCelcat) -> str:
    nom = (ev.module_nom or "").strip()
    if nom:
        return nom.split()[0]
    return (ev.module_code or "").strip()


def _evenements_depuis_page(page: Any) -> list[EvenementCelcat]:
    reponses = getattr(page, "reponses", None)
    if not isinstance(reponses, dict):
        return []
    bruts = reponses.get("udlTimetables.load")
    if not isinstance(bruts, list):
        return []
    evenements: list[EvenementCelcat] = []
    for brut in bruts:
        if not isinstance(brut, dict):
            continue
        groupes = brut.get("groups") if isinstance(brut.get("groups"), list) else []
        tete = groupes[0] if groupes and isinstance(groupes[0], dict) else {}
        gid = int(tete["id"]) if tete.get("id") is not None else 0
        gnom = str(tete.get("name") or "")
        evenements.append(evenement_depuis_rpc(brut, group_id=gid, groupe_nom=gnom))
    return evenements


def _a_un_match_caliut(ev: EvenementCelcat) -> bool:
    state = get_state()
    for placement in state.timetable:
        session = state.sessions_by_id.get(placement.session_id)
        if session is None:
            continue
        if correspond_live(session, placement, ev):
            return True
    return False


def _scanner_extras(page: Any, doc: dict[str, Any]) -> None:
    evenements = list(live_actuel())
    vus = {ev.event_id for ev in evenements}
    if page is not None:
        for ev in _evenements_depuis_page(page):
            if ev.event_id not in vus:
                evenements.append(ev)
                vus.add(ev.event_id)

    ignores = doc.get("ignores") if isinstance(doc.get("ignores"), dict) else {}
    existants = {str(x.get("id")): x for x in lister_extras()}

    for ev in evenements:
        if not est_cours(ev) or est_ferie(ev) or est_fantome(ev):
            continue
        extra_id = f"extra-{ev.event_id}"
        if extra_id in ignores or str(ev.event_id) in ignores:
            continue
        deja = existants.get(extra_id)
        if deja and deja.get("statut") in ("ignore", "ajoute"):
            continue
        if _a_un_match_caliut(ev):
            continue
        code = _code_depuis_ev(ev)
        group_ids = _group_ids_depuis_nom(ev.groupe_nom)
        teacher_codes = _teacher_codes_depuis_nom(ev.enseignant)
        semaine = ev.indice_semaine
        enregistrer(
            {
                "id": extra_id,
                "statut": "ouvert",
                "course_code": code,
                "module_nom": ev.module_nom,
                "libelle": ev.module_nom,
                "event_id": ev.event_id,
                "groupe": ev.groupe_nom,
                "group_ids": group_ids,
                "teacher_codes": teacher_codes,
                "jour": ev.jour,
                "heure_debut": ev.heure_debut,
                "heure_fin": ev.heure_fin,
                "salle": ev.salle,
                "enseignant": ev.enseignant,
                "semaine": semaine,
            }
        )


def _masque_pour(entree: Any) -> str:
    """Masque `weeks` (54 caractères, 1×Y) pour une entrée — calcul PUR
    (aucun RPC) : `lundi` -> indice `weeks`. Ne lève jamais : un lundi
    absent ou hors calendrier retombe sur un masque vide, que
    `verifier_avant_envoi` refusera proprement en aval (SemainesNonRestreintes)."""
    try:
        if not str(getattr(entree, "lundi", "") or "").strip():
            return "N" * 54
        from datetime import date

        indice = indice_depuis_lundi(
            date.fromisoformat(entree.lundi), premiere_semaine_celcat=PREMIERE_SEMAINE_CELCAT
        )
        return masquer_semaine(longueur=54, indice=indice)
    except Exception:  # noqa: BLE001
        return "N" * 54


def _evenement_a_disparu(motif: str) -> bool:
    """Ce motif prouve-t-il que l'évènement n'existe PLUS dans Celcat ?

    Deux formulations, toutes deux vues en production le 08/09/2026 :
    la nôtre, quand `localiser_evenement` ne retrouve rien
    (« event_id=1953820 absent des group_ids=[1661972] interrogés »), et
    celle de Celcat lui-même (« L'enregistrement n'existe pas. Il a peut être
    été supprimé par un autre utilisateur. »).

    STRICTEMENT CES DEUX-LÀ. Le journal est la seule protection contre les
    doublons : oublier un `event_id` sur une panne réseau, un délai dépassé
    ou un refus temporaire ferait créer un SECOND évènement à côté de celui
    qui existe toujours. En particulier « une des ressources affectées a été
    supprimée » parle d'une SALLE ou d'un ENSEIGNANT disparu, pas de
    l'évènement — celui-ci est bien là.
    """
    texte = str(motif or "")
    return "absent des group_ids" in texte or "L'enregistrement n'existe pas" in texte


def _group_id_celcat_depuis_nom(nom: str) -> int | None:
    """ID Celcat d'un groupe depuis son nom (« BUT MMI S1 CM »).

    Lu dans `data/config/celcat_groupes.yaml`, la même source que l'écriture :
    deviner un identifiant produirait une suppression sur le mauvais groupe,
    ou aucune. Rend None si le nom est inconnu — le job n'est alors pas
    enfilé, plutôt qu'enfilé sans groupe et bloqué à jamais en file.
    """
    from cal_iut.celcat.ecriture import _groupes_connus

    if not nom.strip():
        return None
    connus = _groupes_connus()
    direct = connus.get(nom.strip())
    if direct is not None:
        return int(direct)
    cible = nom.strip().upper()
    for cle, valeur in connus.items():
        if cle.strip().upper() == cible:
            return int(valeur)
    return None


def _indice_pour(entree: Any) -> int | None:
    """Indice `weeks` d'une entrée, ou None si on ne peut pas le calculer.

    Même calcul que `_masque_pour`, rendu séparément : le masque sert à
    ÉCRIRE, l'indice sert à DÉCIDER si l'on écrit. `_masque_pour` retombe
    volontairement sur un masque vide en cas de lundi illisible ; ici il faut
    pouvoir distinguer « semaine 7 » de « je ne sais pas », les deux
    n'appelant pas la même conduite.
    """
    try:
        if not str(getattr(entree, "lundi", "") or "").strip():
            return None
        from datetime import date

        return indice_depuis_lundi(
            date.fromisoformat(entree.lundi), premiere_semaine_celcat=PREMIERE_SEMAINE_CELCAT
        )
    except Exception:  # noqa: BLE001
        return None


def _ecarter_semaines_non_posees(
    jobs: list[dict[str, Any]], entrees: dict[str, Any], bilan: BilanDrainage
) -> list[dict[str, Any]]:
    """Retire les CRÉATIONS visant une semaine que Celcat n'a pas encore
    posée (consigne du 08/09/2026 : « les semaines pas posées dans Celcat il
    faut attendre »).

    Seules les créations sont concernées : un `update` ou un `delete` porte
    un `event_id`, donc l'évènement EXISTE déjà là-bas et la semaine y est
    posée par construction. Différer une correction laisserait une heure
    fausse en ligne — le signalement de Régis Huez cette semaine.

    APPELÉ AVANT LE DÉCOUPAGE PAR `limite`, et c'est essentiel : le cycle
    prend les PREMIERS jobs de la file. Trier après aurait rendu des cycles
    entiers vides dès que des différés occupent la tête de file, chaque
    passage reprenant les mêmes — une file qui cesse de se vider tout en
    ayant l'air de tourner, c'est-à-dire la panne du 07/09/2026 reproduite
    par le remède.
    """
    from cal_iut.celcat.instantane import lire
    from cal_iut.celcat.semaines_posees import cours_par_semaine, motif_attente, semaines_posees

    attendus: dict[int, int] = {}
    for entree in entrees.values():
        indice = _indice_pour(entree)
        if indice is not None:
            attendus[indice] = attendus.get(indice, 0) + 1

    releve = lire()
    posees = semaines_posees(releve.evenements, attendus=attendus)
    presents = cours_par_semaine(releve.evenements)

    retenus: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("action") != "create":
            retenus.append(job)
            continue
        entree = entrees.get(str(job.get("session_id") or ""))
        indice = _indice_pour(entree) if entree is not None else None
        # Une entrée inconnue ou sans lundi lisible passe ici sans être
        # différée : son sort est déjà décidé plus bas (« séance inconnue de
        # la maquette »), et l'écarter ici la ferait disparaître des
        # compteurs sans explication.
        if indice is None or indice in posees:
            retenus.append(job)
            continue
        bilan.differes.append(
            (
                str(job.get("session_id") or ""),
                motif_attente(
                    indice, celcat=presents.get(indice, 0), attendu=attendus.get(indice, 0)
                ),
            )
        )
    return retenus


def _cle_ressources(entree: Any) -> tuple:
    """Ce qui détermine les identifiants Celcat d'une séance.

    Même clé que `scripts/pousser_manquants_celcat.py` : deux séances de la
    même matière, dans la même salle, avec le même enseignant et le même
    type se résolvent à l'identique. Le TYPE en fait partie — c'est lui qui
    choisit la catégorie d'évènement, et l'omettre ferait écrire un TD avec
    la catégorie d'un CM.
    """
    return (
        getattr(entree, "code_module", None),
        getattr(entree, "salle", None),
        getattr(entree, "code_enseignant", None),
        getattr(entree, "type_seance_nom", None),
    )


def _ids_pour(page: Any, entree: Any) -> tuple[dict, str | None]:
    """Résout module/salle/personnel/catégorie/département Celcat via le
    catalogue RPC (`page`). Sur un échec de résolution (catalogue
    indisponible, ressource inconnue), retombe sur `{}` : l'écriture réelle
    (creer_manquants/modifier_manquants) refusera alors proprement via ses
    propres garde-fous plutôt que de faire échouer tout le job de nuit.

    Rend AUSSI la cause de l'échec. Sans elle, l'écriture échouait plus loin
    sur « TD exige event_cat_id pour [TD] — reçu vide » : le symptôme du
    garde-fou, jamais la ressource réellement introuvable — salle ? module ?
    enseignant ? La réponse était dans l'exception, et on la jetait
    (constaté sur 415 échecs le 07/09/2026)."""
    try:
        state = get_state()
        carte = charger_carte(state.config_dir)
        categorie = carte.categorie(entree.type_seance_nom)
        return resoudre_ids(page, entree, categorie=categorie), None
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__} : {exc}"


def _group_id_pour(page: Any, entree: Any, group_id_connu: object) -> int:
    """Préfère le `group_id` déjà porté par le job (posé par `ops.py` ou par
    le job lui-même) ; sinon résout via le catalogue RPC, sinon 0 (échec
    encaissé en aval, jamais une exception qui arrête le job de nuit)."""
    if group_id_connu not in (None, ""):
        try:
            return int(group_id_connu)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    try:
        return resoudre_groupe(page, entree.nom_groupe_celcat)
    except Exception:  # noqa: BLE001
        return 0


@dataclass
class BilanDrainage:
    """Ce qu'un passage de drainage a VRAIMENT fait.

    Existe parce que son absence a coûté cher (07/09/2026) : `_consommer_
    file` ne lisait que les succès, et le worker a répété « file d'attente
    drainée » toutes les minutes pendant des jours sans jamais réussir une
    seule écriture. Une panne totale et une file vide produisaient la même
    ligne de journal — la panne n'a été découverte que par trois
    signalements humains (un cours déplacé resté à son ancienne heure, une
    séance annulée toujours affichée, une catégorie fausse).

    `__bool__` rend « il y avait quelque chose à faire », ce que renvoyait
    l'ancien booléen : un appelant qui ne s'intéresse qu'à ça n'a rien à
    changer.
    """

    en_attente: int = 0
    reussis: int = 0
    echecs: list[tuple[str, str]] = field(default_factory=list)
    ignores: list[tuple[str, str]] = field(default_factory=list)
    # Jobs volontairement NON tentés : leur semaine n'est pas encore posée
    # dans Celcat (consigne du 08/09/2026). Ni un échec ni un abandon — ils
    # restent en file. Comptés à part parce que les confondre avec les
    # ignorés ferait lire « 409 jobs perdus » là où il faut lire « 409 jobs
    # qui attendent que l'équipe ouvre les semaines ».
    differes: list[tuple[str, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.en_attente > 0

    @staticmethod
    def _par_motif(entrees: list[tuple[str, str]], combien: int = 4) -> str:
        """Répartition par motif, du plus fréquent au plus rare.

        Trois exemples pris dans l'ordre d'arrivée ne disent pas si l'on a
        UN problème massif ou quinze cas isolés — c'est pourtant ce qui
        décide par quoi commencer. Chaque motif garde le nom d'UNE séance
        concernée : un compte sans exemple ne permet pas d'aller regarder
        dans Celcat.
        """
        from collections import Counter

        comptes = Counter(motif for _sid, motif in entrees)
        exemple = {}
        for sid, motif in entrees:
            exemple.setdefault(motif, sid)
        morceaux = [
            f"{n}× {motif} (ex. {exemple[motif]})" for motif, n in comptes.most_common(combien)
        ]
        reste = len(comptes) - len(morceaux)
        if reste > 0:
            morceaux.append(f"et {reste} autre(s) motif(s)")
        return " | ".join(morceaux)

    def resume(self) -> str:
        if not self.en_attente:
            return "file d'attente vide"
        parts = [f"{self.en_attente} job(s)", f"{self.reussis} réussi(s)"]
        if self.echecs:
            parts.append(f"{len(self.echecs)} en échec — {self._par_motif(self.echecs)}")
        if self.ignores:
            parts.append(f"{len(self.ignores)} ignoré(s) — {self._par_motif(self.ignores, 2)}")
        if self.differes:
            parts.append(
                f"{len(self.differes)} en attente d'une semaine posée "
                f"— {self._par_motif(self.differes, 2)}"
            )
        return " — ".join(parts)


def _avec_cause(
    echecs: list[tuple[str, str]], cause: str | None
) -> list[tuple[str, str]]:
    """Rattache la cause d'une résolution d'ids ratée au motif d'échec.

    Sans elle, l'écriture rend « TD exige event_cat_id pour [TD] — reçu
    vide » : le symptôme du garde-fou, jamais la ressource réellement
    introuvable — salle ? module ? enseignant ?"""
    if not cause:
        return list(echecs)
    return [(sid, f"{motif} [ids irrésolus : {cause}]") for sid, motif in echecs]


def _consommer_file(
    page: Any, doc: dict[str, Any], *, base: str, production_autorisee: bool, limite: int = 0
) -> BilanDrainage:
    """Draine `file_attente.lister()` et appelle la primitive RPC adaptée à
    chaque job (create/update/delete). Un job traité (succès OU refus de
    garde-fou) est retiré de la file ; un job en échec RPC/réseau y reste
    pour la prochaine nuit — mais REPOUSSÉ EN FIN DE FILE, jamais laissé en
    tête : le cycle est borné et prend les premiers jobs, si bien qu'un
    échec systématique confisquerait la file (cf. `repousser_en_fin`).

    Rend un `BilanDrainage` : ce qui a échoué compte autant que ce qui a
    réussi, et rester muet sur les échecs revient à les cacher."""
    jobs = lister()
    bilan = BilanDrainage(en_attente=len(jobs))
    if not jobs:
        return bilan
    state = get_state()
    entrees = entrees_pour_state(state)
    methodes = charger_methodes(Path(state.config_dir))
    a_retirer: list[dict[str, Any]] = []

    # D'ABORD écarter ce qui vise une semaine que Celcat n'a pas ouverte,
    # ENSUITE borner le cycle : l'ordre inverse ferait des passages entiers
    # vides dès que des différés occupent la tête de file (cf.
    # `_ecarter_semaines_non_posees`).
    jobs = _ecarter_semaines_non_posees(jobs, entrees, bilan)
    if limite > 0:
        # Un cycle BORNÉ. Le premier drainage réel a duré 2h11 sur 489 jobs,
        # session VPN du compte partagé prise du début à la fin et pas une
        # ligne de journal entre-temps. La file étant persistante, ce qui
        # n'est pas fait maintenant se fera au cycle suivant — il n'y a
        # aucune raison de tout tenir en un seul passage.
        jobs = jobs[:limite]

    # Résolutions mises en cache LE TEMPS DE CE CYCLE. Chaque job coûtait
    # sinon six appels RPC (groupe, module, salle, personnel, catégorie,
    # département) : sur 504 jobs, trois mille allers-retours pour une
    # poignée de combinaisons distinctes — d'où des cycles interminables
    # (retour utilisateur 08/09/2026 : « cela prend 2321 ans »).
    # `pousser_manquants_celcat.py` le fait depuis toujours ; le worker,
    # jamais.
    #
    # Pas au-delà du cycle : le catalogue Celcat peut changer entre deux
    # passages (salle ajoutée, module renommé), et écrire avec des
    # identifiants périmés serait bien pire que lent.
    cache_ids: dict[tuple, tuple[dict, str | None]] = {}
    cache_groupes: dict[str, int] = {}

    def _ids_cache(entree: Any) -> tuple[dict, str | None]:
        cle = _cle_ressources(entree)
        if cle not in cache_ids:
            cache_ids[cle] = _ids_pour(page, entree)
        return cache_ids[cle]

    def _groupe_cache(entree: Any, group_id_connu: object) -> int:
        if group_id_connu not in (None, ""):
            return _group_id_pour(page, entree, group_id_connu)
        nom = str(getattr(entree, "nom_groupe_celcat", "") or "")
        if nom not in cache_groupes:
            cache_groupes[nom] = _group_id_pour(page, entree, None)
        return cache_groupes[nom]

    # Créations dont le journal connaît déjà l'event_id : ce sont en réalité
    # des modifications, versées plus bas dans le lot d'updates.
    elements_requalifies: list[ElementModification] = []
    jobs_requalifies: dict[str, dict[str, Any]] = {}
    causes_requalifiees: dict[str, str] = {}

    # --- create : un appel par job, comme les scripts existants (ids/masque
    # ne sont pas garantis homogènes entre deux jobs différents). ---------
    for job in jobs:
        if job.get("action") != "create":
            continue
        sid_job = str(job.get("session_id") or "")
        entree = entrees.get(sid_job)
        if entree is None:
            # Le job restera en file sans jamais pouvoir être traité : le
            # nommer est le minimum, sans quoi il tourne indéfiniment en
            # silence (c'était le cas avant le 07/09/2026).
            bilan.ignores.append((sid_job, "séance inconnue de la maquette"))
            continue
        # Le journal est relu ICI, au moment d'écrire — et non pas seulement
        # au moment d'enfiler, comme le fait `ops.py::_executer`. Entre les
        # deux instants, la séance a pu recevoir un event_id (saisie
        # manuelle, réconciliation du journal) : partir quand même sur une
        # création poserait un SECOND événement à côté du premier. L'écart
        # était théorique tant que la file se vidait en quelques secondes ;
        # il ne l'est plus depuis qu'elle a stagné plusieurs jours.
        journal_actuel = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}
        row_connu = journal_actuel.get(sid_job)
        eid_connu = _event_id(row_connu) if isinstance(row_connu, dict) else None

        group_id = _groupe_cache(entree, job.get("group_id"))
        ids, cause_ids = _ids_cache(entree)
        masque = _masque_pour(entree)

        if eid_connu:
            # L'évènement EXISTE déjà là-bas : c'est une modification, et elle
            # doit emprunter le chemin des modifications.
            #
            # `creer_manquants(..., event_id=N)` semblait faire l'affaire —
            # `charge_utile` pose bien la clé `event_id`. Mais il RECONSTRUIT
            # l'évènement à partir de rien : `"rooms": [{"room_id": 42}]`,
            # sans `dept_id`, `unique_name`, `name` ni `weeks`. Or
            # `modification.py` documente exactement cette forme comme la
            # cause de « Cannot locate a record using only a partial key » —
            # devenu le motif d'échec DOMINANT en production le 08/09/2026,
            # jusqu'à 25 échecs sur 25 dans un cycle.
            #
            # `modifier_manquants` recharge l'évènement COMPLET depuis Celcat
            # puis n'écrase que les champs qui changent : c'est le remède déjà
            # écrit, il suffisait d'y router ces jobs.
            elements_requalifies.append(
                ElementModification(
                    entree=entree,
                    event_id=int(eid_connu),
                    group_id=group_id,
                    ids=ids,
                    masque=masque,
                )
            )
            jobs_requalifies[sid_job] = job
            if cause_ids is not None:
                causes_requalifiees[sid_job] = cause_ids
            continue

        resultat = creer_manquants(
            page,
            [entree],
            group_id=group_id,
            ids=ids,
            masque=masque,
            methode=methodes.methode_ecriture,
            base=base,
            production_autorisee=production_autorisee,
            event_id=0,
        )
        for sid, eid in resultat.crees:
            marquer_saisi(entree, event_id=eid, group_id=group_id)
            a_retirer.append(job)
            bilan.reussis += 1
            # Journalise l'ECRITURE, pas seulement les refus : sans ça, les
            # compteurs et la vue d'activite restent a zero meme quand tout
            # marche (constate le 07/09/2026).
            journaliser(
                kind="created", session_id=sid, event_id=eid,
                course_code=getattr(entree, "course_code", None),
            )
        # L'écriture est tentée même avec des ids incomplets — c'est le
        # comportement voulu, ses propres garde-fous la refuseront. Mais si
        # elle échoue ALORS QUE la résolution avait déjà échoué, le motif
        # rendu (« event_cat_id reçu vide ») est un symptôme : on lui
        # rattache la cause, sans quoi elle est perdue.
        for sid_e, motif_e in _avec_cause(resultat.echecs, cause_ids):
            bilan.echecs.append((sid_e, motif_e))
            journaliser(
                kind="echec", session_id=sid_e, motif=motif_e,
                course_code=getattr(entree, "course_code", None), regrouper=True,
            )

    # --- update : un seul lot, ElementModification porte déjà ses propres
    # ids/masque/group_id (contrairement à creer_manquants). ---------------
    # Les créations requalifiées rejoignent ce lot : elles portent un
    # event_id, donc elles modifient un évènement existant, et le chemin
    # `localiser_evenement` + `fusionner_deltas` est le seul qui envoie un
    # enregistrement COMPLET — le seul que Celcat accepte.
    elements_m: list[ElementModification] = list(elements_requalifies)
    jobs_m: dict[str, dict[str, Any]] = dict(jobs_requalifies)
    # Cause d'une resolution d'ids ratee, par seance : rattachee au motif
    # d'echec plus bas (le lot d'updates est ecrit en une fois).
    causes_m: dict[str, str] = dict(causes_requalifiees)
    for job in jobs:
        if job.get("action") != "update":
            continue
        sid = str(job.get("session_id") or "")
        entree = entrees.get(sid)
        eid = job.get("event_id")
        if entree is None or eid in (None, ""):
            bilan.ignores.append(
                (
                    sid,
                    "séance inconnue de la maquette"
                    if entree is None
                    else "aucun event_id dans le job",
                )
            )
            continue
        ids_m, cause_ids_m = _ids_cache(entree)
        if cause_ids_m is not None:
            causes_m[sid] = cause_ids_m
        group_id = _groupe_cache(entree, job.get("group_id"))
        elements_m.append(
            ElementModification(
                entree=entree,
                event_id=int(eid),
                group_id=group_id,
                ids=ids_m,
                masque=_masque_pour(entree),
            )
        )
        jobs_m[sid] = job
    if elements_m:
        resultat_m = modifier_manquants(
            page,
            elements_m,
            methode=methodes.methode_ecriture,
            base=base,
            production_autorisee=production_autorisee,
        )
        gid_par_session = {el.entree.session_id: el.group_id for el in elements_m}
        for sid, eid in resultat_m.modifiees:
            job = jobs_m.get(sid)
            if job is None:
                continue
            a_retirer.append(job)
            bilan.reussis += 1
            entree = entrees.get(sid)
            if entree is not None:
                marquer_saisi(entree, event_id=eid, group_id=gid_par_session.get(sid))
            journaliser(
                kind="modified", session_id=sid, event_id=eid,
                course_code=getattr(entree, "course_code", None),
            )
        for sid_e, motif_e in resultat_m.echecs:
            cause = causes_m.get(sid_e)
            motif_complet = f"{motif_e} [ids irrésolus : {cause}]" if cause else motif_e
            bilan.echecs.append((sid_e, motif_complet))
            if _evenement_a_disparu(motif_e):
                # L'`event_id` du journal ne désigne plus rien : le garder
                # ferait requalifier la création en modification à CHAQUE
                # passage, et la séance ne serait jamais recréée — une boucle
                # parfaitement stable, avec toutes les apparences du travail.
                # Huit séances y ont tourné le 08/09/2026 au soir, après que
                # leurs évènements ont été supprimés de Celcat.
                marquer_supprime(sid_e)
            journaliser(
                kind="echec", session_id=sid_e, motif=motif_complet,
                course_code=getattr(entrees.get(sid_e), "course_code", None), regrouper=True,
            )

    # --- delete : group_id vient du job (row.get("group_id")), jamais résolu
    # ici — c'est `ops.py` qui le pose à l'enfilage. ------------------------
    elements_s: list[ElementSuppression] = []
    jobs_s: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if job.get("action") != "delete":
            continue
        sid = str(job.get("session_id") or "")
        eid = job.get("event_id")
        gid = job.get("group_id")
        if eid in (None, "") or gid in (None, ""):
            continue
        elements_s.append(ElementSuppression(session_id=sid, event_id=int(eid), group_id=int(gid)))
        jobs_s[sid] = job
    if elements_s:
        resultat_s = supprimer_manquants(
            page,
            elements_s,
            methode=methodes.methode_suppression,
            base=base,
            production_autorisee=production_autorisee,
        )
        for sid in resultat_s.supprimees:
            job = jobs_s.get(sid)
            if job is not None:
                a_retirer.append(job)
                bilan.reussis += 1
                journaliser(
                    kind="deleted", session_id=sid,
                    event_id=int(job.get("event_id") or 0) or None,
                )
        for sid, motif in resultat_s.refusees:
            job = jobs_s.get(sid)
            if job is not None:
                a_retirer.append(job)
            # Refus d'un garde-fou : le job SORT de la file (le retenter
            # donnerait le même refus), mais il n'a rien changé dans Celcat
            # — le compter comme réussi masquerait une suppression qui
            # n'aura jamais lieu.
            bilan.ignores.append((sid, f"suppression refusée : {motif}"))
        # Échec RPC d'une suppression : personne ne le lisait jusqu'ici, si
        # bien qu'une suppression impossible restait en file SANS jamais
        # apparaître au bilan — invisible et immobile, la pire combinaison
        # (trouvé le 08/09/2026 en câblant la rotation).
        for sid, motif in resultat_s.echecs:
            bilan.echecs.append((sid, f"suppression : {motif}"))
            journaliser(kind="echec", session_id=sid, motif=motif, regrouper=True)

    if a_retirer:
        retirer_traites(a_retirer)
    # TOUT ce qui a été examiné sans être retiré repart en fin de file —
    # défini par soustraction plutôt que cas par cas, parce que l'énumération
    # oubliait déjà un cas : « séance inconnue de la maquette » est classée
    # « ignoré » mais RESTE en file, et squattait donc la tête aussi
    # sûrement qu'un échec (vu dans les journaux du 08/09/2026, avec
    # WR303D-S3-TD-2). Par soustraction, tout nouveau cas de ce genre est
    # couvert d'avance.
    #
    # Les jobs différés n'y sont pas : ils ont été écartés AVANT le
    # découpage, donc ils ne consomment pas le budget du cycle et n'ont pas
    # besoin de bouger.
    retires = {cle_job(j) for j in a_retirer}
    a_repousser = [j for j in jobs if cle_job(j) not in retires]
    if a_repousser:
        repousser_en_fin(a_repousser)
    return bilan


def drainer_file_immediate(
    page: Any,
    *,
    base: str = BASE_ENTRAINEMENT,
    production_autorisee: bool = False,
    limite: int = 0,
) -> BilanDrainage:
    """Consomme la file d'attente (create/update/delete) TOUT DE SUITE —
    jamais le balayage par semaine ni le marquage `semaines_lancees`,
    réservés au vrai job de nuit (`executer_job_nuit`). Retour utilisateur
    07/09/2026 : « sur les update on veut tenter en temps réel, pas la
    nuit » — un déplacement de séance déjà placée (`ops.py::_executer`,
    action « update ») s'enfile immédiatement dans la file ; c'est CETTE
    fonction, appelée par le worker à un rythme rapide (cf.
    `deploy/celcat-sidecar/nuit-quotidienne.sh`), qui la vide en quelques
    secondes plutôt qu'à la prochaine bascule de jour.

    Rend un `BilanDrainage`, vrai au sens booléen s'il y avait des jobs en
    attente (donc si la connexion Live valait le coût) — l'appelant qui ne
    veut que cette information n'a rien à changer, celui qui journalise
    dispose enfin du détail des échecs."""
    doc = charger()
    if not doc.get("saisie_active"):
        return BilanDrainage()
    if not lister():
        return BilanDrainage()
    return _consommer_file(
        page, doc, base=base, production_autorisee=production_autorisee, limite=limite
    )


def executer_job_nuit(
    page: Any = None, *, base: str = BASE_ENTRAINEMENT, production_autorisee: bool = False
) -> None:
    from datetime import datetime

    from cal_iut.celcat.etat import sauver, semaines_celcat_passees

    doc = charger()
    if not doc.get("saisie_active"):
        return

    validees = {int(s) for s in (doc.get("semaines_validees") or [])}
    deja_lancees = {int(s) for s in (doc.get("semaines_lancees") or [])}
    passees = set(semaines_celcat_passees())
    semaines = validees - deja_lancees - passees
    state = get_state()
    journal = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}

    # LE BALAYAGE PASSE PAR LA COMPARAISON, jamais par le seul journal.
    #
    # Il enfilait une CRÉATION pour chaque séance dont le journal ignorait
    # l'event_id, sans regarder ce que Celcat contient : 409 créations pour
    # les semaines 1 à 3, quand 60 séances seulement y manquaient (mesuré le
    # 08/09/2026). Les ~350 autres visaient des cours déjà présents — au
    # mieux elles échouent, au pire elles posent un doublon.
    #
    # Demande de l'utilisateur, le même jour : « on veut uniquement modifier
    # ce qui ne va pas », puis « il faut bien fix cela pour les prochaines
    # saisies ». C'est ici que ça se joue : sans ce changement, valider la
    # semaine 4 relancerait les 350 créations aveugles.
    semaines_faites: set[int] = set()
    if semaines:
        releve = lire_instantane()
        if releve.releve_le is None or not releve.evenements:
            # Sans relevé — ou avec un relevé VIDE, qui dit la même chose en
            # ayant l'air de dire autre chose — TOUTES les séances paraissent
            # absentes de Celcat : le balayage créerait un doublon de tout le
            # planning. On n'enfile rien.
            #
            # Et surtout ON NE MARQUE PAS la semaine « lancée » : elle
            # sortirait du balayage pour toujours sans jamais être partie.
            # C'est exactement ce qui est arrivé aux semaines 1, 2 et 3,
            # marquées lancées alors que l'état applicatif du sidecar était
            # vide et qu'aucun job n'avait pu être enfilé.
            journaliser(
                kind="echec",
                session_id="(balayage)",
                motif=(
                    "relevé Celcat absent ou vide : balayage reporté, rien n'est enfilé"
                ),
                regrouper=True,
            )
        else:
            ctx = contexte_comparaison(state)
            lundis = getattr(state.calendar, "teaching_mondays", []) or []
            for semaine in sorted(semaines):
                if not 0 <= semaine < len(lundis):
                    continue
                indice = indice_depuis_lundi(
                    lundis[semaine], premiere_semaine_celcat=PREMIERE_SEMAINE_CELCAT
                )
                for job in jobs_depuis_lignes(
                    lignes_comparaison(
                        state,
                        semaine=semaine,
                        semaine_celcat=indice,
                        evenements=releve.evenements,
                        ctx=ctx,
                    ),
                    semaine=semaine,
                    group_id_pour_nom=_group_id_celcat_depuis_nom,
                ):
                    enfiler(job)
                semaines_faites.add(semaine)

    _scanner_extras(page, doc)

    if page is not None:
        _consommer_file(page, doc, base=base, production_autorisee=production_autorisee)

    doc = charger()
    lancees = {int(s) for s in (doc.get("semaines_lancees") or [])}
    # Seules les semaines RÉELLEMENT balayées sont marquées. Marquer une
    # semaine qu'on n'a pas pu traiter (relevé absent, semaine hors
    # calendrier) la retirerait du balayage définitivement : elle ne
    # partirait jamais, en silence. C'est la panne des semaines 1, 2 et 3,
    # marquées « lancées » sans qu'un seul job ne parte (07/09/2026).
    doc["semaines_lancees"] = sorted(lancees | semaines_faites)
    doc["dernier_job"] = {"lance_le": datetime.now(UTC).isoformat()}
    sauver(doc)
