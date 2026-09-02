# Architect contract — modifier/supprimer séance Celcat (RPC)

goal: pousser vers Celcat les modifications (et suppressions) de séances déjà posées — aujourd'hui la file "update" n'a aucun consommateur et modifier_seance/supprimer_seance sont désactivés.

approach: ne jamais reconstruire un événement Celcat depuis zéro pour un update/delete — toujours recharger l'enregistrement COMPLET par `udlTimetables.load` (le seul chemin qui a marché au canari, event_id 202985) puis n'écraser QUE les champs qui changent, avant `save`. Le pilote clic-glisser (`driver.py`) reste hors-jeu ; tout passe par les primitives RPC de `rpc.py`/`ecriture.py` déjà prouvées pour la création.

rejected: étendre `charge_utile()` avec un champ "manquant" deviné — rejeté : le canari prouve que c'est la DIFFÉRENCE STRUCTURELLE (objet reconstruit vs objet chargé) qui cause "partial key", pas un champ isolé.

## contract

- `EvenementIntrouvable(LookupError)` — event_id absent des `group_ids` interrogés.
- `MethodeSuppressionAbsente(ValueError)` — mirroir de `MethodeEcritureAbsente`, `data/config/celcat_rpc.yaml::methode_suppression` vide.
- `SuppressionRefusee(PermissionError)` — le garde-fou `file_attente.autoriser_suppression` bloque, réévalué sur l'enregistrement FRAIS, jamais sur l'instantané de la file.
- `rpc.py::event_id_retour(resultat: object) -> int | None` — promotion de `ecriture._event_id_retour` (privé aujourd'hui) en helper partagé ; `ecriture.py` l'importe en retour, pas de duplication.
- `rpc.py::supprimer_evenement_rpc(page, charge: object, *, methode: str) -> object` — primitive RPC brute de suppression ; lève `MethodeSuppressionAbsente` si `methode` vide.
- `modification.py::localiser_evenement(page, event_id: int, *, group_ids: list[int]) -> dict` — recharge l'EDT des `group_ids` et renvoie le dict BRUT (pas un `EvenementCelcat` normalisé) porté par `event_id`. Lève `EvenementIntrouvable` sinon. Seul point d'entrée admis avant tout `save` d'update ou de delete.
- `modification.py::fusionner_deltas(brut: dict, *, entree: EntreeCelcat, ids: dict, group_id: int, masque: str) -> dict` — clone `brut` et n'écrase QUE day_of_week/start_time/end_time/weeks/event_cat_id/dept_id/modules/rooms/staff/groups/notes — même jeu de champs que `ecriture.charge_utile`, mais superposé sur l'enregistrement complet plutôt qu'à la place de rien : c'est tout le correctif.
- `modification.py::ElementModification` — dataclass `(entree: EntreeCelcat, event_id: int, group_id: int, ids: dict, masque: str)`.
- `modification.py::ResultatModification` — dataclass `(modifiees: list[tuple[str, int]], echecs: list[tuple[str, str]])`.
- `modification.py::modifier_evenement(page, entree: EntreeCelcat, *, event_id: int, group_id: int, ids: dict, masque: str, methode: str, base: str = BASE_ENTRAINEMENT, production_autorisee: bool = False) -> int` — localise, fusionne, revérifie (`verifier_charge_categorie`, `verifier_avant_envoi`), `enregistrer_evenement`, renvoie l'event_id confirmé. Lève `EvenementIntrouvable` / `CategorieRefusee` / `SemainesNonRestreintes` / `ProductionRefusee` ; n'attrape rien.
- `modification.py::modifier_manquants(page, elements: list[ElementModification], *, methode: str, base: str = BASE_ENTRAINEMENT, production_autorisee: bool = False) -> ResultatModification` — comme `creer_manquants` : un échec isolé n'arrête pas le lot, notifie via `_notifier_celcat`.
- `suppression.py::ElementSuppression` — dataclass `(session_id: str, event_id: int, group_id: int)`.
- `suppression.py::ResultatSuppression` — dataclass `(supprimees: list[str], refusees: list[tuple[str, str]], echecs: list[tuple[str, str]])`.
- `suppression.py::supprimer_evenement(page, event_id: int, *, group_id: int, methode: str, base: str = BASE_ENTRAINEMENT, production_autorisee: bool = False) -> None` — `localiser_evenement` puis `evenement_depuis_rpc` puis `file_attente.autoriser_suppression` ; si refusé → `SuppressionRefusee` ; si `EvenementIntrouvable` → no-op idempotent (aucune levée) ; sinon `verifier_avant_envoi` puis `rpc.supprimer_evenement_rpc`.
- `suppression.py::supprimer_manquants(page, elements: list[ElementSuppression], *, methode: str, base: str = BASE_ENTRAINEMENT, production_autorisee: bool = False) -> ResultatSuppression`.
- `mapping.py::entrees_pour_state(state) -> dict[str, EntreeCelcat]` — même construction que `api/main.py::_entrees_celcat`, indexée par `session_id`.
- `sync.py::marquer_saisi(entree, *, event_id=None, group_id=None) -> None` — persiste aussi `group_id`.
- `file_attente.py::retirer_traites(identites: list[dict]) -> None` — relit le fichier, retire les jobs dont `(action, session_id, event_id)` correspond exactement, réécrit ; jamais un `vider()` global.
- `rpc_config.py::charger_methodes(config_dir: Path) -> RpcConfig` — `RpcConfig(methode_ecriture, methode_suppression)`, remplace `_methode_yaml()` dupliquée dans 2 scripts.
- `nuit.py::executer_job_nuit(page: Any = None, *, base=BASE_ENTRAINEMENT, production_autorisee=False) -> None` — ajoute `_consommer_file(page, doc, *, base, production_autorisee)` exécuté **seulement si `page is not None`** : lit `file_attente.lister()`, résout via `mapping.entrees_pour_state` (create/update) ou `row.get("group_id")` (delete), appelle `creer_manquants`/`modifier_manquants`/`supprimer_manquants`, journalise, puis `retirer_traites` sur les jobs consommés (succès + refus garde-fou ; PAS les échecs réseau/RPC qui restent en file).

## files

- src/cal_iut/celcat/modification.py — create
- src/cal_iut/celcat/suppression.py — create
- src/cal_iut/celcat/rpc_config.py — create
- src/cal_iut/celcat/rpc.py — edit (event_id_retour public, supprimer_evenement_rpc)
- src/cal_iut/celcat/ecriture.py — edit (_event_id_retour → ré-import)
- src/cal_iut/celcat/mapping.py — edit (entrees_pour_state)
- src/cal_iut/celcat/sync.py — edit (marquer_saisi group_id)
- src/cal_iut/celcat/file_attente.py — edit (retirer_traites)
- src/cal_iut/celcat/ops.py — edit (jobs delete portent group_id)
- src/cal_iut/celcat/nuit.py — edit (_consommer_file, executer_job_nuit(page=None,...))
- data/config/celcat_rpc.yaml — edit (ajoute methode_suppression: vide)
- scripts/celcat_nuit.py — edit (ouvre Playwright/VPN/login, passe page/--base/--production)
- scripts/corriger_cm_categories_celcat.py — edit (remplace creer_manquants(event_id=...) par modification.modifier_evenement)
- scripts/pousser_manquants_celcat.py — edit (passe group_id à sync.marquer_saisi)
- tests/test_celcat_modification.py — create (TDD)
- tests/test_celcat_suppression.py — create (TDD)
- tests/test_celcat_nuit.py — edit (_consommer_file)
- tests/test_celcat_ops.py — edit (delete jobs portent group_id)
- docs/CELCAT.md — edit (documente la cause racine)

## acceptance (TDD spec)

- should raise EvenementIntrouvable when localiser_evenement is called with an event_id absent from every loaded group_id
- should return the full raw record (all original keys incl. original_id) when localiser_evenement finds the event_id, not a normalized EvenementCelcat
- should overwrite only day_of_week/start_time/end_time/weeks/event_cat_id/dept_id/modules/rooms/staff/groups/notes when fusionner_deltas runs, leaving every other key from brut untouched
- should send the full merged record (not a synthetic minimal one) to udlTimetables.save when modifier_evenement runs against a FaussePage, event_id of the recorded call equals the one requested
- should raise CategorieRefusee when modifier_evenement would send a CM event without event_cat_id 430
- should raise SemainesNonRestreintes when the merged weeks mask is not exactly one Y
- should raise ProductionRefusee when base is URCA_2026 and production_autorisee is False
- should keep processing remaining elements and record the failure when one ElementModification fails inside modifier_manquants
- should raise MethodeSuppressionAbsente (not call supprimer_evenement_rpc) when methode_suppression is empty
- should raise SuppressionRefusee and not call supprimer_evenement_rpc when the freshly localized event is protected=Y or a fantôme, even if the queued job predates that state
- should treat EvenementIntrouvable during supprimer_evenement as a no-op success (already gone), not an error
- should keep a failed element in refusees (guard) vs echecs (RPC exception) correctly in supprimer_manquants
- should drain create/update/delete jobs from file_attente and call the matching RPC function when executer_job_nuit runs with a page, and do nothing RPC-wise when page is None
- should remove only successfully-processed or guard-refused jobs from the queue after _consommer_file, leaving RPC-failed jobs for the next run
- should persist group_id in the journal row when sync.marquer_saisi is called with one, omit it when not given
- should carry group_id on every enqueued delete job, never silently missing it

Live verification (not unit tests): URCA_FORMATION update run succeeds without "partial key"; then URCA_2026 event_id 1931709/1933218 flip [TP]→[CM], confirmed by a zero-gap audit re-read.

## risks

- Delete RPC method is UNPROVEN (no canari like the update one). `methode_suppression` stays empty until a canari captures it — `supprimer_manquants` must refuse cleanly (MethodeSuppressionAbsente), not guess. Not blocking for update/modify shipping.
- `localiser_evenement` reloads the whole group EDT per job — fine at current volume (few sessions/night).
- Pre-existing "delete" jobs in the queue (from before this change) lack group_id — will need a manual backfill or fallback, out of scope here.

Reuse existing guard rails, don't reimplement: `file_attente.autoriser_suppression`, `categories.verifier_charge_categorie`.

Test house style: reuse `FaussePage` from tests/test_celcat_rpc.py (import it, don't redefine), `tests/celcat_sync_helpers.py` for queue/state helpers, `tests/fixtures/celcat_udl_load.json` for raw load-shaped events. French `test_should_<verb>_when_<condition>` names. `pytest tests/test_celcat_*.py` to run.
