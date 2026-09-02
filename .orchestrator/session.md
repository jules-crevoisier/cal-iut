# Session

goal: pousser vers Celcat les modifications (et suppressions) de séances déjà posées — aujourd'hui la file "update" n'a aucun consommateur et modifier_seance/supprimer_seance sont désactivés.

out_of_scope: UI (aucun écran ne change) ; le pilote navigateur (clic-glisser) reste tel quel — on écrit en RPC direct, même famille que corriger_cm_categories_celcat.py ; nouvelle route API.

users: interne — le job de nuit (executer_job_nuit / sidecar Docker VPN+RPC), pas d'action manuelle attendue au quotidien.

branch: feature/celcat-modifier-seance

locked:
- Corriger la cause racine de EUDLDSError "partial key" (RPC update par event_id échoue faute d'un champ requis dans la charge).
- Écrire un module de résolution+écriture "modifier" côté RPC (comme creer_manquants mais pour update), + son pendant "supprimer" (même cause racine que modifier_seance : localiser l'événement).
- Brancher ce module dans executer_job_nuit() (nuit.py) pour qu'il consomme les jobs "update"/"delete" de celcat_file_attente.json automatiquement, aux côtés des créations.
- Toujours : audit avant écriture, --production requis sur URCA_2026, jamais de suppression d'un jour férié protégé (déjà une règle existante — la respecter).
- Validation obligatoire sur URCA_FORMATION avant toute écriture URCA_2026.
- Une fois validé sur FORMATION : appliquer directement en prod aux 2 CM WR116 bloqués (event_id 1931709, 1933218, [TP] → [CM]) sans repasser par l'utilisateur.

open: none

acceptance:
- Un job "update" en file (event_id connu) est résolu et écrit via RPC sans erreur "partial key", sur URCA_FORMATION d'abord.
- Un job "delete" en file est résolu et supprimé via RPC sans erreur, sur URCA_FORMATION d'abord ; un jour férié protégé sur la même case bloque la suppression avec un message clair (pas de suppression aveugle).
- executer_job_nuit() traite create + update + delete depuis celcat_file_attente.json ; audit-only par défaut, écrit seulement si le mode nuit l'autorise (garder le garde-fou --production existant côté scripts appelants).
- Tests unitaires (page/RPC factices) couvrant : résolution d'un event_id existant, échec propre si l'event_id est introuvable, refus de suppression sur jour férié protégé.
- Après validation FORMATION : les 2 event_id WR116 passent de [TP] à [CM] en prod (URCA_2026), vérifié par une relecture d'audit à 0 écart.
