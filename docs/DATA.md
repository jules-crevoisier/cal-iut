# Données et configuration

Ce document explique où vivent les données de cal-iut et comment les modifier.
Il est pour les techniciens : ceux qui éditent un fichier de configuration ou relancent un calcul.
Il décrit l'état actuel des fichiers, de leurs formats et des règles de placement.
Pour utiliser l'appli, lire plutôt [GUIDE.md](../GUIDE.md). Pour administrer, [ADMIN.md](ADMIN.md).
Ce qui est faisable dans l'appli est signalé : c'est toujours préférable à une modification de fichier.

## Comment lire ce document

- **Vous cherchez un fichier ?** Commencer par le [tableau des fichiers](#les-fichiers-en-un-tableau).
- **Vous avez une tâche précise ?** Aller aux [tâches courantes](#tâches-courantes) : chaque tâche est en étapes.
- **Vous voulez changer une règle ?** Voir [Quel fichier pour quelle règle ?](#quel-fichier-pour-quelle-règle-).
- **Vous voulez le format exact ?** Aller à la [référence par fichier](#référence-par-fichier).
- **Un mot vous échappe ?** Voir le [glossaire](#glossaire).
- **Pourquoi une séance est-elle placée ainsi ?** Voir les [règles de placement](#règles-de-placement-et-contraintes-du-solveur).

Sommaire :

1. [Les données en un coup d'œil](#les-données-en-un-coup-dœil)
2. [Tâches courantes](#tâches-courantes)
3. [Référence par fichier](#référence-par-fichier)
4. [Glossaire](#glossaire)
5. [Règles de placement et contraintes du solveur](#règles-de-placement-et-contraintes-du-solveur)
6. [Pour les techniciens](#pour-les-techniciens)

---

## Les données en un coup d'œil

### Le chemin des données

```
 Sources officielles (tableurs, exports du serveur MMI)
   contraintes_update/        ← déposées à la main ou par « cal-iut refresh --ecrire »
        │
        │  python scripts/build_contraintes.py
        ▼
 contraintes/*.json           ← GÉNÉRÉS : calendrier, SAE, événements, enseignants, maquette
        │
        │  + data/config/*.yaml (règles et corrections tenues à la main)
        │  ingestion (cal-iut ingest, ou le serveur à chaque démarrage)
        ▼
 Séances à placer             ← data/generated/sessions.json (une ligne par séance et par groupe)
        │
        │  cal-iut solve --decomposed …  (le solveur, lancé hors du serveur)
        ▼
 Planning calculé             ← data/generated/timetable.json
        │
        │  cal-iut load-run
        ▼
 Planning en service          ← data/state/cal-iut.db (+ retouches dans data/state/*.json)
        │
        ├──► Appli web (déplacements, créations, « À placer »)
        ├──► Celcat   (file d'attente + worker « celcat-nuit », cf. CELCAT.md)
        ├──► Agendas ICS (cf. ICS.md)
        └──► API v1 et MCP (cf. API.md, MCP.md)
```

Trois idées à retenir :

- **Les sources officielles font foi.** On ne corrige jamais un fichier généré (`contraintes/*.json`).
  On corrige la source, ou on déclare une correction dans `data/config/`.
- **`data/config/` est dans l'image Docker.** Le modifier demande un commit et un redéploiement.
- **`data/state/` est le volume persistant.** L'appli y écrit. Rien n'y est versionné (sauf la base initiale).

### Les fichiers en un tableau

Colonne « Qui » : **main** = édité à la main, **généré** = produit par un script, **appli** = écrit par l'appli.
Colonne « Effet » : ce qu'il faut faire pour qu'une modification compte (détails [plus bas](#quand-une-modification-prend-elle-effet-)).

#### `data/config/` (règles et correspondances, versionnées)

| Fichier | À quoi il sert | Qui | Effet |
|---|---|---|---|
| [`rooms.yaml`](#roomsyaml) | Salles du bâtiment et règles de choix de salle | main | Redéploiement |
| [`groups.yaml`](#groupsyaml) | Groupes (promo, TD, TP) et effectifs par parcours | main | Redéploiement ; peut changer les séances |
| [`teacher_availability.yaml`](#teacher_availabilityyaml) | Indisponibilités et disponibilités d'enseignants, en plus de la feuille officielle | main | Redéploiement ; solveur au prochain calcul |
| [`teacher_duos.yaml`](#teacher_duosyaml) | Paires d'enseignants qui font leurs TP en même temps, en salles jumelles | main | Redéploiement + nouveau calcul |
| [`teacher_contacts.yaml`](#teacher_contactsyaml) | Adresses mail des enseignants | main (+ appli) | Redéploiement |
| [`enseignants_supplementaires.yaml`](#enseignants_supplementairesyaml) | Enseignants absents de la feuille officielle | main (+ appli) | Redéploiement |
| [`additional_courses.yaml`](#additional_coursesyaml) | Cours absents de la maquette officielle | main | Redéploiement ; crée des séances |
| [`course_corrections.yaml`](#course_correctionsyaml) | Remplacer un enseignant sur un cours | main | Redéploiement ; change les séances |
| [`course_scheduling_rules.yaml`](#course_scheduling_rulesyaml) | Bornes de semaines, fenêtres de dates, ordre et répartition des enseignants, dérogations | main | Redéploiement + nouveau calcul |
| [`double_sessions.yaml`](#double_sessionsyaml) | Séances à coller en blocs de 3 h ou 4 h 30 | main | Redéploiement ; change les séances |
| [`seances_annulees.yaml`](#seances_annuleesyaml) | Séances qui n'auront jamais lieu | main | Redéploiement ; séances retirées |
| [`sae_corrections.yaml`](#sae_correctionsyaml) | Ajouter ou retirer des journées SAE | main | Redéploiement + nouveau calcul |
| [`sae_teacher_phases.yaml`](#sae_teacher_phasesyaml) | Quels jours chaque enseignant encadre une SAE | main | Redéploiement + nouveau calcul |
| [`salles_reservees.yaml`](#salles_reserveesyaml) | Salles prises par un tiers (Direction…) | main | Redéploiement ; salles au prochain calcul |
| [`evenements_supplementaires.yaml`](#evenements_supplementairesyaml) | Événements fixes absents du tableur officiel | main | **Rebuild** des contraintes + redéploiement |
| [`celcat.yaml`](#celcatyaml) | Codes Celcat : enseignants, salles, modules, « sans code (voulu) », règles d'envoi | main (+ appli) | Redéploiement |
| [`celcat_modules_maquette.yaml`](#celcat_modules_maquetteyaml) | Codes module Celcat repris de la maquette | généré | Redéploiement |
| [`celcat_groupes.yaml`](#celcat_groupesyaml) | Identifiants Celcat des groupes | main (relevé) | Redéploiement |
| [`celcat_matieres.yaml`](#celcat_matieresyaml) | Identifiants Celcat des matières | main (relevé) | Redéploiement |
| [`celcat_formulaire.yaml`](#celcat_formulaireyaml-et-celcat_rpcyaml) | Libellés du formulaire Celcat | main (relevé) | Redéploiement |
| [`celcat_rpc.yaml`](#celcat_formulaireyaml-et-celcat_rpcyaml) | Méthodes d'écriture Celcat | main (relevé) | Redéploiement |
| [`celcat_occupations.yaml`](#celcat_occupationsyaml) | Occupations hors MMI : salles et enseignants surveillés dans Celcat, période, forçable ou strict, fraîcheur | main | Redéploiement (sidecar et appli) |

#### `data/state/` (volume persistant, écrit par l'appli, jamais versionné sauf la base)

| Fichier | À quoi il sert | Qui | Effet |
|---|---|---|---|
| `cal-iut.db` | Base SQLite : planning en service, comptes, clés API, tâches, historique | appli | Immédiat |
| `custom_rooms.json` | Salles créées dans l'appli, et case « placement auto » de toute salle | appli | Immédiat |
| `custom_sessions.json` | Séances créées dans l'appli (hors maquette) | appli | Immédiat |
| `session_overrides.json` | Retouches d'une séance de maquette (enseignant, type, durée) | appli | Immédiat |
| `references.json` | Mails, noms, prénoms, téléphones, types d'enseignant, intitulés saisis dans l'appli ; intervenants créés dans l'appli | appli | Immédiat |
| `celcat_mappings.json` | Codes Celcat saisis dans l'appli, « sans code (voulu) » de l'appli | appli | Immédiat (worker compris) |
| `forced_pending.json` | Placements forcés hors ordre pédagogique, en attente de validation | appli | Immédiat |
| `celcat_file/` | File d'attente Celcat : un fichier par écriture à faire | appli + worker | Immédiat |
| `celcat_sync.json` | Ce qui a été saisi dans Celcat (signature par séance) | worker | — |
| `celcat_instantane.json`, `celcat_instantane_demande.json` | Relevé de Celcat fait par le worker, et sa demande | worker / appli | — |
| `celcat_occupations_externes.json`, `celcat_occupations_demande.json` | Occupations hors MMI de nos salles et enseignants relevées dans Celcat (cf. [`celcat_occupations.yaml`](#celcat_occupationsyaml)), et la demande « Relire maintenant » | worker / appli | Immédiat (l'appli le relit dès qu'il change) |
| `celcat_drainage.json`, `celcat_logs.json`, `celcat_extras.json` | Trace du dernier passage, journal, cours présents seulement dans Celcat | worker | — |
| `celcat_correction_en_cours.json` | Correction Celcat envoyée, en attente du worker | appli | — |
| `*.lock`, `*.migre`, `celcat_file_attente.json` | Verrous entre conteneurs ; ancienne file mise de côté | technique | Ne pas toucher |
| `notifications.json`, `mail_log.json` | Destinataires des notifications ; mails déjà envoyés | appli | Immédiat |
| `mcp_journal.json` | Journal des modifications faites par MCP | appli | — |
| `blocages.json` | Blocages anti-aspiration (cf. [ANTI-ASPIRATION.md](ANTI-ASPIRATION.md)) | appli | Immédiat |
| `controle_doublons_hebdo.json` | Dernier contrôle hebdomadaire des doublons | appli | — |
| `sauvegardes/`, `sauvegardes_db/` | Sauvegarde quotidienne du planning (JSON) et de la base (30 jours) | appli | — |
| `pieces_jointes/` | Images jointes aux tâches | appli | — |
| `.secret_key` | Clé de signature des sessions | appli | Ne pas toucher |

Les détails de ces fichiers sont dans [ADMIN.md](ADMIN.md) (comptes, sauvegardes) et [CELCAT.md](CELCAT.md) (fichiers `celcat_*`).

#### `contraintes/` (généré, versionné) et `contraintes_update/` (sources)

**Règle d'or : ne jamais modifier `contraintes/` à la main.** Le script le réécrit en entier à partir de `contraintes_update/`.
Les seuls fichiers sources qu'on remplace sont ceux de `contraintes_update/` :

| Fichier source (`contraintes_update/`) | Contenu | D'où il vient |
|---|---|---|
| `maquette.json` | Modules, volumes, enseignants | Serveur MMI (`cal-iut refresh`) |
| `progression.json` | Ordre des séances de chaque module | Serveur MMI (`cal-iut refresh`) |
| `CONTRAINTES ENSEIGNANTS … .csv` | Disponibilités et indisponibilités | Tableur rempli par les enseignants |
| `INDISPONIBILITÉS IUT TROYES … .csv` | Vacances, fériés, fermetures | Direction de l'IUT |
| `DATES SAE … .csv` | Journées de chaque SAE | Responsables de SAE |
| `Dates MMI … .csv` | Rentrées, interventions à heure fixe | Département |
| `DISPONIBILITÉS ÉTUDIANTS BUT2 / BUT3 … .csv` | Semaines à l'IUT des alternants | Service alternance |
| `Maquette 2026 … .docx`, `voeux EDT … .pdf` | Précisions des responsables (lues par un humain) | Équipe pédagogique |

Exports officiels : `https://mmi23x02.mmi-troyes.fr/export/maquette` et `https://mmi23x02.mmi-troyes.fr/export/progression`.

**Périmètre 2026-2027 : S1, S3 et S5 seulement.** Le fichier « DATES SAE » ne date que ces semestres.
Demander `--semestre-group even` (S2, S4, S6) affiche un avertissement : les plannings seraient faits sans aucune journée SAE.
BUT2-DEV-FC est gelé cette année (pas assez d'alternants) : aucun module, donc aucune séance.

Fichiers générés :

| Fichier | À quoi il sert | Lu par l'appli ? |
|---|---|---|
| `contraintes/00_INDEX.md` | Provenance de chaque fichier et arbitrages humains | Non |
| `01_regles_generales.json`, `06_salles.json` | Règles et salles de la conversation préparatoire (non générés) | Non, référence seulement |
| `02_calendrier_iut.json` | Vacances, pauses, jours fériés | **Oui** |
| `03_calendrier_alternance_officiel.json` | Semaines de présence IUT des alternants | **Oui** |
| `05_enseignants_contraintes.json` | Indisponibilités et disponibilités de la feuille officielle | **Oui** |
| `07_modules_maquette_progression.json` | Vue fusionnée maquette + progression | Non (audit) |
| `08_alertes_qualite_donnees.json` | Anomalies détectées dans les sources | Non (à lire) |
| `09_dates_sae.json` | Journées de chaque SAE, module par module | **Oui** |
| `10_dates_fixes.json` | Événements fixes horodatés, avec leur parcours | **Oui** |
| `maquette.json`, `progression.json` | Copies figées des exports officiels | **Oui** (préférées au téléchargement) |

#### Autres dossiers

| Emplacement | Contenu | Versionné ? |
|---|---|---|
| `data/generated/` | Sorties de `cal-iut ingest` et `cal-iut solve` (`sessions.json`, `timetable.json`…) | Non |
| `data/exports/` | Téléchargement brut de `cal-iut fetch` | Non |
| `data/sauvegardes/` | Anciennes versions sauvegardées par `cal-iut refresh --ecrire` | Non ignoré par git : ne pas commiter |
| `data/timetable_odd_fresh.json` | Planning par défaut de `cal-iut load-run` | Oui |

### Quand une modification prend-elle effet ?

| Vous modifiez… | Ce qu'il faut faire |
|---|---|
| Un fichier de `data/config/` | Commit, puis redéploiement (Dokploy). Au démarrage, le serveur relit tout et ré-ingère. En local : relancer `cal-iut serve`. |
| Un fichier `celcat_*.yaml` | Pareil, et redéployer aussi le conteneur `celcat-nuit` (il a sa propre copie). |
| Une règle du solveur (bornes, blocs, duos, SAE) | Elle protège les **déplacements manuels** dès le redémarrage. Elle ne **replace** rien : le planning existant ne change qu'au prochain calcul (`cal-iut solve`, ou « régénérer la semaine »). |
| `evenements_supplementaires.yaml` | Lancer `python scripts/build_contraintes.py`, commiter `contraintes/10_dates_fixes.json`, redéployer. Sans rebuild, **aucun effet**. |
| Une source dans `contraintes_update/` | Lancer `python scripts/build_contraintes.py`, relire le diff de `contraintes/`, commiter, redéployer. |
| Quelque chose dans l'appli | Immédiat. Rien à redéployer. |

> **Attention :** l'identifiant d'une séance contient le code du cours, son type, son numéro et le groupe
> (ex. `WR104-S1-TD-3-but1-td-ab`). Changer un identifiant de groupe, coller des séances en bloc
> ou ajouter une séance au milieu d'une progression change ces identifiants.
> Les anciennes séances placées ne correspondent plus : elles reviennent dans « À placer ».

---

## Tâches courantes

Chaque entrée de fichier porte une trace : **qui l'a demandée et quand** (`motif`, `demande_par`, `le` ou `note`).
Une règle sans raison finit supprimée à tort, ou conservée à tort.

### Quel fichier pour quelle règle ?

Avant de modifier : lancer `cal-iut regles`. Il liste en français les règles actives, leur raison et leur fichier.
Tous les fichiers ci-dessous sont dans `data/config/`. Ce sont des fichiers texte, éditables dans n'importe quel éditeur.

| Vous voulez… | Fichier (section) |
|---|---|
| Changer les groupes ou leurs effectifs | `groups.yaml` |
| Changer les salles ou leurs règles | `rooms.yaml` |
| Bloquer une salle prise par un tiers | `salles_reservees.yaml` |
| Déclarer une indisponibilité d'enseignant hors feuille officielle | `teacher_availability.yaml` |
| Qu'un cours ne commence pas trop tôt / ne finisse pas trop tard | `course_scheduling_rules.yaml` (`min_week_rules`, `max_week_rules`) |
| Imposer une séance à une date ou dans une période | `course_scheduling_rules.yaml` (`session_date_windows`) |
| Faire des cours de 3 h au lieu de 1h30 | `double_sessions.yaml` |
| Alterner deux enseignants sur un module | `course_scheduling_rules.yaml` (`teacher_distribution`) |
| Dire qu'un enseignant intervient au début et l'autre à la fin | `course_scheduling_rules.yaml` (`teacher_order_rules`) |
| Faire placer une SAE par le solveur | `course_scheduling_rules.yaml` (`solver_scheduled_sae`) |
| Dire qui encadre une SAE et quand | `sae_teacher_phases.yaml` |
| Ajouter ou retirer des journées SAE | `sae_corrections.yaml` |
| Autoriser exceptionnellement une semaine plus chargée | `course_scheduling_rules.yaml` (`weekly_cap_exceptions`) |
| Faire co-animer deux enseignants en salles jumelles | `teacher_duos.yaml` |
| Ajouter un événement fixe | `evenements_supplementaires.yaml` (puis rebuild) |
| Supprimer définitivement une séance | `seances_annulees.yaml` |
| Ajouter un cours absent de la maquette | `additional_courses.yaml` |

**Écrire toujours une `note:` (ou un `motif:`) qui dit pourquoi, et qui l'a demandé.**
**Après toute modification, relancer `cal-iut audit`.** Une faute de frappe dans un code de cours ne provoque aucune erreur :
la règle est ignorée en silence. L'audit, lui, la signale.

### Ajouter une salle

**Dans l'appli (salle hors bâtiment, administrateurs) :**

1. Ouvrir la **Vue Promo**, puis la carte d'une séance.
2. Dans la liste des salles, choisir **+ Créer une salle…**.
3. Remplir **Nom de la salle** et **Capacité**.
4. Décocher **Proposée au placement automatique** si la salle ne sert qu'à un usage précis (ex. la BU).
5. Cliquer sur **Créer et utiliser**.

La salle est créée en type `standard`, dans `data/state/custom_rooms.json`. Elle survit aux redéploiements.
Pour l'envoyer à Celcat, saisir son code dans **Référence → Codes Celcat → Salles** (cf. [ADMIN.md](ADMIN.md)).

**Dans le fichier (salle du bâtiment, avec un type et des règles) :**

1. Ajouter une entrée dans `rooms:` de [`rooms.yaml`](#roomsyaml) : `id`, `label`, `capacity`, `room_type`.
2. Si elle doit servir à des cours précis, ajouter une règle dans `room_assignment_rules`.
3. Ajouter son libellé Celcat dans `salles:` de [`celcat.yaml`](#celcatyaml).
4. Commiter, redéployer, lancer `cal-iut audit`.

### Retirer une salle du placement automatique

1. Ouvrir la fiche de la salle (Vue Salle).
2. Décocher **Proposée au placement automatique** (administrateurs).

Elle reste choisissable à la main. Une règle de `rooms.yaml` qui la nomme dans `preferred_room_ids` peut encore la choisir.

### Déclarer une indisponibilité d'enseignant

La **feuille officielle** « CONTRAINTES ENSEIGNANTS » reste la référence. Deux cas :

**L'enseignant a modifié sa ligne dans la feuille officielle :**

1. Déposer le nouvel export CSV dans `contraintes_update/` (même nom de fichier).
2. Lancer `python scripts/build_contraintes.py`.
3. Relire le diff de `contraintes/05_enseignants_contraintes.json`.
4. Lancer `cal-iut audit` : il signale les phrases que le lecteur n'a pas comprises.
5. Commiter et redéployer.

**Indisponibilité ponctuelle ou précision (hors feuille) :**

1. Ouvrir [`teacher_availability.yaml`](#teacher_availabilityyaml).
2. Chercher le trigramme de l'enseignant, ou créer une entrée `- teacher_code: XXX`.
3. Ajouter, selon le cas :
   - une date et des créneaux précis : `forbidden_date_slots` (ex. le 3 septembre, 9h30-12h30) ;
   - un créneau chaque semaine : `forbidden_slots` (ex. jamais avant 9h30) ;
   - « seulement ces créneaux-là » : `allowed_slots`.
4. Ajouter `stricte: true` sur une date si l'appli doit refuser le placement **même avec « Forcer »**.
5. Commiter, redéployer.

Résultat : le glisser-déposer signale l'indisponibilité ; le prochain calcul la respecte.
Une indisponibilité ne déplace pas les séances déjà placées : les repérer dans **À traiter** et les déplacer.

### Bloquer une salle prise par un tiers

1. Ajouter une entrée dans [`salles_reservees.yaml`](#salles_reserveesyaml) : `salle`, `date`, `slots`, `motif`.
2. Commiter, redéployer.

La réservation ne déplace aucun cours. Elle empêche l'attribution automatique de choisir cette salle.
Elle apparaît dans la vue « Salles libres ».

### Ajouter un événement fixe (rentrée, réunion…)

1. Ajouter une entrée dans [`evenements_supplementaires.yaml`](#evenements_supplementairesyaml).
2. Lister dans `parcours` les promotions qui ne doivent pas avoir cours. Liste vide = simple information.
3. Lancer `python scripts/build_contraintes.py`.
4. Vérifier que l'événement apparaît dans `contraintes/10_dates_fixes.json` (`"source": "config"`).
5. Commiter les deux fichiers, redéployer.

> **Attention :** un événement bloque les **étudiants** des parcours listés, pas les **enseignants**.
> Pour libérer un enseignant, ajouter aussi un `forbidden_date_slots` dans `teacher_availability.yaml`.

### Annuler une séance

« Annuler » veut dire : les heures n'auront jamais lieu. C'est différent de **Retirer du planning**
(la séance retourne dans « À placer » et reviendra au prochain calcul).

1. Trouver l'identifiant exact de la séance (ex. `WR303D-S3-CM-1`).
   Il est dans `data/generated/sessions.json` après `cal-iut ingest --semestre-group odd`.
2. Ajouter une entrée dans [`seances_annulees.yaml`](#seances_annuleesyaml) avec `session_id`, `motif`, `demande_par`, `le`.
3. Commiter, redéployer.

La séance disparaît dès l'ingestion : du planning, de « À placer » et du solveur.
Pour la faire revenir, retirer l'entrée.
Une séance **créée dans l'appli** se supprime directement : bouton **Supprimer cette séance** sur sa carte (Vue Promo).

### Corriger les journées d'une SAE

**Les dates officielles changent :** mettre à jour le CSV « DATES SAE » dans `contraintes_update/`,
puis `python scripts/build_contraintes.py`.

**Correction locale (le tableur n'est pas à jour) :**

1. Ouvrir [`sae_corrections.yaml`](#sae_correctionsyaml).
2. Mettre dans `ajouter` les journées à **réserver** à la SAE (plus de cours classiques ces jours-là).
3. Mettre dans `retirer` les journées à **rendre** aux cours classiques.
4. Remplir `motif`, `demande_par`, `le`. Commiter, redéployer.

**Préciser qui encadre quand :** [`sae_teacher_phases.yaml`](#sae_teacher_phasesyaml).
Par défaut, tout enseignant d'une SAE est pris sur **tous** ses jours.
Une phase restreint ses jours, et libère donc ses autres créneaux.

Les séances déjà placées sur une journée nouvellement réservée apparaissent dans **À traiter**.

### Ajouter un intervenant

**Dans l'appli (administrateurs) — recommandé :**

1. Cliquer sur **Nouvel intervenant** (Vue Enseignant, **Référence → Enseignants & vacataires**,
   ou **Référence → Codes Celcat → Enseignants**).
2. Saisir nom, trigramme, code Celcat, mail, et au besoin téléphone et type.

Il est enregistré dans `data/state/references.json` ; son code Celcat dans `data/state/celcat_mappings.json`.
Procédure complète : [ADMIN.md](ADMIN.md) et [GUIDE.md](../GUIDE.md).

**Dans les fichiers :**

1. Ajouter une entrée dans [`enseignants_supplementaires.yaml`](#enseignants_supplementairesyaml) (nom, date, demandeur).
2. Ajouter son code Celcat dans `enseignants:` de [`celcat.yaml`](#celcatyaml). Le champ `code_celcat` du premier fichier n'est **pas lu**.
3. Ajouter son mail dans [`teacher_contacts.yaml`](#teacher_contactsyaml).
4. Commiter, redéployer.

Dès que l'enseignant figure dans la feuille officielle, c'est le nom de la feuille qui s'affiche.

### Corriger l'enseignant d'un cours

- **Pour une séance :** dans l'appli, modifier la séance (crayon sur la carte, Vue Promo). La retouche va dans `session_overrides.json`.
- **Pour tout un cours, la maquette officielle se trompe :** ajouter une entrée dans [`course_corrections.yaml`](#course_correctionsyaml).
  Le mieux reste de faire corriger la maquette à la source.
- **Changer la répartition entre enseignants** (alterner, garder par groupes) :
  `teacher_distribution` dans [`course_scheduling_rules.yaml`](#course_scheduling_rulesyaml).

### Coller des séances en blocs de 3 h

1. Ajouter une règle dans [`double_sessions.yaml`](#double_sessionsyaml) : `course_code`, `session_type`, `slots_per_session`.
2. Choisir `pair_from: end` pour ne coller que les dernières séances, et `max_blocks` pour limiter le nombre de blocs.
3. Commiter, redéployer, **relancer un calcul** : les identifiants des séances changent.

### Imposer une période à un cours ou à une séance

Dans [`course_scheduling_rules.yaml`](#course_scheduling_rulesyaml) :

| Besoin | Section |
|---|---|
| Un cours ne commence pas avant la semaine X | `min_week_rules` |
| Un cours se termine avant la semaine X | `max_week_rules` |
| Une séance précise entre deux dates, ou à certaines dates | `session_date_windows` |
| Un enseignant intervient plutôt avant l'autre dans le module | `teacher_order_rules` |
| Une SAE sans date doit quand même être placée par le solveur | `solver_scheduled_sae` |
| Autoriser une semaine plus chargée pour une promo | `weekly_cap_exceptions` |

Les semaines sont des **index** (cf. [le tableau des semaines](#index-de-semaine-et-semaine-n)), les dates sont au format `AAAA-MM-JJ`.

### Déclarer un code Celcat

**Dans l'appli (administrateurs) :** **Référence → Codes Celcat**, choisir la famille (Cours, Salles, Enseignants),
puis **Saisir** sur la ligne « manquant ». Voir [ADMIN.md](ADMIN.md).
Un code connu (fichier, maquette) est verrouillé : il ne se modifie pas dans l'appli.

**Dans le fichier :** ajouter la ligne dans la section voulue de [`celcat.yaml`](#celcatyaml)
(`enseignants`, `salles` ou `modules`). Le fichier l'emporte sur la maquette.
Pour un nouveau **groupe** ou une nouvelle **matière** Celcat, il faut aussi son identifiant numérique
dans `celcat_groupes.yaml` ou `celcat_matieres.yaml` (relevé dans Celcat, cf. [CELCAT.md](CELCAT.md)).

### Marquer « sans code (voulu) »

Pour une entité qu'on n'envoie **jamais** à Celcat (projet enseignants, ligne administrative, code inventé).

- **Dans l'appli :** **Référence → Codes Celcat**, bouton **Sans code (voulu)…**, motif obligatoire, **Marquer**.
- **Dans le fichier :** ajouter `CODE: "motif"` dans `sans_code_voulu:` de [`celcat.yaml`](#celcatyaml).
  Ce marquage-là ne se retire qu'en éditant le fichier (l'appli l'indique : « se retire dans celcat.yaml »).

L'entité n'apparaît plus comme « manquant » ni comme blocage. Le plan Celcat la compte « non envoyée (voulu) ».

### Envoyer avec une règle d'envoi

Pour des séances qui doivent partir dans Celcat avec une catégorie, une remarque et un département **imposés**.
Exemples : WR100BU (visite de la BU, code inventé, sans matière Celcat) ; toutes les séances de type PTUT.

Section `regles_envoi:` de [`celcat.yaml`](#celcatyaml), par **cours** ou par **type** de séance :

```yaml
regles_envoi:
  cours:
    WR100BU:
      enseignants: [VMA]       # seules ces interventions partent ; absent = toutes
      module: aucun            # aucune matière, jamais cherchée
      categorie: "TD0"         # nom exact de la catégorie d'évènement Celcat
      remarque: "WR100BU"      # écrit dans « Remarques » de l'évènement
      departement: "T_MMI T29" # nom exact du département Celcat (défaut : T_MMI T29)
      motif: "Visite de la BU (Kyllian Bresson, 01/10/2026)"
  types:
    PTUT:
      module: cours            # la matière du cours si son code est connu, sinon aucune
      categorie: "Projet"
      remarque: "PTUT"
      motif: "Séances PTUT (Kyllian Bresson, 01/10/2026)"
```

- `module` est **obligatoire** : `aucun` (jamais de matière) ou `cours` (celle du cours, cherchée comme d'habitude ;
  aucune si le cours n'a pas de code). Jamais une matière au nom de la règle.
- `categorie` est obligatoire. Elle et le département sont cherchés **par leur nom** dans Celcat ; introuvables : séance bloquée.
- La pondération (0 pour TD0 et Projet) est portée par la catégorie : rien d'autre à écrire.
- La salle, le groupe et l'enseignant restent ceux de la séance.
- Une séance d'un enseignant hors `enseignants` n'est pas envoyée (motif affiché dans le plan Celcat).
- Priorité : règle du **cours**, puis règle du **type**. Une règle passe devant `sans_code_voulu`.
- Refusé au chargement : un cours à la fois dans `regles_envoi.cours` et `sans_code_voulu`,
  un cours `module: aucun` qui a un code dans `modules`, un type inconnu (CM, TD, TP, PTUT), un champ inconnu.
- Pour arrêter : retirer le bloc, redéployer.
- Avant d'activer en production : essayer avec `cal-iut celcat-essai-regle` ([CELCAT.md](CELCAT.md#5-règles-denvoi--wr100bu-et-ptut)).

### Confirmer un code « à confirmer »

Un cours listé dans `codes_a_confirmer:` de [`celcat.yaml`](#celcatyaml) reste « manquant » exprès,
même si la maquette propose un code. Aujourd'hui : WS103, WS104, WS105.

1. Faire confirmer le code par l'équipe pédagogique.
2. Soit le saisir dans l'appli (**Saisir** ; le code de la maquette est proposé en premier).
3. Soit l'ajouter dans `modules:` de `celcat.yaml` **et** retirer la ligne de `codes_a_confirmer:`.
4. Dans le second cas, lancer `python scripts/generer_codes_maquette.py` pour mettre à jour la section `exclus`,
   relire le diff (ces codes servent à la paie), commiter, redéployer.

### Mettre à jour la maquette et la progression

1. `cal-iut refresh` : télécharge les exports du serveur MMI et **montre ce qui change**, sans rien écrire.
2. `cal-iut refresh --ecrire` : écrit dans `contraintes_update/` (l'ancienne version va dans `data/sauvegardes/`).
3. `python scripts/build_contraintes.py` : régénère `contraintes/`.
4. Si des codes de cours ont changé : `python scripts/generer_codes_maquette.py`.
5. `cal-iut audit`, puis commit et redéploiement.

Sans réseau : `cal-iut refresh --depuis <dossier>` avec des fichiers reçus par mail.
`cal-iut doctor` dit à tout moment quelle commande lancer ensuite.

---

## Référence par fichier

Conventions communes :

- **Jour :** `0` = lundi … `4` = vendredi.
- **Créneau (slot) :** `0` = 8h-9h30, `1` = 9h30-11h, `2` = 11h-12h30, `3` = 14h-15h30, `4` = 15h30-17h, `5` = 17h-18h30.
- **Semaine :** index du solveur (`0` = semaine du 31 août 2026), cf. [tableau](#index-de-semaine-et-semaine-n).
- **Date :** ISO, `AAAA-MM-JJ`.
- **Trigramme :** code enseignant de la maquette (ex. `KBR`).
- **Identifiant de salle :** l'`id` de `rooms.yaml` (ex. `h018`), pas le libellé (`H.018`).

### Sources officielles et fichiers générés

`scripts/build_contraintes.py` est le **seul** point d'entrée. Il lit `contraintes_update/` et réécrit `contraintes/`.
Les décisions humaines qui ne se déduisent d'aucun fichier sont des constantes nommées de ce script :

| Constante | Contenu |
|---|---|
| `_DISPOS_EXCLUSIVES` | Enseignants dont les disponibilités sont une liste blanche dure (MNI, VBU, KNG, EHU) |
| `_EXTRA_INDISPO_TOKENS`, `_REFINED_DISPO_TOKENS` | Précisions sur des phrases de la feuille enseignants |
| `_PARITY_RULES` | Règles semaines paires / impaires (TCA) |
| `_MONTHLY_CLUSTERING` | Regroupement mensuel (ARA, JHU : 2 semaines par mois) |
| `_SAE_MANUAL_WINDOWS` | Fenêtres SAE fixées à la main |
| `_CANCELLED_FIXED_EVENTS` | Événements officiels annulés (ex. VSS du 17/09/2026) |
| `_ARBITRAGES` | Liste sourcée de tous les arbitrages |

La liste des arbitrages est aussi dans [`contraintes/00_INDEX.md`](../contraintes/00_INDEX.md).

#### `05_enseignants_contraintes.json`

Une entrée par enseignant de la feuille officielle. Extrait réel :

```json
{"nom_complet": "Thomas Pavie", "trigramme": "TPA",
 "indisponibilites_raw": "vendredi après-midi",
 "indisponibilites_tokens": [{"raw": "vendredi après-midi", "type": "recurrent_hebdomadaire",
                              "jour": "vendredi", "moment": "apres_midi"}],
 "disponibilites_raw": null, "disponibilites_tokens": [], "disponibilites_exclusives": false}
```

| Champ | Sens |
|---|---|
| `indisponibilites_tokens[].type` | `recurrent_hebdomadaire` (chaque semaine), `date_specifique`, `autre_a_interpreter` |
| `moment` | `matin` (créneaux 0-2), `apres_midi` (3-5), `toute_la_journee`, `apres_17h` (créneau 5), `plage_horaire_precisee_dans_raw` |
| `disponibilites_exclusives` | `true` : hors des disponibilités déclarées, l'enseignant n'est pas plaçable |
| `regles_parite_semaine` | Retraits de créneaux une semaine sur deux |
| `regroupement_mensuel_max_semaines` | Objectif : au plus N semaines de cours par mois |

Pièges :

- **Rien n'est deviné.** Une phrase non comprise est ignorée et listée par `cal-iut audit` (`unresolved_tokens`).
  Elle ne s'applique pas du tout : c'est la première chose à regarder après une mise à jour du CSV.
- Une phrase répétée (« mardi après-midi - mardi ») donne **deux** indisponibilités, la seconde sur tout le mardi.
  Pour annuler un blocage faux venu de la feuille : `cancelled_forbidden_slots` dans `teacher_availability.yaml`.

Formulations bien comprises dans la feuille des enseignants :

| Écrit dans la case | Compris comme |
|---|---|
| `vendredi après-midi` | Tous les vendredis, 14h-18h30 |
| `lundi toute la journée` | Tous les lundis |
| `jeudi 12 novembre 2026` | Cette seule date |
| `du lundi 2 au vendredi 6 novembre 2026` | Toute la plage (le mois de fin vaut pour le début) |
| `les jeudis après 17h00` | Tous les jeudis, créneau 17h-18h30 |
| `mardi de 15h30 à 18h30` | Tous les mardis, créneaux qui chevauchent 15h30-18h30 |

À éviter :

- Les dates en chiffres (`23/09/26`) sont comprises, mais le mois en toutes lettres reste plus sûr.
- « Si possible », « idéalement » : gardé comme note, **ne contraint rien**. Un vrai impératif s'écrit comme une indisponibilité.
- Plusieurs idées dans une case : les séparer par ` - `.

#### `09_dates_sae.json`

Une entrée par SAE : `code_matiere`, `semestre`, `parcours_source`, `lead`, `autres_enseignants`,
`fenetres` (liste de `{debut, fin, dates}`), éventuellement `groupes_td` et `dates_indeterminees`.

Règles :

- Chaque date listée est une **journée entière** réservée à la SAE pour le parcours du module.
- Avec `groupes_td` (ex. `["AB"]`), seuls ces TD, leurs TP, et la promo si c'est l'unique TD, sont bloqués.
- Les enseignants listés (`lead` + `autres_enseignants`) sont réputés pris ces jours-là, sur **tous** les parcours.
- Seuls S1, S3 et S5 sont datés pour 2026-2027. S2, S4 et S6 sont **hors périmètre** : un avertissement s'affiche.
- Correction locale : [`sae_corrections.yaml`](#sae_correctionsyaml).

#### `10_dates_fixes.json`

```json
{"date": "2026-08-31", "debut": "14h00", "fin": "15h30", "salle": "H.018",
 "parcours": ["BUT3-DEV-FC"], "motif": "Rentrée"}
```

- Les créneaux qui chevauchent `debut`-`fin` sont bloqués pour les cours classiques des **seuls** parcours listés.
- `parcours: []` : information seulement, rien n'est bloqué.
- Une « Rentrée » d'un parcours FC bloque aussi **tout ce qui précède** pour ce parcours.
- Un horaire entre 12h30 et 14h ne bloque rien (aucun créneau à cette heure).
- `a_fixer` : dates encore inconnues. `annules` : événements retirés par arbitrage.
- Contient aussi les entrées de [`evenements_supplementaires.yaml`](#evenements_supplementairesyaml) (`"source": "config"`).

#### `02_calendrier_iut.json` et `03_calendrier_alternance_officiel.json`

- `02` : `vacances_et_pauses_pedagogiques` (plages), `jours_feries`, `jalons_et_evenements`.
  Le code ajoute en plus le 1er et le 8 mai 2027, absents de la source.
- `03` : pour `BUT2_FC_S3_S4` et `BUT3_FC_S5_S6`, les semaines où les alternants sont **à l'IUT**.
  Une fermeture de l'IUT l'emporte toujours ; les conflits sont listés dans `08_alertes_qualite_donnees.json`.

#### `maquette.json` et `progression.json`

Copies figées des exports `https://mmi23x02.mmi-troyes.fr/export/maquette` et `…/progression`.
L'ingestion les préfère au téléchargement : le résultat ne dépend pas du réseau.

- **Maquette :** un cours par `(code_matiere, semestre, parcours)`, avec `lead`, `profs` (blocs d'enseignants),
  volumes `cm`/`td`/`tp` et `groupes` (`td`, `tp`).
- **Progression :** `progression.seances` = l'ordre exact des séances (`ordre`, `type`, `eval`),
  et `ordonnancement` = les liens avec d'autres cours (`before`, `after`, `same`).
- Les volumes comptent des **séances de 1h30**, pas des heures.
- Sans progression définie, l'ordre est CM, puis TD, puis TP.
- Un cours du parcours `admin` ou marqué `hors_service` ne produit aucune séance.
- Préfixes de code : `WR` ressource, `WRA` ressource alternants, `WS` SAE, `WSA` SAE alternants.
- Deux blocs d'enseignants différents (`block1`, `block2`) = partage du **contenu** : chacun fait sa partie avec tous les groupes.
  Exceptions déclarées dans `teacher_distribution` (`mode: par_groupes`).

---

### `rooms.yaml`

Les salles et les règles de choix de salle. Le solveur place les séances **sans** regarder les salles.
Les salles sont attribuées **après**, par ces règles.

Exemple réel :

```yaml
rooms:
  - id: h005
    label: H.005
    capacity: 15
    room_type: tp_standard
    equipment: [ilots, bar_chaises_hautes, televiseur]
  - id: h007_h008
    label: H.007-008
    capacity: 30
    room_type: combined
    combines: [h007, h008]
room_assignment_rules:
  - session_types: [CM]
    preferred_room_types: [amphi]
    fallback_room_types: [standard]
    same_room_for_course: true
```

Champs d'une salle :

| Champ | Type | Obligatoire | Sens |
|---|---|---|---|
| `id` | texte | oui | Identifiant, utilisé partout (réservations, duos, Celcat) |
| `label` | texte | oui | Libellé affiché |
| `capacity` | entier | oui | Places |
| `room_type` | type | oui | Voir la liste ci-dessous |
| `equipment` | liste | non | Informatif |
| `combines` | liste d'`id` | non | Salle « fusion » : l'occuper bloque ses moitiés, et inversement |
| `placement_auto` | booléen | non (défaut `true`) | `false` : jamais choisie automatiquement, toujours à la main |

Types de salle : `amphi`, `standard`, `tp_standard`, `td_design`, `tp_mac`, `studio_av`, `tp_anglais`,
`tp_vr_reseaux`, `evaluation`, `combined`, `reserve`. (`labo_dev` et `studio_crea` sont d'anciens types conservés.)

Salles déclarées :

| id | Libellé | Places | Type |
|---|---|---|---|
| h005, h006, h007, h008 | H.005 … H.008 | 15 | tp_standard |
| h007_h008 | H.007-008 | 30 | combined |
| h009 | H.009 (Design) | 30 | td_design |
| h016 | H.016 (Salle Mac) | 24 | tp_mac |
| h017 / h022 | H.017 (Studio) / H.022 (fantôme Studio) | 20 / 16 | studio_av |
| h018 | H.018 (Amphi MMI) | 150 | amphi |
| h101, h104, h105, h111, h201, h203 | H.1xx, H.201, H.203 | 35 | standard |
| h103 | H.103 (Anglais) | 36 | tp_anglais |
| h201_h203 | H.201-203 | 70 | combined |
| h205 | H.205 (VR/Réseaux) | 35 | tp_vr_reseaux |
| a018 | A.018 | 150 | evaluation |

H.001 (BDE) est volontairement absente.

Champs d'une règle (`room_assignment_rules`) :

| Champ | Sens |
|---|---|
| `session_types` | `CM`, `TD`, `TP` ; vide = tous |
| `course_code_patterns` | Motifs de code (`WR108`, `WRA1*`, `*D`) ; vide = tous |
| `is_eval` | `true` = seulement les évaluations |
| `preferred_room_types` | Types essayés d'abord, dans l'ordre |
| `fallback_room_types` | Types de repli, dans l'ordre |
| `preferred_room_ids` | Salles nommées, autorisées même si `placement_auto: false` |
| `same_room_for_course` | Les CM d'un même cours gardent la même salle si elle est libre |

Comment une salle est choisie :

1. La **dernière** règle qui correspond l'emporte. Règles générales en haut, règles de cours en dessous, évaluations en dernier.
2. Parmi les salles libres et assez grandes : le type préféré d'abord, puis la **plus petite** qui convient.
3. Un cours sur plusieurs créneaux qui se suivent (même cours, groupe, enseignant) garde la même salle.
4. Un TD ou TP sans salle assez grande prend la plus grande salle libre. Le contrôle « capacité » le signale.
5. Un CM sans amphi libre reste **sans salle** : l'équipe la complète à la main.
6. Les TP d'un duo prennent leurs salles jumelles (cf. [`teacher_duos.yaml`](#teacher_duosyaml)).

Pièges :

- Une évaluation **préfère** A.018 (règle `is_eval: true`), avec repli amphi puis standard. Ce n'est pas garanti.
- Le solveur ignore les salles : deux CM (BUT1, 120 étudiants ; BUT2-DEV-FI, 56) peuvent tomber à la même heure
  alors qu'un seul amphi les contient. `cal-iut audit` le signale (`capacite.salles_rares`).
- Le motif `*D` attrape tout code finissant par D, SAE comprises.
- Une salle créée dans l'appli n'a pas de règle dédiée : elle est choisie par type (`standard`).

### `groups.yaml`

Les groupes d'étudiants de chaque parcours. Exemple réel :

```yaml
promotions:
  BUT2-CREACOM-FC:
    td_groups:
      - { id: but2-creacom-fc-td-gh, label: TD GH, tp_groups: [G], headcount: 18 }
    tp_groups:
      - { id: but2-creacom-fc-tp-g, label: TP G, headcount: 18 }
    promo_group:
      id: but2-creacom-fc-promo
      label: Promo BUT2 CREACOM-FC
      headcount: 18
```

| Champ | Type | Obligatoire | Sens |
|---|---|---|---|
| clé de parcours | texte | oui | `BUT1`, `BUT2-DEV-FI`… ; l'année est avant le premier tiret |
| `td_groups[]` | liste | oui | `id`, `label`, `tp_groups` (lettres des TP), `headcount` (défaut 30) |
| `tp_groups[]` | liste | oui | `id`, `label`, `headcount` (défaut 30) |
| `promo_group` | objet | **oui** | Groupe des CM : `id`, `label`, `headcount` (défaut 240) |

Structure actuelle :

| Parcours | Promo | TD | TP |
|---|---|---|---|
| BUT1 | 120 | AB, CD, EF, GH (30) | A à H (15) |
| BUT2-DEV-FI | 56 | AB, CD (28) | A à D (14) |
| BUT2-CREACOM-FC | 18 | GH (18) | G, groupe unique |
| BUT3-DEV-FI | 25 | AB (25) | A (13), B (12) |
| BUT3-DEV-FC | 10 | EF (10) | E, groupe unique |
| BUT3-CREACOM-FC | 19 | GH (19) | G, groupe unique |

BUT2-DEV-FC est gelé pour 2026-2027 (aucun module) ; sa structure est en commentaire.

Pièges :

- **Sans `promo_group`**, les CM ne sont rattachés à aucune cohorte : leurs chevauchements avec TD et TP ne sont plus vus.
- Quand la maquette dit N groupes TD, ce sont les **N premiers** `td_groups` déclarés qui reçoivent les séances. L'ordre compte.
- **Groupe unique** (1 TD et 1 TP dans la maquette) : les TP sont émis en TD sur le groupe TD. Le groupe TP reste déclaré
  (il sert au plafond hebdomadaire) mais n'est pas affiché.
- `headcount` décide des salles possibles : 15 places exactement pour H.005. Mettre 19 exclut les petites salles.
- L'`id` d'un groupe entre dans l'identifiant des séances : ne pas le renommer en cours d'année.

### `teacher_availability.yaml`

Ce qui complète ou corrige la feuille officielle des enseignants. Les deux sources sont **fusionnées**.

Exemple réel :

```yaml
teachers:
  - teacher_code: KBR
    forbidden_slots: [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]]
    notes: "Ne débute ses cours qu'à partir de 9h30."
  - teacher_code: FLI
    forbidden_date_slots:
      - date: "2026-09-03"
        slots: [1, 2]
        note: "Pré-rentrée BUT2 FC alternants 9h30-12h30"
```

| Champ | Type | Sens | Effet |
|---|---|---|---|
| `teacher_code` | trigramme | Enseignant visé | — |
| `forbidden_slots` | `[[jour, créneau]]` | Interdit chaque semaine | Dur |
| `forbidden_date_slots` | liste de `{date, slots, note, stricte}` | Interdit à une date et des créneaux | Dur |
| `stricte` | booléen | Refusé en placement manuel **même en forçant** | Appli |
| `allowed_slots` | `[[jour, créneau]]` | Liste blanche : seuls ces créneaux | Dur |
| `allowed_dates` | liste de dates | Liste blanche : seuls ces jours de l'année | Dur |
| `cancelled_forbidden_slots` | `[[jour, créneau]]` | Annule un blocage **faux** venu de la feuille officielle | — |
| `week_parity_rules` | liste de `{parity, day, slots}` | Retire des créneaux les semaines `paire` ou `impaire` | Dur |
| `parity_reference` | `departement` ou `iso` | Numéro de semaine utilisé pour la parité (défaut : département) | — |
| `monthly_cluster_max_weeks` | entier | Au plus N semaines de cours par mois | Mou |
| `preferred_days`, `preferred_slots`, `max_afternoons_per_week`, `notes` | — | Informatifs : **non utilisés** par le solveur | — |
| `objective_weights` (racine) | table | Seul `gap_penalty` est lu (poids des trous, calcul CLI/API) | — |

Règles de fusion avec la feuille officielle :

- Créneaux interdits : **union** des deux sources, moins `cancelled_forbidden_slots`.
- Listes blanches : **intersection** si les deux en ont une, sinon celle qui existe.
- Dates interdites : additionnées.
- Les jours d'encadrement de SAE s'ajoutent ensuite (cf. [`sae_teacher_phases.yaml`](#sae_teacher_phasesyaml)).

Pièges :

- Une entrée ne peut que **restreindre**. Pour lever un blocage de la feuille, utiliser `cancelled_forbidden_slots`.
- `week_parity_rules` ne fait que retirer. « Disponible le jeudi les semaines paires seulement » s'écrit :
  jeudi dans `allowed_slots`, **et** une règle `impaire` qui retire le jeudi.
- Un bloc de 3 h ne peut pas commencer sur le dernier créneau autorisé.
- Le solveur traite toute indisponibilité comme dure. En placement manuel, elle se **force** (l'enseignant a accepté),
  sauf `stricte: true`.

### `teacher_duos.yaml`

Deux enseignants qui font leurs TP **en même temps**, chacun dans une salle d'une paire jumelle.
Celcat n'accepte qu'un enseignant par salle : d'où deux salles collées (« hack Celcat »).

```yaml
duos:
  - teacher_codes: [KBR, KNG]
    course_codes: [WR110]
    rare_rooms: [h017, h022]
    group_overrides:
      KBR: [A, C]
      KNG: [B, D]
```

| Champ | Type | Obligatoire | Sens |
|---|---|---|---|
| `teacher_codes` | 2 trigrammes | oui | Le duo (une entrée à 3 codes est ignorée) |
| `course_codes` | liste | oui | Cours concernés |
| `rare_rooms` | 2 `id` de salle | non (défaut `h017`, `h022`) | La paire de salles jumelles |
| `group_overrides` | trigramme → lettres de TP | non | Force quels groupes TP a chaque enseignant |
| `note` | texte | non | Raison |

Duos actuels : WR110 au Studio (H.017/H.022) ; WR112 et WR113 en H.201/H.203 et H.007/H.008.

Pièges :

- Seuls les **TP** sont synchronisés. Un champ `session_types` dans le fichier n'est pas lu.
- Deux duos sur la **même** paire de salles ne se chevauchent jamais ; sur des paires différentes, ils sont indépendants.
- Déplacer à la main une moitié de duo casse la synchronisation : l'appli le signale (forçable) et conseille de régénérer la semaine.
- `group_overrides` sert à obtenir des épisodes lisibles (« A et B » ensemble, puis « C et D »).

### `teacher_contacts.yaml`

```yaml
contacts:
  KBR: kyllian.bresson@univ-reims.fr
```

Trigramme → adresse. Aucun fichier officiel ne porte les mails : ce fichier est tenu à la main.
Une adresse saisie **dans l'appli** (annuaire, fiche enseignant) a le dernier mot ; elle est marquée « modifiée dans l'appli ».
Sans adresse, le bouton d'écriture ouvre quand même le brouillon, destinataire vide.
En bas du fichier : les adresses non rapprochées, à trancher à la main.

### `enseignants_supplementaires.yaml`

Enseignants que la feuille officielle ne connaît pas encore (arrivée en cours d'année).
Sans eux, un enseignant sans séance n'apparaît pas dans « Nouvelle séance ».

```yaml
APH:
  nom: "Alexia Petit-Halajko"
  ajoute_le: "2026-09-22"
  demande_par: "Jules Crevoisier"
  code_celcat: "40584"
```

- Seul `nom` est lu. `code_celcat` est un rappel : le vrai code va dans `celcat.yaml`.
- Ordre de priorité pour le nom : feuille officielle > ce fichier > intervenant créé dans l'appli.
  Un nom corrigé dans l'appli passe devant tout.

### Prénom, nom, type et téléphone d'un enseignant

Onglet **Référence → Enseignants & vacataires**. Une seule source, pas de nouveau fichier :

| Donnée | D'où vient la valeur | Où va une saisie |
|---|---|---|
| Liste des enseignants | Celle de l'annuaire : feuille des contraintes, maquette, [`enseignants_supplementaires.yaml`](#enseignants_supplementairesyaml), intervenants créés | — |
| Diminutif | Le trigramme (KBR) | Ne se modifie pas |
| Prénom, Nom | Tirés du nom complet affiché (règle ci-dessous) | `references.json` : `prenom`, `nom_famille` |
| Mail | [`teacher_contacts.yaml`](#teacher_contactsyaml) | `references.json` : `email` |
| Type | Aucun fichier : « à préciser » | `references.json` : `type` (`enseignant` ou `vacataire`) |
| Téléphone | Aucun fichier : vide | `references.json` : `telephone` (format `+33612345678`) |
| Code Celcat | [`celcat.yaml`](#celcatyaml) | `celcat_mappings.json` (admins) |

**Règle prénom / nom** (la même côté serveur et côté écran) :

- des mots en capitales et d'autres non : les capitales sont le nom (« Thomas CASTELLENGO », « Barthélémy TOMASINA ») ;
- sinon, le premier mot est le prénom, le reste le nom (« KYLLIAN BRESSON », « Anne-Laure Perrone », « Alexia Petit-Halajko ») ;
- le prénom est écrit en casse normale (« Kyllian »), le nom en capitales (« BRESSON »).

Sans correction, le nom affiché partout reste le nom complet du fichier.
Dès qu'un prénom ou un nom est corrigé, le nom affiché devient « Prénom NOM » :
annuaire, fiche, « Nouvelle séance », Liens & partage, flux `.ics`, API v1.
Ressaisir le nom complet d'un bloc (fiche) efface un prénom ou un nom corrigés avant lui.

Chaque saisie garde qui, quand, la valeur d'avant et celle du fichier (journal de `references.json`).
« Revenir à la valeur du fichier » retire la saisie. Pour le type et le téléphone, cela revient à « à préciser » / vide.

Le téléphone n'est jamais dans `/app-state` ni dans l'API v1 : seulement dans `GET /reference/enseignants`,
pour les rôles `edit` et `admin` (cf. [ADMIN.md](ADMIN.md)).

### `additional_courses.yaml`

Cours absents de l'export de la maquette (code encore inconnu, ajout tardif). Ils suivent exactement le même chemin qu'une ligne officielle.

```yaml
courses:
  - code_matiere: WR100BU
    nom_matiere: "Jeu de piste BU"
    semestre: S1
    parcours: BUT1
    lead: {code: VMA, nom: MARIOT, prenom: VALERIE}
    total: {cm: 0, td: 3, tp: 0}
    profs:
      - {block: block1, code: VMA, nom: MARIOT, prenom: VALERIE, cm: 0, td: 12, tp: 0, nbGpTd: 4, nbGpTp: 0}
    maquette:
      groupes: {td: 4, tp: 0}
```

- Même forme qu'une ligne de `maquette.json`.
- `total` compte les séances **par étudiant** ; `profs[].td` compte les créneaux **de l'enseignant** (tous groupes).
- Sans progression, l'ordre est CM, TD, TP.
- WR100BU est un code inventé, absent de Celcat. Il part dans Celcat **sans module**, en catégorie « TD0 »,
  pour les interventions de VMA : voir [« Envoyer avec une règle d'envoi »](#envoyer-avec-une-règle-denvoi).

### `course_corrections.yaml`

Remplace un enseignant sur un cours, après la fusion maquette + progression. Aujourd'hui vide.

```yaml
teacher_corrections:
  - course_code: WRA304M
    semestre: S3
    parcours: BUT2-CREACOM-FC
    wrong_teacher_code: JTH
    correct_teacher_code: ARA
    note: "Qui, quand, pourquoi"
```

- `correct_teacher_code` doit déjà exister ailleurs dans la maquette. Sinon l'ingestion s'arrête avec une erreur.
- À retirer dès que la maquette officielle est corrigée : sinon la correction la contredit.

### `course_scheduling_rules.yaml`

Six sections, toutes facultatives. Semaines en **index solveur**.

```yaml
min_week_rules:
  - {course_code: WR119, semestre: S1, min_week: 3, note: "PPP pas dès la rentrée"}
max_week_rules:
  - {course_code: WRA507D, semestre: S5, max_week: 18, note: "Fin en janvier"}
session_date_windows:
  - course_code: WR100BU
    semestre: S1
    session_type: TD
    sequence_orders: [1]
    debut: 2026-09-01
    fin: 2026-09-15
teacher_order_rules:
  - {course_code: WRA505C, semestre: S5, teacher_order: [ALO, AFR], weight: 200}
teacher_distribution:
  - {course_code: WRA507D, semestre: S5, mode: alterne, teacher_order: [BTO, JSA]}
solver_scheduled_sae:
  - {course_code: WSA501D, semestre: S5}
weekly_cap_exceptions:
  - {parcours: BUT1, semestre: S1, week_monday: "2026-11-30", cap: 23}
```

| Section | Champs | Effet |
|---|---|---|
| `min_week_rules` | `course_code`, `semestre`, `min_week` | Dur : aucune séance avant cet index |
| `max_week_rules` | `course_code`, `semestre`, `max_week` | Dur : aucune séance après cet index |
| `session_date_windows` | `course_code`, `semestre`, `session_type` (option), `sequence_orders` (option), `debut`/`fin` **ou** `dates` | Dur : les séances visées tombent dans la fenêtre (fériés exclus d'office) |
| `teacher_order_rules` | `course_code`, `semestre`, `teacher_order`, `weight` (défaut 200) | Mou : le premier enseignant intervient globalement avant le suivant |
| `teacher_distribution` | `course_code`, `semestre`, `mode`, `session_type` (option), `teacher_order` | Ingestion : répartition des séances entre enseignants |
| `solver_scheduled_sae` | `course_code`, `semestre` | Cette SAE est placée par le solveur comme un cours |
| `weekly_cap_exceptions` | `parcours`, `semestre`, `week_monday`, `cap` | Relève le plafond hebdomadaire pour une promo et une semaine |

Modes de `teacher_distribution` :

- `sequentiel` (comportement par défaut, sans règle) : chaque enseignant prend un bloc de séances qui se suivent.
- `alterne` : les enseignants tournent séance après séance, volumes inchangés.
- `par_groupes` : un enseignant = des groupes entiers, même si la maquette distingue des blocs.
  Utilisé pour WR117 (S1), WR311D et WR312D (S3) en 2026-2027 seulement : **à retirer pour 2027-2028**.

Pièges :

- `sequence_orders` désigne l'`ordre` dans la progression, pas le numéro de la séance dans son type.
- Un `min_week` supérieur au `max_week` du même cours est signalé par `cal-iut audit`.
- `week_monday` est une date (lundi), pas un index. L'unique dérogation actuelle (`cap: 23`) égale le plafond par défaut :
  elle est sans effet aujourd'hui.
- Une SAE non listée dans `solver_scheduled_sae` n'est **jamais** placée par le solveur : ses enseignants l'organisent.

### `double_sessions.yaml`

Colle des séances consécutives (dans l'ordre pédagogique) en un bloc de 3 h ou 4 h 30. Le solveur ne voit plus qu'une séance.

```yaml
rules:
  - {course_code: WR110, session_type: TP, slots_per_session: 2}
  - {course_code: WR106, session_type: CM, slots_per_session: 2, pair_from: end}
  - {course_code: WRA308M, session_type: TD, slots_per_session: 3, pair_from: end, max_blocks: 1}
```

| Champ | Type | Obligatoire | Sens |
|---|---|---|---|
| `course_code` | texte | oui | Cours |
| `session_type` | `CM`, `TD`, `TP` | oui | Type de séance à coller |
| `slots_per_session` | entier | non (défaut 2) | Créneaux par bloc (2 = 3 h, 3 = 4 h 30) |
| `pair_from` | `start` ou `end` | non (défaut `start`) | Coller depuis le début ou depuis la fin de la liste |
| `max_blocks` | entier | non | Nombre maximal de blocs |

Règles actuelles : TP de WR110, TD de WR104, CM 2 et 3 de WR106, 3 derniers TD de WRA308M, TD de WSA501D.

Pièges :

- Un reste impair reste une séance de 1h30 (ex. 5 TD : 2 blocs de 3 h + 1 séance).
- Un bloc ne franchit jamais la pause de midi : un bloc de 2 commence à 8h, 9h30, 14h ou 15h30.
- Le numéro dans l'identifiant compte les **blocs** : après collage, `WR104-S1-TD-3` est le troisième bloc.

### `seances_annulees.yaml`

```yaml
annulees:
  - session_id: WR303D-S3-CM-1
    motif: "JHU ne souhaite plus assurer de CM"
    demande_par: "Justine Hussenet, via Kyllian Bresson"
    le: "2026-08-31"
```

| Champ | Obligatoire | Sens |
|---|---|---|
| `session_id` | oui | Identifiant exact de la séance |
| `motif` | **oui** (sinon l'ingestion s'arrête) | Pourquoi elle n'aura pas lieu |
| `demande_par`, `le` | conseillé | Traçabilité |

- Forme de l'identifiant : `CODE-SEMESTRE-TYPE-N` pour un CM, `CODE-SEMESTRE-TYPE-N-groupe` sinon.
- Un identifiant devenu inconnu (maquette changée) est ignoré sans bruit : relire le fichier à chaque rentrée.

### `sae_corrections.yaml`

Ajoute ou retire des journées SAE par-dessus `09_dates_sae.json`.

```yaml
corrections:
  - course_code: WSA501C
    ajouter: ["2026-09-24", "2026-09-25", "2026-11-04"]
    retirer: ["2026-11-23", "2026-11-24", "2026-11-25"]
    motif: "Journées alignées sur les disponibilités du vacataire"
    demande_par: "Marc Nino, via Kyllian Bresson"
    le: "2026-08-30"
```

- `ajouter` : journée **réservée** à la SAE, plus aucun cours classique du parcours.
- `retirer` : journée **rendue** aux cours classiques.
- `motif` obligatoire. Une même date à la fois ajoutée et retirée arrête l'ingestion.
- Se tromper de sens laisse des étudiants sans cours, ou une SAE sans intervenant.

### `sae_teacher_phases.yaml`

Restreint, enseignant par enseignant, les jours où il encadre une SAE.

```yaml
phases:
  - course_code: WS501D
    semestre: S5
    teachers:
      - {teacher_code: FME, debut: 2026-10-19, fin: 2026-10-22}
      - teacher_code: ALO
        debut: 2026-11-12
        fin: 2027-01-15
        exclure: [2026-11-26, 2026-11-27]
```

| Champ | Sens |
|---|---|
| `course_code`, `semestre` | SAE visée |
| `teachers[].teacher_code` | Enseignant |
| `debut`, `fin` | Fenêtre (incluse) ; plusieurs fenêtres possibles pour un même enseignant |
| `exclure` | Jours de la fenêtre où il n'encadre pas |

- Un enseignant de la SAE **absent** de la liste garde tous les jours (on ne libère personne par oubli).
- Une phase n'ajoute jamais de journée SAE : elle dit seulement qui encadre, parmi les jours officiels.

### `salles_reservees.yaml`

```yaml
reservations:
  - salle: "h018"
    date: "2026-09-11"
    slots: [1, 2]
    motif: "Besoin de la Direction (amphi H, 9h30-12h30)"
    demande_par: "Kyllian Bresson"
    le: "2026-08-26"
```

- `salle` est l'`id` de `rooms.yaml`.
- Utilisé par l'attribution automatique des salles et la vue « Salles libres ». Aucun cours n'est déplacé.
- BUT1 et BUT2-DEV-FI n'ont que l'amphi pour leurs CM : réserver H.018 peut laisser un CM sans salle.

### `celcat_occupations.yaml`

Occupations **hors MMI** lues dans Celcat (demande du 01/10/2026) : un autre département programme
un de nos enseignants, l'administration réserve l'amphi H.018. Le sidecar `celcat-nuit` les relit
toutes les 2 h (et sur « Relire maintenant ») et dépose `data/state/celcat_occupations_externes.json`.

```yaml
actif: true
salles: toutes            # ou [h018, h103] ; « toutes » = celles qui ont un équivalent Celcat
salles_prioritaires: [h018, amphi1_tc_gea, amphi2_gmp_geii]   # toujours surveillées
exclure_salles: []
enseignants: tous         # ou [AFR, KBR] ; « tous » = ceux qui ont un code Celcat
exclure_enseignants: []
periode: {du: auto, au: auto}   # auto = lundi de cette semaine → 31 juillet
prefixes_groupes_mmi: ["BUT MMI"]
departements_mmi: ["T_MMI"]
libelles_departements: {}       # ex. {"T_TC T27": "TC"} si le sigle n'est pas déduit
categories_ignorees: []
strict: false             # true : refus au placement manuel, sans « Forcer »
fraicheur_heures: 6       # au-delà, bandeau « relevé il y a N h »
cadence_heures: 2
lot: 10                   # identifiants par requête udlTimetables.load
pause_s: 0.3
cles_filtre_salles: [RoomIDs]
cles_filtre_enseignants: [StaffIDs, StaffID]
```

- **Ce qui est ignoré (« à nous »)** : un évènement écrit par cal-iut (journal `celcat_sync.json`, ou `notes` = identifiant de séance),
  un **cours** (catégorie entre crochets) d'un groupe « BUT MMI … », ou du département MMI sans groupe ;
  un jour férié, un évènement global, suspendu ou sans horaire.
- **Ce qui compte** : tout le reste — cours d'un autre département, réunion, jury, réservation de l'administration,
  y compris une réunion MMI saisie seulement dans Celcat.
- **Conversion** : heure réelle → nos créneaux chevauchés (10h00-12h30 bloque 9h30-11h et 11h-12h30 ; tolérance 5 min).
- **Effet** : générateur et lissage → contrainte dure ; affectation et recherche de salle → salle exclue ;
  placement manuel → **avertissement**, le placement passe (ou refus si `strict: true`) ; « À traiter » → catégorie **Pris ailleurs dans Celcat** (à revoir).
- **Passé** : une occupation d'avant aujourd'hui n'est ni affichée ni comptée.
- Fichier d'état **absent** : aucune contrainte externe. **Ancien** (> `fraicheur_heures`) : contraintes gardées, bandeau.
- Détail technique et marche à suivre si une occupation est fausse : [CELCAT.md](CELCAT.md#6-occupations-hors-mmi).

### `evenements_supplementaires.yaml`

Événements fixes annoncés après l'export officiel « Dates MMI ».

```yaml
evenements:
  - date: "2026-09-03"
    debut: "9h30"
    fin: "12h30"
    parcours: ["BUT2-CREACOM-FC"]
    salle: null
    motif: "Pré-rentrée BUT2 FC alternants"
    demande_par: "Kyllian Bresson"
    le: "2026-08-26"
```

| Champ | Sens |
|---|---|
| `date`, `debut`, `fin` | Quand ; les créneaux couverts sont bloqués |
| `parcours` | Parcours sans cours à ce moment ; `[]` = information seule |
| `salle` | Indicative |
| `motif`, `demande_par`, `le`, `note` | Traçabilité |

- Lu **seulement** par `scripts/build_contraintes.py`. Sans rebuild, rien ne change.
- Retirer l'entrée quand l'établissement l'intègre à son propre export.

### `celcat.yaml`

Correspondance entre nos identifiants et ceux de Celcat. Aucune donnée de planning.

```yaml
enseignants:
  KBR: "35543"  # BRESSON Kyllian
salles:
  h018: "Amphi 3 MMI"
  h203: "H.023"
groupes:
  convention: "BUT MMI {semestre} {libelle} - {annee}"
  annee_cohorte: "2024"
  departement: "T_MMI"
modules:
  WR101: "TSBZ1M01"  # Anglais
codes_a_confirmer:
  cours:
    WS103: "à redemander, pas supposé"
sans_code_voulu:
  cours:
    WS1PJ: "Projet Ens. : pas de code Celcat"
regles_envoi:
  cours:
    WR100BU: {enseignants: [VMA], module: aucun, categorie: "TD0", remarque: "WR100BU", motif: "…"}
  types:
    PTUT: {module: cours, categorie: "Projet", remarque: "PTUT", motif: "…"}
```

| Section | Sens |
|---|---|
| `enseignants` | Trigramme → code Celcat. `"0"` = pas encore de code |
| `salles` | `id` de salle → libellé Celcat. Salles fusionnées : une seule moitié (H.007, H.201) |
| `groupes` | Règle de nommage des groupes Celcat |
| `types_seance` | Ancien index TD/TP ; plus utilisé pour l'écriture |
| `modules` | Code de cours → code module Celcat (`TSB…`) |
| `codes_a_confirmer.cours` | Cours laissés « manquant » exprès, même si la maquette propose un code |
| `sans_code_voulu.<famille>` | Entités jamais envoyées ; le motif est obligatoire |
| `regles_envoi.cours` / `.types` | Catégorie, remarque, département et module imposés à un cours ou à un type ([détail](#envoyer-avec-une-règle-denvoi)) |

Priorité pour un code de cours : règle d'envoi `module: aucun` > « sans code (voulu) » > `celcat.yaml` > code de la maquette
> saisie dans l'appli (qui ne complète que ce qui manque). Un même cours dans `regles_envoi.cours` et `sans_code_voulu`
(ou en `module: aucun` avec un code dans `modules`) est refusé au chargement.
`types_seance: PTUT: null` : PTUT n'a pas de catégorie ordinaire, il part par sa règle d'envoi.

Pièges :

- Libellés particuliers : H.203 s'appelle « H.023 » chez Celcat ; H.022 s'appelle « H.022 studio » ; H.018 est « Amphi 3 MMI ».
- Les cours CREACOM-FC S3 finissent par `M` chez nous et par `C` chez Celcat (`WRA301M` → `TSBZC01C`).
- Une clé en double (ex. `JME`) : seule la dernière ligne compte.
- Ces codes servent aussi à la **paie** : un mauvais code n'est pas qu'une erreur d'affichage.

### `celcat_modules_maquette.yaml`

**Généré** par `python scripts/generer_codes_maquette.py`. Ne pas éditer.
Codes module repris du champ `codelement` de la maquette, pour les cours sans code dans `celcat.yaml`.

- `modules` : `{code, origine}` ; origine `maquette` ou `maquette (corrigé M→C)`.
- `exclus` : codes de la maquette **non repris** par prudence, avec la raison (affichée dans l'appli).
- À relancer quand la maquette ou `celcat_matieres.yaml` change. `--verifier` échoue si le fichier n'est plus à jour.

### `celcat_groupes.yaml`

Nom de groupe Celcat (sans « - 2024 ») → identifiant numérique.

```yaml
"BUT MMI S1 TD AB": 1661972
```

- Relevé par balayage : Celcat refuse de lister ses groupes. Ne rien déduire d'un numéro voisin.
- Un groupe absent fait échouer l'écriture avec un message trompeur (« une des ressources affectées a été supprimée »).
- Les promotions BUT3 (S5, S6) n'ont **pas** de groupe CM dans Celcat.

### `celcat_matieres.yaml`

Code module Celcat → identifiant numérique, relevé par balayage. Le nom lisible est en commentaire.

```yaml
"TSBZ1M01": 1585129  # WR101 Anglais
```

Un code de `celcat.yaml` absent d'ici bloque la séance (« code absent de data/config/celcat_matieres.yaml »).

### `celcat_formulaire.yaml` et `celcat_rpc.yaml`

Repères techniques de l'écriture dans Celcat : libellés des onglets et champs, catégories `[CM]`, `[TD]`, `[TP]`,
méthodes d'écriture et de suppression. Aucune coordonnée d'écran. Voir [CELCAT.md](CELCAT.md).

---

## Glossaire

| Terme | Définition |
|---|---|
| **Maquette** | Export officiel : pour chaque cours, ses enseignants, ses volumes et ses groupes. |
| **Progression** | Export officiel : l'ordre des séances d'un cours (ex. TD, TP, TP, CM éval) et ses liens avec d'autres cours. |
| **Ordonnancement** | Lien entre deux cours : `before` (A avant B), `after`, `same` (en parallèle). |
| **Parcours** | Une promotion suivie : `BUT1`, `BUT2-DEV-FI`, `BUT2-CREACOM-FC`, `BUT3-DEV-FI`, `BUT3-DEV-FC`, `BUT3-CREACOM-FC`. |
| **FI / FC** | Formation initiale / formation continue (alternance). Un parcours FC contient « FC » dans son nom. |
| **DEV / CREACOM** | Les deux spécialités : développement web, création et communication. |
| **Promo, TD, TP** | Groupes : la promo entière suit les CM, un groupe TD les TD, un demi-groupe TP les TP. |
| **CM, TD, TP** | Cours magistral, travaux dirigés, travaux pratiques. Une séance dure 1h30. |
| **Cohorte** | Les étudiants réels d'un TP : ils suivent les CM de leur promo, les TD de leur TD et leurs TP. |
| **Groupe unique** | Parcours FC dont TD et TP sont les mêmes étudiants : tout est émis en TD. |
| **Créneau (slot)** | Une des 6 plages de 1h30 d'une journée, numérotées 0 à 5 (8h à 18h30, pause 12h30-14h). |
| **Semaine index** | Numéro utilisé par le solveur et les fichiers : 0 = semaine du 31 août 2026. Les semaines entièrement fermées n'ont pas d'index. |
| **Semaine N** | Numéro « département » affiché dans l'appli : Semaine 1 = semaine du 24 août 2026. Continu, vacances comprises. |
| **Semaine d'intégration** | Index 0 (Semaine 2, 31 août-4 septembre) : aucun cours pour les FI. |
| **SAE** | Situation d'apprentissage et d'évaluation : projet sur des journées entières (codes `WS`, `WSA`). |
| **Journée SAE (sanctuarisée)** | Journée réservée à une SAE : aucun cours classique pour ce parcours. |
| **PAC** | Pratique artistique et culturelle : le jeudi après-midi des FI, réservé, jamais placé par le solveur. |
| **PTUT** | Projet tutoré. Type de séance prévu, jamais produit par les progressions actuelles. |
| **Duo** | Deux enseignants qui font leurs TP en même temps, dans deux salles jumelles. |
| **Séance double (bloc)** | Plusieurs séances collées en un bloc de 3 h ou 4 h 30. |
| **Trigramme** | Code enseignant de trois lettres (ex. `KBR`). |
| **Ingestion** | Transformation des sources et de la configuration en séances à placer. |
| **Solveur** | Le programme qui place les séances (OR-Tools CP-SAT), en mode « décomposé » en production. |
| **À placer** | Onglet des séances que le solveur n'a pas su placer ; on les place à la main. |
| **À traiter** | Onglet de ce qui demande une décision : non placées, doublons, violations, journées trouées. |
| **Forcer** | Placer malgré un conflit que l'appli autorise à outrepasser. |

### Index de semaine et Semaine N

L'écart n'est pas constant : les vacances n'ont pas d'index. Semestres S1, S3 et S5 :

| Index | Semaine N | Dates | Index | Semaine N | Dates |
|---|---|---|---|---|---|
| 0 | 2 | 31 août-4 sept. 2026 | 12 | 15 | 30 nov.-4 déc. |
| 1 | 3 | 7-11 sept. | 13 | 16 | 7-11 déc. |
| 2 | 4 | 14-18 sept. | 14 | 17 | 14-18 déc. |
| 3 | 5 | 21-25 sept. | 15 | 20 | 4-8 janv. 2027 |
| 4 | 6 | 28 sept.-2 oct. | 16 | 21 | 11-15 janv. |
| 5 | 7 | 5-9 oct. | 17 | 22 | 18-22 janv. |
| 6 | 8 | 12-16 oct. | 18 | 23 | 25-29 janv. |
| 7 | 9 | 19-23 oct. | 19 | 24 | 1-5 févr. |
| 8 | 11 | 2-6 nov. | 20 | 25 | 8-12 févr. |
| 9 | 12 | 9-13 nov. | 21 | 26 | 15-19 févr. |
| 10 | 13 | 16-20 nov. | 22 | 28 | 1-5 mars |
| 11 | 14 | 23-27 nov. | 23 | 29 | 8-12 mars |

Calcul : `AcademicCalendar.department_week_label(index)` dans `src/cal_iut/calendar/academic.py`.

---

## Règles de placement et contraintes du solveur

**Dur** : jamais violé par le solveur. **Mou** : le solveur l'évite autant que possible (le poids dit à quel point).
Colonne « Manuel » : ce que fait l'appli quand on déplace une séance à la main.
« Non vérifié » : le déplacement passe sans contrôle ; l'écran **Contraintes** recalcule la règle sur le planning.
Les noms entre parenthèses sont les réglages du code : `SolverConfig` (`src/cal_iut/solver/cpsat.py`) ou paramètres de `solver/decomposed.py`.
En mode décomposé, plusieurs poids mous sont fixés dans `solver/decomposed.py` : les valeurs du tableau sont celles-là.

### Calendrier et présence

| Règle | Type | Manuel | Où c'est réglé |
|---|---|---|---|
| Pas de cours pendant les vacances et jours fériés (dont 1er et 8 mai 2027) | Dur | Refusé | `02_calendrier_iut.json` (`enforce_calendar`) |
| Semaine d'intégration (index 0) sans cours pour tous les FI | Dur | Non vérifié | Code (`enforce_s1_integration_week_lock`) |
| FC : aucun cours avant la rentrée exacte du parcours | Dur | Refusé | `10_dates_fixes.json` (événement « Rentrée ») |
| FC : cours seulement les semaines de présence à l'IUT | Dur | Refusé | `03_calendrier_alternance_officiel.json` |
| FI : jeudi 14h-18h30 réservé aux PAC | Dur | Refusé | Code (`enforce_thursday_pac_lock`) |
| Journées SAE : aucun cours classique du parcours (ou des groupes visés) | Dur | Refusé (sauf séance SAE) | `09_dates_sae.json`, `sae_corrections.yaml` (`enforce_sae_sanctuarization`) |
| Événements fixes : créneaux bloqués pour les parcours listés | Dur | Refusé | `10_dates_fixes.json`, `evenements_supplementaires.yaml` (`enforce_planning_events`) |
| Horizon : FI jusqu'à l'index 18 (29 janvier 2027), FC jusqu'à l'index 23 | Dur | Refusé (fin de semestre FI) | Options `--weeks 24 --fi-max-week 18` (`fi_max_week`) |
| Semaine passée ou en cours | — | Forçable, confirmation forte | Date du jour |

### Enseignants

| Règle | Type | Manuel | Où c'est réglé |
|---|---|---|---|
| Un enseignant n'est qu'à un endroit à la fois | Dur | Forçable | — |
| Indisponibilités, listes blanches, parité | Dur | Forçable (sauf `stricte: true`) | `05_enseignants_contraintes.json`, `teacher_availability.yaml` (`allowed_slots`, `allowed_dates`, `week_parity_rules`, `parity_reference`) |
| Encadrement de SAE : pas de cours classique ces jours-là, tous parcours | Dur par défaut ; mou (poids 300) avec `--no-sae-supervisor-hard` | Forçable | `09_dates_sae.json`, `sae_teacher_phases.yaml` (`enforce_sae_supervisor_availability`, `sae_supervisor_weight`) |
| Au plus 26 créneaux (39 h) par semaine | Dur | Non vérifié | Code (`teacher_weekly_cap_slots`) |
| Duos : TP en même temps, une seule paire de salles à la fois | Dur | Forçable, sans suggestion | `teacher_duos.yaml` (`enforce_duo_rare_room`) |
| Regroupement mensuel (ARA, JHU) | Mou (120) | — | Feuille officielle, `teacher_availability.yaml` (`teacher_clustering_weight`) |
| Ordre des enseignants dans un module | Mou (200 par défaut) | — | `teacher_order_rules` (`optimize_teacher_order`) |

### Étudiants et pédagogie

| Règle | Type | Manuel | Où c'est réglé |
|---|---|---|---|
| Une cohorte n'a qu'un cours à la fois (CM promo, TD, TP) | Dur | Forçable | `groups.yaml` (`enforce_student_cohort`) |
| Au plus 23 créneaux (34 h 30) par semaine et par cohorte, FI et FC | Dur | Non vérifié | `fi_weekly_cap_slots`, `fc_weekly_cap_slots` ; dérogations `weekly_cap_exceptions` |
| Ordre de la progression dans un même groupe | Dur | Forçable | `progression.json` (`enforce_sequence`) |
| Ordre CM ↔ TD/TP vu par l'étudiant : dur dans la semaine, mou entre semaines (60 par semaine de retard) | Dur / mou | Forçable | `progression.json` (`cohort_order_weight`) |
| Une évaluation après tout le contenu qui la précède | Dur | Forçable | `progression.json` (`eval`) |
| Bornes de début, de fin, fenêtres de dates | Dur | Non vérifié | `course_scheduling_rules.yaml` (`enforce_course_min_week`, `enforce_session_date_windows`) |
| Blocs de 3 h ou 4 h 30 sur une même demi-journée | Dur | Non vérifié | `double_sessions.yaml` |
| Ordonnancement entre cours (`before`/`after`) : position moyenne | Mou (400) | — | `progression.json` (`enforce_ordonnancement`, `ordonnancement_weight`) |
| Ordonnancement strict : A fini avant le début de B | Mou (50) | — | `progression.json` (`strict_ordonnancement_weight`) |
| Étaler chaque cours sur le semestre | Mou (2 par défaut, 8 recommandé) | — | Option `--spread-weight` (`spread_weight`) |
| Regrouper les évaluations sur peu de semaines | Mou (30) | — | Code (`eval_clustering_weight`) |
| Éviter les trous dans la journée | Mou (100) | — | Code |
| Éviter lundi 8h et vendredi 17h | Mou (15) | — | Code (`avoid_zone_weight`) |
| Remplir d'abord autour de midi (11h, 14h) | Mou (8) | — | Code (`midday_fill_weight`) |
| BUT3 : éviter 8h et 17h (25), puis 15h30 (10) | Mou | — | Code |

### Salles

Les salles ne sont **pas** dans le calcul : elles sont attribuées après (cf. [`rooms.yaml`](#roomsyaml)).
En manuel : un conflit de salle est forçable ; l'appli garde la salle si elle est libre, sinon en cherche une autre.
Une salle réservée par un tiers (`salles_reservees.yaml`) ou **prise dans Celcat** (`celcat_occupations.yaml`) n'est jamais attribuée automatiquement.

### Occupations hors MMI (Celcat)

Un enseignant programmé ailleurs dans Celcat (autre département, réunion) est **indisponible** pour le solveur,
la régénération et le lissage, exactement comme une indisponibilité datée (`TeacherDateSlotRule`, dure).
Cf. [`celcat_occupations.yaml`](#celcat_occupationsyaml).

### Ce qui se force, ce qui ne se force pas

| Obstacle au placement manuel | Bouton « Forcer » |
|---|---|
| Conflit de groupe, d'enseignant ou de salle | Oui |
| Ordre pédagogique | Oui (la séance reste signalée dans « À placer » jusqu'à validation) |
| Indisponibilité d'enseignant déclarée | Oui |
| Indisponibilité `stricte: true` | **Non** |
| Enseignant ou salle déjà pris dans Celcat (hors MMI) | Oui (message « Enseignant indisponible — … Celcat ») ; **Non** si `strict: true` dans `celcat_occupations.yaml` |
| Semaine passée ou en cours, date passée | Oui, avec confirmation forte |
| Jour fermé, jeudi PAC, journée SAE, événement fixe, présence alternant, fin de semestre FI | **Non** |
| Moitié de duo déplacée seule | Oui (aucune suggestion ; mieux : régénérer la semaine) |

Une séance créée pour **représenter** un événement officiel échappe aux verrous institutionnels.

---

## Pour les techniciens

### Où est le code

| Sujet | Fichier |
|---|---|
| Lecture des YAML | `src/cal_iut/ingestion/config_loader.py` |
| Fusion maquette + progression | `src/cal_iut/ingestion/merge.py` |
| Découpage en séances, blocs, répartition des enseignants | `src/cal_iut/ingestion/normalize.py` |
| Enchaînement de l'ingestion, séances annulées | `src/cal_iut/ingestion/pipeline.py` |
| Feuille enseignants, présence des alternants, fusion des disponibilités | `src/cal_iut/ingestion/constraints_loader.py` |
| SAE, événements fixes, corrections SAE | `src/cal_iut/ingestion/planning_loader.py` |
| Calendrier, index de semaine | `src/cal_iut/calendar/academic.py` |
| Modèles des règles (champs) | `src/cal_iut/models/entities.py` |
| Contraintes, objectifs, solveur décomposé, salles | `src/cal_iut/solver/constraints.py`, `objectives.py`, `decomposed.py`, `rooms.py` |
| Contrôles d'un déplacement manuel | `src/cal_iut/api/main.py` (`_conflits_deplacement`) |
| Codes Celcat | `src/cal_iut/celcat/mapping.py`, `codes_maquette.py`, `mappings.py` |
| Audit | `src/cal_iut/audit/` (`cal-iut audit`) |

### Produire un emploi du temps en ligne de commande

Le calcul complet se lance hors du serveur, sur un poste. Les commandes, dans l'ordre :

| Commande | Ce qu'elle fait |
|---|---|
| `cal-iut doctor` | Vérifie l'installation et dit quelle commande lancer ensuite. En cas de doute, toujours elle. |
| `cal-iut refresh` | Télécharge maquette et progression et montre ce qui change, **sans rien écrire**. |
| `cal-iut refresh --ecrire` | Écrit dans `contraintes_update/` ; l'ancienne version va dans `data/sauvegardes/<date>/`. |
| `cal-iut refresh --depuis <dossier> --ecrire` | Même chose à partir de fichiers reçus par mail (serveur injoignable). |
| `python scripts/build_contraintes.py` | Régénère `contraintes/*.json` depuis `contraintes_update/`. |
| `cal-iut ingest --semestre-group odd` | Produit les séances à placer (S1 + S3 + S5) dans `data/generated/sessions.json`. |
| `cal-iut audit` | Vérifie données, configuration et capacité (cf. ci-dessous). |
| `cal-iut solve --decomposed --semestre-group odd --weeks 24 --fi-max-week 18` | Calcule un planning : `data/generated/timetable.json`. |
| `python scripts/solve_until_ok.py --max-runs 20 --max-hours 8` | Relance avec d'autres graines et garde le meilleur. |
| `cal-iut completer --timetable data/generated/timetable_best.json` | Place ce qui reste, avec les mêmes contrôles que l'appli. |
| `cal-iut load-run <timetable.json>` | Charge un planning calculé dans la base locale. |
| `cal-iut regles` | Liste en français les règles déclarées et leur raison. |

**`cal-iut annee`** enchaîne tout en quatre étapes et s'arrête à la première qui coince :

1. régénérer les contraintes (`build_contraintes.py`) ;
2. préparer les séances (`ingest`) ;
3. vérifier les données (`audit`) : une `[ERREUR]` arrête tout, sauf avec `--sans-audit` ;
4. construire l'emploi du temps (`solve_until_ok.py`, `--runs 6` tentatives, `--heures 4` au plus).

Compter de 30 minutes à plusieurs heures. Le résultat est dans `data/generated/timetable_best.json`.
Le meilleur run est ensuite complété automatiquement (comme `cal-iut completer`).

Options utiles de `cal-iut solve` :

| Option | Effet |
|---|---|
| `--decomposed` | Mode de production (semaine, puis jour et créneau, puis salles). |
| `--semestre-group odd` | Tous les parcours de S1, S3 et S5 ensemble : un enseignant partagé n'est jamais à deux endroits. |
| `--weeks 24 --fi-max-week 18` | Horizon de 24 semaines pour les alternants, FI arrêtée à l'index 18 (cf. ci-dessous). |
| `--spread-weight 8` | Lissage plus fort ; recommandé pour un run complet. |
| `--no-sae-supervisor-hard` | Encadrement de SAE en contrainte molle ; recommandé pour un run complet. |
| `--warm-start <timetable.json>` | Part d'un run précédent. Mesuré en août 2026 sur BUT1-S1 : ~15 min à froid, ~1 min ainsi. |
| `--time-limit`, `--num-workers` | Budget de temps ; nombre de processeurs (par défaut : tous, 32 au plus). |
| `--course WR108 --no-gaps` | Une seule matière, sans objectif de trous : test rapide. |
| `--last-resort-seconds`, `--last-resort-seeds`, `--benders-rounds`, `--attempts` | Réglages fins des relances. |

`scripts/solve_until_ok.py` utilise déjà `--weeks 24 --fi-max-week 18 --spread-weight 8` et l'encadrement de SAE en mou.
Il garde le meilleur run dans `data/generated/timetable_best.json`, classé par : séances manquantes,
puis ordre CM/TD/TP cassé, puis chevauchement des modules ordonnés, puis trous.
Chaque tentative est notée dans `data/generated/solve_runs.jsonl`. `--sans-completion` saute la complétion finale.

### Pourquoi `--weeks 24 --fi-max-week 18`

Avec l'horizon par défaut (19 semaines, jusqu'au 29 janvier 2027), BUT3-CREACOM-FC ne tient pas.
Il lui faut 173 créneaux. Ses 40 jours de présence, moins 12 jours de SAE (WSA501C, WSA502C), laissent 28 jours × 6 = 168 créneaux.
Le solveur répond alors `WEEK_ASSIGNMENT_INFEASIBLE` : c'est une impossibilité réelle, pas un bug.

`--fi-max-week 18` étend l'horizon aux **seuls** parcours en alternance, jusqu'à l'index 23 (8-12 mars 2027).
BUT3-CREACOM-FC a alors 38 jours libres, soit 228 créneaux. Les parcours FI ne dépassent jamais l'index 18.

### Vitesse et reproductibilité

- La grille : 6 créneaux × 5 jours × 19 semaines = 570 positions par groupe et par semestre.
- Le solveur utilise tous les processeurs. En mode décomposé : 4 semaines résolues en même temps, 4 « workers » chacune
  (16 processeurs : 4 × 4). Les semaines sont indépendantes une fois leur contenu fixé.
- Les résultats sont appliqués dans l'ordre des semaines : le parallélisme lui-même ne change pas le résultat.
- **Mais le résultat n'est pas reproductible** : avec une limite de temps et plusieurs workers, CP-SAT varie
  d'un run à l'autre, malgré une graine fixe (`random_seed=2027`). Deux runs identiques peuvent différer.
  C'est pourquoi on relance et on garde le meilleur.

### L'audit

```
cal-iut audit                                                  # données, configuration, capacité
cal-iut audit --timetable data/generated/timetable_best.json   # + vérification d'un planning produit
cal-iut audit --json                                           # sortie machine ; code retour 1 s'il y a une erreur
```

L'audit ne résout rien : il relit, recompte et compare. Quatre familles de contrôles :

| Famille | Ce qu'elle trouve | Exemple réel |
|---|---|---|
| `couverture.*` | Une règle déclarée qui ne s'applique pas | fenêtres de dates absentes du mode décomposé |
| `config.*` | Une règle qui vise un code inexistant (ignorée en silence) | code de cours mal orthographié |
| `donnees.*` | Une donnée source mal comprise | « mercredi 23/09/26 » lu comme « tous les mercredis » |
| `capacite.*` | Une impossibilité de calcul, dite avant de lancer le solveur | 22 créneaux FI pour 21 disponibles hors jeudi PAC |

Trois niveaux :

- **`[ERREUR]`** : le planning sera faux ou impossible. Corriger avant de continuer.
- **`[ALERTE]`** : une donnée est probablement mal comprise. À regarder.
- **`[INFO]`** : pour information, dont les règles que l'audit ne sait pas vérifier.

Chaque ligne dit **où** et **quoi faire**. Exemples :

> `[ERREUR] min_week_rules : aucun cours WR1119 (S1) dans la maquette — règle sans effet.` → vérifier l'orthographe du code.

> `[ERREUR] AHA : 22 créneaux de FORMATION INITIALE pour 21 créneaux disponibles hors jeudi après-midi (réservé aux PAC).`
> → élargir ses disponibilités, ou basculer une partie de son volume en FC.

Lancer `cal-iut audit --timetable …` avant de diffuser un planning : il rejoue toutes les règles sur le résultat.

### Quand ça ne marche pas

| Symptôme | Que faire |
|---|---|
| Je ne sais pas où j'en suis | `cal-iut doctor` |
| `PARTIAL_WEEKS_FAILED` | Des semaines n'ont pas pu être remplies. `cal-iut audit --timetable <fichier>` nomme la semaine et l'enseignant en cause. Sinon, relancer avec plus de tentatives. |
| `WEEK_ASSIGNMENT_INFEASIBLE` | Un parcours ne tient pas dans l'horizon. Vérifier `--weeks` et `--fi-max-week`, puis `cal-iut audit` (`capacite.*`). |
| Il manque des séances au planning | Normal : il en reste toujours quelques-unes. `cal-iut completer`, puis l'onglet **À placer**. |
| Une contrainte d'enseignant n'est pas respectée | `cal-iut audit` : chercher les formulations non comprises. Reformuler dans le CSV. |
| J'ai modifié un CSV, rien n'a changé | Lancer `python scripts/build_contraintes.py` puis `cal-iut ingest` (ou `cal-iut annee`). |
| Un enseignant n'a aucun cours | `cal-iut audit` : « un enseignant porte du volume mais n'a aucune séance ». |
| Le résultat change à chaque exécution | Normal. Garder le meilleur : `timetable_best.json`. |

### Export HTML autonome

```
cal-iut export --format html --output planning.html                       # une page, tout le planning
cal-iut export --format html --per-teacher data/generated/par-enseignant  # un fichier par enseignant
cal-iut export --format csv --output export.csv                           # tableur
```

La page HTML ne dépend d'aucun serveur : on peut l'envoyer par mail.
La variante `--per-teacher` ne contient que les séances de chaque enseignant.

### Architecture de l'appli

```
contraintes/*.json + data/config/*.yaml
        │ ingestion (au démarrage du serveur)
        ▼
séances à placer ──► solveur CP-SAT (hors serveur) ──► attribution des salles (rooms.yaml)
        │
        ▼
SQLite data/state/cal-iut.db (runs, placements, corrections, poids)
        │
        ▼
API FastAPI  ◄──►  frontend React   (GET /app-state, calculé par build_payload)
```

- Les vues en lecture seule viennent toutes de `GET /app-state`, calculé par `build_payload` (`export/html_view.py`).
  Le frontend n'invente aucun verdict : il affiche ce que le serveur a validé.
  La page `/legacy` (administrateurs) utilise la même fonction.
- Dans `src/cal_iut/api/main.py`, `app.mount("/", StaticFiles(...))` doit rester **la dernière** déclaration.
  Starlette essaie les routes dans l'ordre du fichier ; ce montage accepte tous les chemins.
  Placé plus tôt, il intercepterait `/meta`, `/app-state` et toutes les autres routes.

### Changer d'année

1. Remplacer les fichiers de `contraintes_update/` (dont « INDISPONIBILITÉS IUT », qui donne le calendrier).
2. Mettre à jour les dates écrites dans `src/cal_iut/calendar/academic.py` :
   - `DEPARTMENT_WEEK_ANCHOR` : lundi de la « Semaine 1 » (aujourd'hui le 24 août 2026, semaine ISO 35) ;
   - début du S1 (31 août 2026) et fin d'année (30 juin 2027) dans `build_default_calendar_2026_2027` ;
   - `_S1_S3_S5_START`, `_S1_S3_S5_TARGET_END` (1er février 2027) et les dates de `semester_week_offset` ;
   - `_CONFIRMED_EXTRA_HOLIDAYS` (1er et 8 mai 2027).
3. Relire les arbitrages de `contraintes/00_INDEX.md` et les entrées datées de `data/config/` :
   beaucoup ne valent que pour 2026-2027 (ex. `teacher_distribution` en `par_groupes`, `seances_annulees.yaml`, `sae_corrections.yaml`).
4. `cal-iut refresh --ecrire`, `cal-iut doctor`, puis `cal-iut annee`.

### Historique

Ce document remplace un journal de bord daté de 5 200 lignes (sections §1 à §67, août 2026).
Beaucoup de commentaires du code citent encore « docs/DATA.md §NN ».
Pour lire la section citée : `git show b3053ee:docs/DATA.md`.
