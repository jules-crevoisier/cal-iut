# Analyse des données — règles métier pour le solveur

Sources analysées pour cal-iut (année 2026-2027).

## 1. `maquette.json` + `progression.json`


| Indicateur                     | Valeur                                                                        |
| ------------------------------ | ----------------------------------------------------------------------------- |
| Matières                       | 182                                                                           |
| Parcours                       | BUT1, BUT2-DEV-FI, BUT2-CREACOM-FC, BUT3-DEV-FI, BUT3-DEV-FC, BUT3-CREACOM-FC |
| Progressions définies          | 53 / 182                                                                      |
| Ordonnancements inter-matières | 31 matières (`before`/`after`/`same`)                                         |
| Cohérence volume ↔ séquence    | 100 % sur les progressions définies                                           |


### Règles pédagogiques extraites

1. `progression.seances[]` = ordre exact CM/TD/TP (et flag `eval`).
  - Ex. WR101 : TD→TP→TP→TD→…→CM(eval).
2. **Volumes = nombre de séances de 1h30**, pas des heures horloge.
3. **Groupes** :
  - BUT1 : 4 TD × 8 TP
  - BUT2-DEV-FI : 2 TD × 4 TP
  - Parcours FC : souvent 1 TD × 1 TP
4. **Synchronisation groupes** : les séances de même `ordre` doivent tomber
  **la même semaine** pour tous les groupes TD/TP d’une matière
   (sinon les groupes divergent pédagogiquement).
5. **Ordonnancement** inter-matières (`before` / `after` / `same`) :
  - Ex. WR108 before WR109 & WS103
  - Ex. WR308D same WR301D / WR311D / WR304D (BUT2-DEV)



## 2. Contraintes enseignants (CSV)

20 enseignants, colonnes : `DIMINUTIF`, `CONTRAINTES`, `INDISPONIBILITÉS`, `DISPONIBILITÉS`.

### Indisponibilités structurées (dures)

Exemples parsés :

- `vendredi après-midi` → créneaux 14h–18h30
- `lundi toute la journée` → journée entière
- `jeudis après 17h00` → créneau 17h–18h30
- dates absolues / plages (`du … au …`)



### Contraintes textuelles (molles / notes)

- MRI : ordre idéal WR106 + CM évaluation 3h en fin
- MMA : CM puis TD, format 3h
- ARA : regrouper sur 1–2 semaines / mois
- ALO : enchaînement WS501D ↔ WRA505C avec dates
- TCA : semaines paires/impaires différentes
- DAN : éviter le matin (sauf 11h si besoin)



## 3. Indisponibilités IUT Troyes

Jours sans cours :

- Vacances Toussaint, Noël, hiver, printemps, Ascension
- Jours fériés (11 nov, Pâques, 1er/8 mai, Ascension, 14 juil…)
- Fin des cours : 30 juin 2027
- Début S2 : 4 janvier 2027

→ Ces dates sont **exclues** du placement.

## 4. Disponibilités étudiants FC (alternance)



### BUT2 FC (S3/S4) — CSV

Présence à l’IUT **1 semaine sur 2** environ (listes de dates explicites).
Appliqué à `BUT2-CREACOM-FC`.

### BUT3 FC (S5/S6) — XLSX

Idem, rythme d’alternance différent.
Appliqué à `BUT3-DEV-FC` et `BUT3-CREACOM-FC`.

Les étudiants FI (formation initiale) sont considérés disponibles toute la semaine
enseignable.

## 5. Mapping → contraintes solveur


| Source                                  | Type  | Implémentation                               |
| --------------------------------------- | ----- | -------------------------------------------- |
| `progression.seances` ordre             | Dur   | `ordre N < ordre N+1` par groupe             |
| Sync groupes même ordre                 | Dur   | même semaine pour tous les TD/TP d’un ordre  |
| `ordonnancement` before/after/same      | Dur   | min/max entre matières                       |
| Indispos enseignants (créneaux + dates) | Dur   | créneaux interdits                           |
| Vacances / fériés IUT                   | Dur   | créneaux bloqués                             |
| Présence FC                             | Dur   | `add_allowed_assignments` sur jours présents |
| Trous journées                          | Molle | objectif (si ≤150 séances)                   |
| Préférences / commentaires              | Molle | notes + poids feedback                       |




## 6. Point d’attention

Le fichier `maquette.json` à la racine était vide (0 octet) — la copie
valide est dans `data/exports/maquette.json` (resync automatique).

## 7. Règles ajoutées suite à l'analyse du cahier des charges exhaustif (§2-3, §11-12)





### 7.1 Bug corrigé — `promo_group` manquant pour BUT2/BUT3

`groups.yaml` ne définissait un `promo_group` (groupe CM) que pour `BUT1`.
Pour tous les autres parcours, les séances de CM étaient taguées avec un id
promo **synthétique** (`f"{parcours}-promo"`, généré par
`normalize._promo_group_id`) qui n'existait dans aucun `Group` réel.
Or `build_student_cohorts` (résolveur de cohortes étudiantes) ne rattache un
CM à une cohorte que si son `group_id` correspond à un `Group` de `kind="promo"`
effectivement déclaré. Conséquence : pour BUT2/BUT3, un CM pouvait se
chevaucher avec le TD/TP de la même promo sans qu'aucune contrainte
`NoOverlap` ne le détecte. Corrigé en ajoutant un `promo_group` explicite à
chaque parcours dans `groups.yaml`.

### 7.2 Structure de groupes corrigée — BUT2/BUT3-DEV-FI

Le cahier des charges (§1, §13) précise que DEV-FI (S3 à S6) a une structure
**2 TD (AB, CD) × 4 TP (A, B, C, D)** — chaque TD se scinde en 2 sous-groupes
TP, comme en BUT1 mais resserré. `groups.yaml` ne déclarait qu'un TP par TD
(2 TP au total) : corrigé pour `BUT2-DEV-FI` et `BUT3-DEV-FI`. Les parcours FC
(`*-DEV-FC`, `*-CREACOM-FC`) restent à 1 TD × 1 TP (aucune indication contraire
dans le cahier des charges — cohortes d'alternants réduites).

### 7.3 Plafond horaire hebdomadaire (dur) — §3

- FI (formation initiale) : **33h/semaine max = 22 créneaux de 1h30**, strict.
- FC (alternants) : **~35h/semaine max = 23 créneaux de 1h30**.

Implémenté dans `solver/constraints.py::add_weekly_hour_cap_constraints`,
appliqué par cohorte étudiante réelle (CM promo + TD + TP, via
`build_student_cohorts`) et non par `group_id` brut, pour ne pas sous-compter
la charge d'un étudiant qui suit les trois. Activable via
`SolverConfig.enforce_weekly_hour_cap` (défaut `True`).

### 7.4 Jeudi après-midi verrouillé pour la FI — §2

14h00-18h30 le jeudi est réservé aux PAC (placées manuellement, hors
solveur) pour toute la Formation Initiale. Les parcours FC ne sont pas
concernés (créneau stratégique pour eux). Implémenté en dur dans
`add_thursday_afternoon_pac_lock` (`SolverConfig.enforce_thursday_pac_lock`).

### 7.5 Zones à éviter (molles) — §2

Lundi 8h00-9h30 et vendredi 17h00-18h30 sont des créneaux de dernier recours
(pas interdits, juste déconseillés). Implémenté comme pénalité objectif dans
`add_avoid_zone_penalties` (`SolverConfig.optimize_avoid_zones`,
`avoid_zone_weight`, défaut 15).

### 7.6 Cartographie des salles réelle — §11-12

`rooms.yaml` contenait des salles génériques fictives ("Amphi A", "Labo Dev
1"...). Remplacé par l'inventaire réel du bâtiment H (H.005 à H.205, + A.018
pour les évaluations), avec les règles CM→H.018 systématique, Anglais→H.103
systématique, H.016 (salle Mac, pas de fenêtres) en dernier recours, salles
couplées (H.007+H.008, H.201+H.203, H.017+H.022 « hack Celcat ») modélisées
comme salles Celcat distinctes pour éviter tout double-booking fictif.
H.001 (réunion BDE) est volontairement absente : exclue des cours.
`RoomType` (models/entities.py) étendu en conséquence.

### 7.7 Points encore ouverts (non traités ici, cf. cahier des charges §16)

- ~~Les effectifs BUT1 (60/TD, 30/TP, 240/promo) ne sont pas fournis...~~
  **Confirmé par Kyllian Bresson le 05/08/2026 : 30/TD, 15/TP, 120/promo**
  (la moitié des chiffres placeholder ci-dessus, qui n'avaient jamais été
  validés) — correspond déjà exactement à `data/config/groups.yaml`
  (4 TD × 30, 8 TP × 15, promo 120), aucun changement de config nécessaire.
- Sanctuarisation SAE (« un jour alloué à une SAE interdit tout cours
classique ce jour pour ce parcours ») : seule la version *molle*
(`add_sae_window_constraints`, qui rapproche les séances SAE de leurs
fenêtres) est implémentée. La version dure (bloquer les cours *classiques*
sur ces jours) reste à ajouter.
- WR318D (PPP S3-DEV-FI), WR120 détail fin, et modules S2/S4/S6/DEV-FC/CREACOM-FC
ne sont pas couverts par le cahier des charges fourni.



## 8. Deuxième vague de corrections (retour utilisateur sur le premier run réel)



### 8.1 Bug corrigé — ordonnancement before/after quasi toujours violé

Audit sur les données réelles (BUT1-S1, 1437 séances) : les 17 relations
`before`/`after` du cahier des charges étaient violées à 100 % dans le premier
run. Cause : `add_ordonnancement_constraints` comparait `max(source)` /
`min(target)` sur **toutes** les séances de la matière (tous groupes TD/TP
confondus), ce qui exige que l'intégralité de la promo finisse le cours A
avant que qui que ce soit commence B — quasi impossible dès qu'un cours est
étalé sur le semestre (objectif spread). Corrigé en deux temps :

1. La comparaison se fait maintenant **par groupe étudiant brut** (ex.
  `but1-tp-a`), pas sur la matière entière.
2. En mode molle (cohortes réelles), on compare la **position moyenne**
  pondérée des séances de A vs B (plutôt que max/min stricts), qui reste
   fidèle à "A se déroule globalement avant B" sans exiger une séparation
   totale. Résultat vérifié : 0 violation sur le même jeu de données avant/après.



### 8.2 Sanctuarisation SAE (dure) — §8

Ajout de `add_sae_sanctuarization_constraints` : si un jour est alloué à une
SAE pour un parcours (déduit du planning Excel officiel), aucune ressource
classique (WR/WRA) ne peut être placée ce jour pour ce même parcours. Les
séances SAE elles-mêmes (WS/WSA) ne sont pas concernées. Contrôlé par
`SolverConfig.enforce_sae_sanctuarization` (défaut `True`).

### 8.3 Semaine "département" corrélée au calendrier réel

Le numéro de semaine interne du solveur (0-based) est maintenant traduisible
en numéro "département" + dates réelles via
`AcademicCalendar.department_week_label`. Ancrage confirmé par l'utilisateur :
semaine 1 = lundi de l'ISO-week 35 2026 (24 août). En découle : rentrée
(31 août/2 sept. 2026) = semaine 2, vrai démarrage des cours S1 (7 sept.) =
semaine 3. Utilisé dans l'export HTML pour afficher "Semaine 3 (7–11 sept.
2026)" plutôt qu'un simple index.

Contrainte dure ajoutée en conséquence : `add_s1_integration_week_lock`
interdit toute séance classique/SAE en semaine-index 0 pour le semestre S1
(semaine d'intégration BUT1, accueil administratif uniquement).

### 8.4 Remplissage centré sur la pause méridienne (molle) — nouvelle demande

`add_midday_fill_penalties` : les créneaux 11h-12h30 et 14h-15h30 (collés à la
pause) sont préférés aux créneaux d'extrémité de journée (8h, 17h). Distance
au centre : 11h/14h=0, 9h30/15h30=1, 8h/17h=2, pénalisée linéairement.
Contrôlé par `optimize_midday_fill` / `midday_fill_weight` (défaut 8).

### 8.5 Regroupement des évaluations + salle A.018 obligatoire — nouvelle demande

- `add_eval_clustering_penalties` (molle) : les séances `is_eval` d'un même
parcours/semestre sont rapprochées sur une même semaine (pénalité sur
l'écart max-min entre semaines), sans les pousser plus tôt — si un module
finit tard, son éval peut légitimement tomber tard.
- Règle de salle dure : `RoomType.EVALUATION` (A.018 uniquement) + nouveau
champ `is_eval` sur `RoomAssignmentRule` — toute séance `is_eval=True` est
forcée en A.018, quel que soit le module, y compris quand un CM non-éval du
même cours a déjà été mis en cache dans une autre salle (ex. WR107 CM2 =
évaluation ≠ CM1).



### 8.6 Export HTML interne (« internaliser » la démo)

Nouvelle commande `cal-iut export --format html` (`src/cal_iut/export/html_view.py`

- `templates/timetable.html`) : calendrier interactif auto-contenu (groupe/semaine,
vérifications automatiques recalculées côté client), **avec vue TD à 2
colonnes TP** quand les deux sous-groupes suivent des séances différentes au
même créneau (parité avec `frontend/src/components/TdWeekGrid.tsx`, qui a la
même fonctionnalité côté app React).



### 8.7 Points restés ouverts (à confirmer avec l'utilisateur)

- **Date de démarrage S2 — RÉSOLU** : confirmé par l'utilisateur, le S2 vise
le lundi 1er février 2027 (comme l'année précédente), pas le 4 janvier
théorique (trop juste, aucune marge avec 16 semaines de S1). `semester_week_offset`
mis à jour, `--weeks` par défaut passé à 19.
- **3 événements institutionnels sans date confirmée** (transcrits depuis une
capture d'écran fournie, table HEURE DÉBUT/FIN/SALLE/BUT/MOTIF) : "Date
sous-commission" (ADMIN, 9h-12h30, H104), "Echange IA" (S1, 9h30-12h30,
H.018), "Présentation des services aux nouveaux étudiants" (S1, 17h-18h30,
A.018). Les 8 autres lignes de cette table (Rentrées + VSS) ont pu être
recoupées avec les dates déjà connues (§6) et sont implicitement couvertes
par `add_s1_integration_week_lock` + le calendrier des rentrées ; ces 3-là
n'ont pas de date exploitable pour l'instant → pas de blocage calendrier
ajouté pour elles.



## 9. Audit progression/enseignants + webapp Groupe/Enseignant/Contraintes



### 9.1 Audit progression.json / maquette.json (demande explicite)

Vérifié sur la sortie réelle du solveur (BUT1-S1, 1437 séances) :


| Vérification                                                                | Résultat                                          |
| --------------------------------------------------------------------------- | ------------------------------------------------- |
| Ordre pédagogique CM→TD→TP par groupe (dur)                                 | 0/1157 violations                                 |
| Évaluation placée après tout le contenu du module                           | 0/10 violations                                   |
| Séquence solveur == séquence `progression.json` (aucun ordre manquant/faux) | 0 écart sur les 53 matières à progression définie |
| `progression.json` lui-même (évals jamais avant du contenu, à la source)    | 0 anomalie sur 53 matières                        |




### 9.2 Audit contraintes enseignants (demande explicite)

13 enseignants avec une contrainte déclarée dans le CSV (créneaux récurrents
et/ou dates ponctuelles) : **0 violation** sur la sortie réelle du solveur.

### 9.3 Webapp interne — 3 onglets (`export/html_view.py` + `templates/timetable.html`)

- **Vue Groupe** (inchangée) : calendrier + TD 2 colonnes TP + vérifications.
- **Vue Enseignant** (nouveau) : même calendrier mais filtré par enseignant
(`rows` filtrées sur `teacher_codes`, pas de cohorte), avec un encart
rappelant sa contrainte déclarée telle quelle (texte brut du CSV) et le
verdict — recalculé, pas affirmé — sur la sortie réelle.
- **Contraintes** (nouveau) : tableau de bord listant
  - chaque règle globale du solveur (`_rule_checks` dans `html_view.py`) avec
  statut pass/fail/info et détail chiffré ;
  - chaque enseignant à contrainte déclarée, texte brut + verdict + créneaux
  en violation le cas échéant.
- **Bandeau calendrier institutionnel** (nouveau) : vacances, jours fériés,
rentrées, dates repères (§6), affiché en frise horizontale au-dessus des
onglets (`INSTITUTIONAL_EVENTS` dans `html_view.py` — informatif seulement,
ne bloque rien : le blocage réel vient d'`AcademicCalendar`).

Tout est calculé côté Python à l'ingestion du payload (`build_payload`), pas
recalculé de façon incohérente côté JS — un seul endroit de vérité par règle.

### 9.4 Vitesse — warm-start (`--warm-start`)

`TimetableSolver.solve(..., hints=...)` appelle `CpModel.add_hint` par séance
à partir d'un `timetable.json` précédent (aucune modification du modèle ni
des contraintes — la qualité ne peut pas être dégradée par construction,
seule la vitesse de convergence change). Mesuré sur BUT1-S1 (19 semaines,
12 cœurs) :


| Run                           | Temps                  | Statut   | Objectif | Trous |
| ----------------------------- | ---------------------- | -------- | -------- | ----- |
| À froid                       | ~15 min (900s alloués) | FEASIBLE | 177 924  | 380   |
| Warm-start (même run en hint) | 60s alloués            | FEASIBLE | 179 890  | 385   |


Recommandé pour toute régénération itérative (verrouillage de séances,
ajustement mineur) plutôt que repartir de zéro.

## 10. Bug trouvé par l'utilisateur — éval WR106 avant le contenu qui la précède



### 10.1 Le bug

Sur la première webapp générée, l'utilisateur a repéré `WR106 CM · éval · MRI` en semaine-index 1 (« semaine 3 »), un vendredi. Vérification directe :
le dernier TP (ordre 12) qui doit précéder cette éval n'avait lieu qu'en
semaine-index 18 pour 7 des 8 groupes. **Les étudiants auraient été évalués
sur un contenu qu'ils n'avaient pas encore reçu.**

Cause : `add_pedagogical_sequence_constraints` ne comparait les séances
qu'au sein d'un même `group_id` **littéral**. Un CM/éval partagé est tagué
`but1-promo`, différent de `but1-tp-a`, `but1-tp-b`, etc. — il n'était donc
jamais comparé aux TD/TP d'un sous-groupe spécifique, seulement aux autres
séances déjà taguées `promo`.

**Point d'intégrité** : mon audit initial (§9.1, "0/1157 violations") utilisait
la même erreur de regroupement par `group_id` littéral dans le script de
vérification — il ne pouvait donc pas détecter ce cas précis. Corrigé dans
`html_view.py::_rule_checks` en même temps que le solveur, avec la bonne
méthode de cohortes (`build_student_cohorts`).

### 10.2 Le correctif — barrière ciblée, pas synchronisation totale

Une première version corrigeait TOUTE la séquence par cohorte réelle (chaque
étape, pas seulement l'éval). Testée : elle rendait le problème bien plus dur
à résoudre (un run à 900s qui trouvait `FEASIBLE` avant se retrouvait
`UNKNOWN` même après 900-1500s). Cause : forcer une synchronisation stricte
de 8 sous-groupes à CHAQUE CM intermédiaire (pas seulement l'éval finale)
crée une contrainte combinatoire bien plus sévère, pour un gain pédagogique
marginal (un léger différentiel de rythme entre 2 TD/TP n'a rien de grave —
seule une évaluation avant le contenu est un vrai problème académique).

Version retenue, plus ciblée :

- L'ordre par `group_id` littéral reste inchangé (TD/TP propres à un
sous-groupe, CM entre eux) — pas de sur-contrainte.
- **Nouvelle barrière dure, ciblée uniquement sur les évaluations** :
`_add_eval_after_cohort_content_constraints` — pour CHAQUE cohorte réelle
(`build_student_cohorts`), la dernière séance non-éval de cette cohorte
doit précéder toute éval de sequence_order supérieur. Coût : quelques
centaines de comparaisons `<` supplémentaires (pas de nouvelle variable),
négligeable comparé à la version "toute la séquence".



### 10.3 Deuxième bug trouvé pendant la vérification : le check affiché ne

correspondait pas à ce que le solveur garantit réellement

En régénérant après le correctif, l'onglet Contraintes affichait
`pedagogical_order fail 520/2200` alors que le solveur venait de trouver une
solution `FEASIBLE` censée respecter cette contrainte dure. Cause :
`html_view.py::_rule_checks` vérifiait encore la version "toute la séquence
par cohorte complète" (celle qui s'est révélée trop stricte et abandonnée
côté solveur), pas la version ciblée réellement appliquée — il comparait donc
à tort des séances qui n'ont jamais été censées être synchronisées. Corrigé
pour recalculer EXACTEMENT les deux mêmes contraintes que le solveur (ordre
par `group_id` littéral + barrière éval par cohorte). Résultat final vérifié
sur la sortie réelle (BUT1-S1, run FEASIBLE, objectif 142 459, 398 trous) :


| Vérification                              | Résultat                                        |
| ----------------------------------------- | ----------------------------------------------- |
| Ordre pédagogique (`group_id` littéral)   | 0/1157 violations                               |
| Éval après contenu (barrière par cohorte) | 0/88 violations                                 |
| Sanctuarisation SAE                       | 0 violation                                     |
| Éval → salle A.018                        | 0/11 hors A.018                                 |
| Plafond horaire hebdo                     | 0 cohorte au-dessus                             |
| Jeudi après-midi (PAC)                    | 0 violation                                     |
| Contraintes enseignants (13 profs)        | 0 violation                                     |
| Ordonnancement inter-matières (molle)     | 19/204 non respectées (attendu, objectif molle) |


**Leçon retenue** : un script de vérification qui partage le même bug que le
code qu'il vérifie donne une fausse confiance (cf. §10.1) ; un script de
vérification plus strict que ce que le modèle garantit donne de faux
échecs. Les deux write-ups précédents ("0/1157" en §9.1, puis "fail" juste
après le correctif) illustrent chacun un de ces deux pièges — d'où
l'importance de garder UNE SEULE implémentation de référence (ou de la
dupliquer à l'identique, jamais une version "améliorée") entre le solveur et
son affichage de vérification.

## 11. `contrainte.json` (cahier des charges machine-readable) — audit d'intégration

Fichier fourni par l'utilisateur : restitution structurée du même cahier des
charges déjà analysé (§1-10), pas de données nouvelles au sens strict, mais
utile pour un audit systématique de ce qui manquait encore.

### 11.1 Ordonnancement : tentative de contrainte dure, revenu à une molle à poids élevé

Retour utilisateur : "essentiel dans l'enseignement". `add_ordonnancement_constraints`
acceptait déjà un mode dur (`strict_mean`). Essayé comme défaut
(`ordonnancement_hard=True`), avec l'accord explicite de l'utilisateur pour
un temps de calcul plus long si besoin ("si il est plus long c'est pas grave
tant que le résultat est bon"). **Testé empiriquement sur les données réelles
(BUT1-S1, 19 semaines, 12 cœurs) :**


| Config                                 | Budget | Résultat                            |
| -------------------------------------- | ------ | ----------------------------------- |
| Molle (poids 80), dates SAE de base    | ~900s  | `FEASIBLE`, objectif 142 459        |
| **Dure**, dates SAE de base            | 1200s  | `UNKNOWN` (aucune solution trouvée) |
| **Dure**, dates SAE complétées (§11.3) | 1800s  | `INFEASIBLE` **(prouvé)**           |


Conclusion : rendre l'ordonnancement pleinement dur n'est pas tenable sur ce
jeu de données réel, une fois combiné aux autres contraintes dures
(sanctuarisation SAE en particulier). Retenu comme défaut définitif :
**molle avec un poids fortement relevé (400, contre 80 initialement)** —
`SolverConfig.ordonnancement_hard = False`, `ordonnancement_weight = 400`.
Le mode dur reste disponible (`ordonnancement_hard=True`) pour un usage
ponctuel sur un sous-ensemble de données où il est faisable (testé et validé
par `test_ordonnancement_hard_mode_available_when_requested`).

### 11.2 Bug trouvé en comparant à `objective_function.priorite_1`

Le JSON confirme noir sur blanc l'objectif déjà documenté au §5 du premier
cahier des charges : *"Densifier au maximum S1, S3, S5... remplissage
front-load: remplir chaque semaine à ras bord dès le début, pas d'étalement
sur 4 mois."* Or `add_semester_spread_penalties` faisait l'inverse : elle
étirait délibérément chaque cours sur l'ensemble de l'horizon
(`target = (i+0.5)/n * horizon`), l'exact contraire du front-load demandé.

Corrigée une première fois pour minimiser directement `Σ start_i`. **Note de
mise à jour (chantier S1 ci-dessous, §12) : cette version simple s'est révélée
insuffisante à l'usage** (compétition frontale entre matières, cf. docstring
de `add_semester_spread_penalties` dans `objectives.py`) et a été remplacée
par une 4e itération — proportionnelle par cours, cible compressée dans les
60% premiers de l'horizon (`_FRONTLOAD_FRACTION`) — qui est la version
réellement en vigueur dans le code aujourd'hui. Cette section restait périmée
par rapport au code depuis cette itération ; corrigé ici pour que la doc
cesse de désigner une version abandonnée.

### 11.3 Dates SAE incomplètes — mauvaise approche corrigée, vrai bug de parsing trouvé

Première tentative (erronée) : comparant `sae_dates.S1` (contrainte.json) à la
sortie du parseur xlsx, **WS105 et WS106 semblaient absents** (seuls
WS101/102/103/104/107 détectés) — j'ai ajouté un `merge_reference_sae_dates`
qui réinjectait des dates transcrites à la main depuis `contrainte.json`.
**L'utilisateur a eu raison de corriger cette approche** : `contrainte.json`
est un résumé dérivé, pas la source — la seule source de vérité pour les
dates SAE est `Plannings MMI 2026_2027.xlsx`. Pire, cette réinjection à la
main a fait passer le total de jours bloqués de 35 à 77 (quasiment doublé),
signe que la transcription manuelle avait aussi introduit des jours en trop
sur des codes déjà correctement lus par ailleurs — exactement le risque que
la règle "donnée fraîche" du cahier des charges met en garde.

Retiré entièrement (`merge_reference_sae_dates` supprimé). Le vrai problème :
**bug dans** `_normalize_sae_token`. Vérifié directement dans le xlsx : la
cellule contient bien le texte `"SAE105/106"`. L'ancienne regex
(`SAE([0-9]{2,3}[A-Z]?)`) s'arrêtait au premier groupe de chiffres et
tronquait `"105/106"` en `"105"`, perdant WS106 (`sae_token_to_course_codes`
gérait déjà correctement le découpage par `/`, mais ne recevait jamais le
token complet). Corrigé pour capturer le token composé en entier
(`SAE([0-9]{2,3}[A-Z]?(?:/[0-9]{2,3}[A-Z]?)*)`). Résultat après correctif,
directement depuis le xlsx réel, sans donnée réinjectée : **7 codes SAE
détectés (WS101/102/103/104/105/106/107)**, 35 jours distincts bloqués au
total pour BUT1-S1 — un résultat sain, cohérent avec l'ajout minimal attendu
(2 semaines supplémentaires pour WS105/106, largement chevauchantes avec des
semaines déjà bloquées par SAE102).

### 11.4 Gaps identifiés, non traités dans cette passe (à prioriser avec l'utilisateur)

- `duo_synchronise_salle_rare` (WR110, WR112, WR113) : documenté comme
règle (2 duos d'enseignants ne doivent jamais se chevaucher dans une salle
rare comme le Studio H.017), mais jamais modélisé comme une contrainte
solveur réelle — seulement une préférence de salle dans `rooms.yaml`. Pour
l'implémenter il faudrait encoder les duos eux-mêmes (quel enseignant est
lié à quel autre, sur quel module) comme donnée d'entrée, absente des
exports maquette/progression actuels.
- `module_rules_S3_DEV_FI` (volumes/répartition détaillés pour ~19
modules) : jamais croisé avec les vraies données `maquette.json` pour ce
parcours (tout le travail de cette conversation a porté sur BUT1-S1) — à
faire si BUT2/BUT3-DEV-FI est mis en solve.
- `placement_priority_layers` (SAE → vacataires → gros volumes → petits
volumes) : c'est une stratégie de placement MANUEL séquentiel ; le solveur
CP-SAT actuel résout tout le problème d'un coup (généralement supérieur à
un placement glouton par couches, qui peut se coincer sur des choix
précoces). Pas de changement de code proposé sauf si l'utilisateur observe
un cas concret où le résultat joint est moins bon qu'un placement par
couches l'aurait été.
- **Incohérence BTO** (disponibilités "mardi matin + mercredi" vs "mercredi +
jeudi matin") : **résolue depuis** — `contraintes/05_enseignants_contraintes.json`
contient désormais pour BTO "lundi toute la journée - mardi après-midi -
mardi - jeudi après-midi - vendredi toute la journée" (plus de mercredi,
plus de contradiction ; légère redondance sans conséquence entre "mardi
après-midi" et "mardi" qui la couvre déjà). Vérifié le 05/08/2026 en
rechargeant `load_all_constraints` — aucune trace de l'ancienne
incohérence dans les données actuelles.



## 12. Refonte S1 — ingestion sur `contraintes/*.json` + résolution en paliers

Chantier déclenché par un constat d'audit : `contraintes/` contient désormais
8 fichiers JSON propres et numérotés remplaçant les CSV/XLSX bruts d'origine
(qui ont disparu du dépôt). Or l'ingestion cherchait encore ces fichiers bruts
par nom à la racine (`_find_file`) — en silence, sans exception, elle
retombait sur des listes vides. **Conséquence concrète : tous les audits
"0 violation" de ce document (§9, §10.3) ont tourné sans aucune contrainte
enseignant ni fenêtre/sanctuarisation SAE réelle**, alors que le code semblait
fonctionner (aucun test ne le détectait avant l'ajout d'un test de non-vide).

### 12.1 Ingestion migrée sur `contraintes/*.json`

- `ingestion/constraints_loader.py::load_all_constraints` lit désormais
directement `contraintes/05_enseignants_contraintes.json` (déjà tokenisé :
`indisponibilites_tokens[].{type,jour,moment}`, bien plus fiable qu'un
reparsing regex de texte CSV libre) et
`contraintes/03_calendrier_alternance_officiel.json` (présence FC). Lève
désormais `ConstraintsDataError` si aucun enseignant n'est chargé, au lieu
de dégrader en silence — c'est exactement ce garde-fou qui manquait.
- `ingestion/planning_loader.py::load_mmi_planning` lit
`contraintes/04_planning_hebdomadaire_par_promo.json` au lieu de scanner un
xlsx. Vérifié : **35 jours SAE bloqués pour BUT1-S1**, identique au chiffre
de référence du §11.3 — confirme que la migration reproduit fidèlement
l'ancien résultat, en s'appuyant sur une source qui, elle, existe encore.
- `calendar/academic.py::build_default_calendar_2026_2027` lit
`contraintes/02_calendrier_iut.json` (vacances + jours fériés) au lieu de
listes codées en dur, avec repli sur l'ancien codage en dur si le fichier
est absent (avertissement `warnings.warn`, pas un échec silencieux).
Écart de donnée noté et tranché avec l'utilisateur : le 1er mai et le 8 mai
2027 (fériés légaux français réels) sont absents de `jours_feries` dans la
source IUT — ajoutés explicitement (`_CONFIRMED_EXTRA_HOLIDAYS`) plutôt que
suivre la source à la lettre.



### 12.2 Horizon S1 calé sur le 1er février 2027 — calculé, plus codé en dur

`weeks=19` était dupliqué à 4 endroits (`SolverConfig`, CLI, schéma API) avec
une 5e valeur divergente côté frontend/DB (`16`). Remplacé par
`academic.py::default_horizon_weeks(calendar, semestre)` : pour S1/S3/S5,
nombre réel de semaines enseignables entre le 31 août 2026 et le 1er février
2027, recalculé depuis le calendrier (donc robuste si le calendrier change une
année future) — `weeks=None` dans `SolverConfig` déclenche ce calcul
automatiquement à la résolution. Résultat vérifié : toujours 19 semaines avec
le calendrier actuel, dernière semaine utilisable = lundi 25 - vendredi 29
janvier 2027 (marge d'un week-end + un jour avant le 1er février). Frontend
(`MAX_WEEKS`) et le payload envoyé à `/solve` ne codent plus cette valeur en
dur ; test de non-régression ajouté (`test_but1_s1_placements_stay_before _february_2027`) qui vérifie la date calendaire réelle de chaque séance
placée, pas seulement l'index de semaine.

### 12.3 Résolution en paliers (`solve_tiered`) — remplace la somme pondérée par défaut

Motif : la somme pondérée (poids 400/100/50/30/15/8/2 réglés à la main) jugée
par l'utilisateur pas assez fiable/prévisible — un score agrégé ne dit pas
quelle priorité métier a été sacrifiée, et le compromis trouvé dépend de où le
solveur s'arrête dans le budget de temps. Remplacée par une résolution en
3 paliers lexicographiques, chacun minimisé puis VERROUILLÉ (contrainte
`sum(pénalités) <= V_atteint`) avant de passer au suivant, avec ré-amorçage
(`add_hint`) de la solution du palier précédent pour ne pas perdre de temps à
retrouver une simple faisabilité sous contrainte resserrée :

1. Ordonnancement inter-matières (jugé pédagogiquement essentiel)
2. Densification S1/S3/S5 (front-load, `objective_function.priorite_1`)
3. Confort résiduel (sync groupes, clustering évals, trous, zones à éviter,
  remplissage méridien) — petite somme pondérée entre eux, non contentieuse

**Benchmark sur données réelles BUT1-S1 (1437 séances, 12 cœurs, budget 900s
— cf. §9.4 pour la référence "cold" historique), une fois l'ingestion §12.1
corrigée (donc AVEC contraintes enseignants et sanctuarisation SAE réelles,
contrairement à tous les runs précédents de ce document) :**


|                                   | Somme pondérée (`solve()`) | Paliers (`solve_tiered()`)                                                      |
| --------------------------------- | -------------------------- | ------------------------------------------------------------------------------- |
| Statut                            | FEASIBLE (904s)            | FEASIBLE (904s)                                                                 |
| Séances placées                   | 1437/1437                  | 1437/1437                                                                       |
| Ordonnancement (violations/total) | **15/204**                 | **0/204**                                                                       |
| Trous (créneaux)                  | 391                        | **273**                                                                         |
| Détail objectif                   | 229 582 (agrégé, opaque)   | ordonnancement=0, frontload=203 404, confort=19 920 (diagnosticable par palier) |


Les paliers gagnent sur **toutes** les dimensions mesurées, au même budget de
temps, avec les mêmes contraintes dures : 0 violation d'ordonnancement au lieu
de 15 (le palier 1 trouve et verrouille le vrai minimum, pas un compromis
pondéré), et même le confort (trous) est meilleur — probablement parce que
verrouiller l'ordonnancement à son optimum libère de la place utile plus tôt
plutôt que de la disputer en permanence avec les autres objectifs mous.

**Décision :** `solve_tiered()` **devient le mode par défaut** pour `cal-iut solve`
(CLI) et `POST /solve` (API) — `solve()` (somme pondérée) reste disponible via
un flag explicite (`--legacy-weighted` / `SolveRequest.legacy_weighted=True`)
comme filet de sécurité, non supprimé sans autre preuve contraire.

**Point opérationnel non résolu (à trancher avec l'utilisateur)** : au budget
par défaut de l'app (`time_limit_seconds=300`), le run complet BUT1-S1
retombe désormais à `UNKNOWN` (aucune solution trouvée) — avant cette
correction d'ingestion, 300s suffisaient car les contraintes enseignants
étaient silencieusement absentes, rendant le problème artificiellement plus
facile. Le chiffre "cold" historique du §9.4 (~15 min = 900s) était déjà le
budget réellement nécessaire ; le défaut applicatif de 300s ne l'a simplement
jamais reflété. À augmenter (300 → 900s au moins) pour tout run complet
BUT1-S1 sans warm-start, ou à documenter comme limite du mode interactif
rapide (sous-ensembles/warm-start uniquement). `SolverConfig.time_limit_seconds`
et `cli.py --time-limit` par défaut relevés à 900 en conséquence.

### 12.4 Vérification de bout en bout (CLI complet, mode paliers, données réelles)

`cal-iut ingest --parcours BUT1 --semestre S1` → `cal-iut solve` (paliers,
900s, isolé de toute autre charge CPU concurrente — un run lancé en parallèle
d'une suite de tests complète a bien confirmé la sensibilité du solveur à la
contention CPU, `UNKNOWN` en concurrence vs `FEASIBLE` isolé au même budget,
cohérent avec la sensibilité déjà connue de CP-SAT au parallélisme réel) →
`cal-iut export --format html`. Résultat : `FEASIBLE`, 1437/1437 séances
placées, objectif palier confort 18 707, 270 trous, 0 jour isolé. Tableau de
bord Contraintes recalculé sur cette sortie réelle :


| Règle                         | Statut                     |
| ----------------------------- | -------------------------- |
| Plafond horaire hebdomadaire  | 0 cohorte au-dessus        |
| Jeudi après-midi (PAC)        | 0 violation                |
| Sanctuarisation SAE           | 0 violation                |
| Éval → salle A.018            | 11/11 évaluations en A.018 |
| Semaine d'intégration S1      | 0 violation                |
| Ordre pédagogique             | 0/1157 violations          |
| Éval après contenu            | 0/88 violations            |
| Ordonnancement inter-matières | **0/204 violations**       |


Toutes les règles passent, y compris l'ordonnancement (contrairement aux
15/204 non respectées en mode somme pondérée, cf. §12.3) — sur des données
réelles où, pour la première fois depuis la migration d'ingestion (§12.1),
les contraintes enseignants et la sanctuarisation SAE sont effectivement
actives. C'est la première validation "S1 parfait" de ce document qui tienne
compte de toutes les sources de contraintes réellement chargées.

## 13. Retour utilisateur sur la démo visuelle — 6 corrections

Après visualisation de l'export HTML réel (§12.4), retour utilisateur avec
6 points distincts, traités ici.

### 13.1 Bug réel trouvé — capacité de salle jamais vérifiée contre l'effectif

Nouveau rule-check `room_capacity` (`html_view.py::_rule_checks`, réutilise
`solver/rooms.py::_headcount_for_groups` — même calcul que l'affectation
réelle, pas une règle dupliquée) : compare l'effectif de la cohorte affectée
à un créneau à la capacité de la salle qui lui est réellement affectée.
**Résultat sur les données réelles BUT1-S1 : 153 séances en dépassement**,
pas seulement les CM — ex. `WR115-S1-TD-1-but1-td-gh` : 60 étudiants
attendus (effectif `but1-td-gh`) dans H.101 (35 places).

Cause racine (à l'époque) : les effectifs `groups.yaml` (60/TD, 30/TP,
240/promo pour BUT1) étaient **systématiquement surdimensionnés** vs les
salles réelles (H.018 amphi = 150, salles TD standard = 30-36) — signalé
comme point ouvert non résolu en §7.7. Le rule-check a rendu le problème
visible (fail) au lieu de le laisser silencieux (l'affectation de salle
gloutonne retombait sur la plus grande salle disponible sans jamais signaler
le dépassement).

**Résolu depuis** (cf. §7.7 mis à jour) : effectifs réels confirmés par
Kyllian le 05/08/2026 à 30/TD, 15/TP, 120/promo — déjà la valeur présente
dans `groups.yaml` au moment de la confirmation (correction déjà appliquée
à un moment non tracé, git absent sur ce dépôt).

### 13.2 Lissage — compression front-load jugée trop agressive

`_FRONTLOAD_FRACTION=0.6` compressait les séances dans les ~60% premiers de
l'horizon S1 (semaines 2-11 pleines, 12-19 vides sur le run réel). Retour
utilisateur : un vrai lissage sur tout l'horizon est souhaité. Par défaut
relevé à `DEFAULT_FRONTLOAD_FRACTION=1.0` (retour à la 1ère itération
historique, étalement proportionnel par cours sur 100% de l'horizon,
`SolverConfig.spread_frontload_fraction` réglable si un compromis
intermédiaire est voulu plus tard). Ne contredit pas
`objective_function.priorite_1` (finir avant le 1er février reste garanti
par l'horizon lui-même, contrainte dure indépendante) — juste la
distribution interne à cet horizon qui n'est plus compressée artificiellement.

### 13.3 Ordonnancement — vérification durcie et rendue mode-consciente

`_rule_checks` reçoit désormais `tier_values` (déjà présent dans le
`timetable.json` produit par `solve_tiered`, cf. §12.3) : en mode paliers,
une violation d'ordonnancement passe de "info" (repli neutre, mode inconnu)
à **"fail"** — puisque le palier 1 a réellement minimisé puis verrouillé ce
critère à son vrai minimum, une valeur non nulle est une anomalie réelle, pas
un compromis pondéré accepté par construction.

### 13.4 Interface — semaines bloquées désormais affichées

Nouveau `AcademicCalendar.full_week_range(week_offset, n_weeks)` : séquence
CONTINUE de semaines "département" (y compris les semaines bloquées/vacances,
sans index solveur), exposée côté export HTML (`payload.weekRows`). Avant ce
correctif, l'ancien axe (basé sur l'index solveur, qui exclut nativement les
semaines totalement bloquées) sautait silencieusement de "Semaine 9" à
"Semaine 11" sans jamais montrer "Semaine 10 (Toussaint)". Le sélecteur de
semaines (`renderWeekBar` dans `templates/timetable.html`) affiche maintenant
ces semaines bloquées avec un style hachuré distinct. **Non fait dans ce
chantier** : la même continuité côté frontend React (`TimetableCalendar.tsx`)
— l'effort a été concentré sur l'export HTML (le support visuel déjà partagé
avec l'utilisateur) ; à reporter sur le frontend si besoin.

### 13.5 Duo synchronisé confirmé — WR110 (KBR+KNG, FLI+VBU)

Donnée confirmée par l'utilisateur, recoupée avec les vrais enseignants du
module dans `contraintes/07_modules_maquette_progression.json` (WR110 a
exactement 4 enseignants : KBR/KNG/FLI/VBU, correspondant aux 2 duos) :

- Duo 1 : KBR (Kyllian Bresson) + KNG (Kévin Ngo)
- Duo 2 : FLI (Florent Libbrecht) + VBU (Valentin Burette)

Nouveau : `models.entities.TeacherDuo`, `data/config/teacher_duos.yaml`,
`solver/constraints.py::add_duo_synchronized_rare_room_constraints` (contrainte
dure), `solver/rooms.py::_duo_room_overrides` (affectation déterministe
H.017/H.022). **Portée volontairement restreinte aux séances de TP** (pas TD)
— confirmé par l'utilisateur ("tes séances de TP... verrouillées"), et
techniquement nécessaire : un même enseignant a souvent 2 groupes TP au même
`sequence_order` (`nbGpTp=2`), ceux-là restant à des instants différents
(déjà garanti par le NoOverlap enseignant) — synchroniser TOUTES les séances
d'un même ordre entre les deux enseignants (première version, bug) forçait à
tort les 2 groupes d'un même enseignant à un instant identique,
contradictoire avec son propre NoOverlap → `INFEASIBLE` immédiat. Corrigé en
appariant positionnellement (1er groupe de l'un avec le 1er groupe de
l'autre, etc.) : chaque enseignant garde ses groupes à des instants
distincts, seuls les épisodes appariés entre les deux enseignants du duo sont
synchronisés. Vérifié sur données réelles (WR110 seul, 110 séances) :
`FEASIBLE`, KBR≡KNG et FLI≡VBU parfaitement synchronisés par paire de
groupes, aucun chevauchement entre les 2 duos, salle H.017 pour le "1er"
enseignant de chaque duo et H.022 pour le "2e".

**WR112/WR113** (cités comme exemples dans `01_regles_generales.json`) ont
des enseignants **différents** de WR110 (AHA/FME/... et AHA/RDE/... au lieu
de KBR/KNG/FLI/VBU) : leurs duos éventuels, s'il y en a, ne sont pas encore
confirmés — non ajoutés (pas deviné).

### 13.6 `/solve` asynchrone

`POST /solve/async` + `GET /solve/status` : même résolution que `/solve`
(extrait dans `_solve_and_persist`, partagé — aucune différence de logique
ni de qualité), lancée dans un thread d'arrière-plan (OR-Tools libère le GIL
pendant le calcul C++, un thread Python suffit sans bloquer le reste de
l'API) plutôt que de bloquer la requête HTTP jusqu'à 900s. Un seul job actif
à la fois (`AppState` est un état global partagé, pas par utilisateur — un
2e job concurrent écraserait le même état de toute façon, donc rejeté en 409
plutôt que de produire une course). Vérifié via `TestClient` : cycle de vie
complet (running → done avec résultat, running → error avec le détail
`HTTPException` d'origine, rejet 409 en cas de job concurrent).

## 14. Solveur décomposé — ordre → semaine → jour/créneau



### 14.1 Motivation

Même en mode paliers (§12.3), le run complet BUT1-S1 (1437 séances réelles,
contraintes enseignants/SAE effectivement actives depuis §12.1) s'est révélé
**non fiable à budget de temps identique (900s)** : deux runs isolés,
strictement identiques en code et en données, ont donné tour à tour
`FEASIBLE` et `UNKNOWN`. Cause : CP-SAT en recherche parallèle (8 workers)
n'est pas strictement déterministe même à graine fixée — le run complet est
si proche de la limite de ce que 900s permet de résoudre de façon fiable que
le hasard de l'ordonnancement des threads décide de la convergence. C'est
exactement le symptôme de fiabilité/prévisibilité qui avait motivé le
passage à `solve_tiered` (§12.3) — mais à l'échelle du modèle JOINT complet
(1437 séances × ~570 créneaux), même les paliers n'échappent pas à cette
variance.

Piste explorée sur suggestion de l'utilisateur, après recherche (cf. survol
de la littérature sur le "university course timetabling problem" : les
approches en plusieurs étages — résoudre les contraintes obligatoires en
premier, raffiner ensuite — sont une technique reconnue, pas un pis-aller) :
**décomposer le problème en paliers de taille décroissante** plutôt que de
router toujours plus de contraintes dans un seul modèle joint. Écarté en
parallèle : confier le placement à un LLM directement — la littérature 2025
sur les LLM comme solveurs combinatoires confirme qu'ils restent fragiles dès
que les contraintes interagissent fortement, même finement entraînés pour
la tâche ; aucune garantie de correction exacte à cette échelle (1437
séances, des milliers de contraintes dures).

### 14.2 Architecture (`solver/decomposed.py`)

1. **Ordre pédagogique + ordonnancement** : déjà porté par les données
  (`sequence_order`, `metadata["ordonnancement"]`), pas de calcul séparé.
2. **Affectation SEMAINE** (`assign_weeks`) : un CP-SAT réduit, domaine
  ~n_weeks (19) par séance au lieu de ~n_weeks×30 (570) — un ordre de
   grandeur plus petit. Y vivent naturellement : le plafond horaire hebdo
   (dur, direct sur la variable semaine — plus besoin de la trigonométrie
   `add_division_equality` du modèle joint), le plafond hebdo PAR
   ENSEIGNANT (nouveau, cf. §14.3), le lissage/front-load, le regroupement
   des évaluations, et une pénalité molle anti-surcharge SAE (cf. §14.3).
3. **Placement jour/créneau PAR SEMAINE** (`solve_week_detail`) : CP-SAT à
  pleine fidélité (réutilise directement `add_student_and_teacher_no_  overlap`, `add_pedagogical_sequence_constraints`,
   `add_thursday_afternoon_pac_lock`, `add_blocked_calendar_constraints`,
   `add_teacher_availability_constraints`, `add_student_presence_  constraints`, `add_duo_synchronized_rare_room_constraints` — mêmes
   fonctions que le modèle joint, une seule implémentation de référence par
   règle), mais sur un sous-ensemble ~15-20x plus petit (une semaine à la
   fois, ~75-100 séances au lieu de 1437) donc largement dans la zone de
   confort de CP-SAT.

Contrepartie assumée : les arbitrages inter-semaines (déplacer une séance
d'une semaine à l'autre pour mieux combler les trous) ne sont plus possibles
une fois l'étage 2 figé — gain de fiabilité et de vitesse contre un optimum
un peu moins global (en pratique : **0 trou** sur le run final, cf. §14.4 —
chaque semaine, résolue quasi indépendamment, atteint plus facilement son
propre optimum local que le modèle joint n'atteint le sien sur 570 créneaux).

`duo_episode_pairs` (l'appariement des séances synchronisées d'un duo,
initialement interne à `add_duo_synchronized_rare_room_constraints`) a été
extrait en fonction partagée pour être réutilisé par l'étage 2 (même semaine
obligatoire pour les deux membres d'un épisode).

### 14.3 Bugs trouvés et corrigés pendant la mise au point

Six problèmes réels trouvés en vérifiant sur données complètes, dans l'ordre
où ils sont apparus :

1. **Semaine d'intégration S1 non portée à l'étage 2** — `assign_weeks`
  n'interdisait pas la semaine-index 0 pour S1 (contrairement au modèle
   joint) ; 29 séances s'y retrouvaient. Corrigé : `week_var != 0` pour
   toute séance S1 dès que `weeks > 0`.
2. **Plafond hebdomadaire PAR ENSEIGNANT manquant** — seul le plafond
  étudiant (22-23 créneaux) existait à l'étage 2. Un enseignant est aussi
   une ressource NoOverlap (une seule salle à la fois) : sans plafond dédié,
   l'étage 2 a concentré jusqu'à 17 séances de KBR (duo WR110) sur une seule
   semaine — largement au-dessus de ce qu'un seul humain peut couvrir avec
   le verrou jeudi PAC et la pause méridienne. Ajouté : plafond dur à 14
   créneaux/semaine/enseignant (`teacher_weekly_cap_slots`, en dessous du
   maximum théorique FI de 27, pour laisser de la marge à l'étage 3).
3. **Sanctuarisation SAE jamais déclenchée (237 violations)** — la fonction
  partagée `sae_blocked_days_by_parcours` déduit les jours bloqués en
   scannant les séances **présentes dans le lot passé en argument** pour un
   code cours SAE connu. Sur le modèle joint (tout le semestre d'un coup),
   la présence est garantie. À l'étage 3 (une semaine à la fois), rien ne
   garantissait que la séance SAE elle-même atterrisse dans la même semaine
   que ses vraies dates calendaires (l'étage 2 ne contraint pas sa
   semaine) — la sanctuarisation ne se déclenchait donc presque jamais.
   Deux corrections tentées :
  - **Tentative 1 (rejetée)** : forcer la séance SAE elle-même dans sa
  semaine calendaire réelle (contrainte dure à l'étage 2). A rendu
  l'étage 2 **INFEASIBLE** (calendrier SAE BUT1-S1 réel : 8 des 19
  semaines significativement bloquées, trop rigide combiné aux autres
  contraintes dures).
  - **Correction retenue** : calculer `blocked_by_parcours` **une seule
  fois sur tout le semestre** (exactement comme le modèle joint), puis le
  filtrer par semaine à l'étage 3 sans dépendre de la présence d'une
  séance SAE dans le lot — nouvelle fonction
  `_apply_sae_sanctuarization_for_week`, découplée de la position
  réelle de la séance SAE. Résultat : 0 violation, sans toucher à la
  liberté de placement de l'étage 2.
4. **Semaines partiellement bloquées SAE surchargées par l'étage 2** — une
  fois (3) corrigé, 4 semaines restaient en échec même après rééquilibrage
   (7, 9, 13, 14 — précisément celles avec 3-4 jours SAE bloqués sur 5,
   donc seulement 6-12 créneaux réellement disponibles pour les cours
   classiques). L'étage 2 continuait de les remplir jusqu'au plafond
   nominal (22), que l'étage 3 ne pouvait plus caser dans les 1-2 jours
   restants. Rendre le plafond dur et dépendant du nombre de jours bloqués
   a de nouveau rendu l'étage 2 INFEASIBLE (sur-contraignant, même
   diagnostic qu'en (3)). **Solution retenue : pénalité MOLLE**
   (`sae_avoid_weight = 80` × nombre de jours bloqués) plutôt qu'un plafond
   dur — décourage sans jamais interdire l'étage 2 d'utiliser une semaine
   partiellement bloquée si c'est vraiment nécessaire.
5. **Rééquilibrage insuffisant** — `max_moves_per_week` initialement à 15
  (trop bas pour vider une semaine massivement surchargée) relevé à 60, et
   le nombre de passes de rééquilibrage de 3 à 6. Le rééquilibrage exclut
   désormais explicitement les séances SAE elles-mêmes (semaine imposée par
   le calendrier réel, jamais déplacées) et les semaines entièrement
   bloquées SAE comme destination possible (`fully_blocked_weeks_by_  parcours`, sous peine de re-casser la sanctuarisation en déplaçant une
   séance classique dans une semaine 100% SAE).
6. **Semaine vidée par le rééquilibrage comptée comme échec** — si le
  rééquilibrage déplace la totalité des séances d'une semaine en échec
   ailleurs, `solve_week_detail` retourne légitimement `NO_SESSIONS` (rien à
   placer) ; ce statut était traité comme un échec continu au lieu d'un
   succès trivial, laissant la semaine à tort dans `failed_weeks` malgré un
   résultat final entièrement correct. Corrigé en traitant `NO_SESSIONS`
   comme un succès (retrait de `failed_weeks`, aucune entrée dans les
   placements).



### 14.4 Résultat final (BUT1-S1 réel, 1437 séances, duo WR110 actif)


|                                        | Modèle joint (paliers, §12.3)                           | Décomposé (§14)                                          |
| -------------------------------------- | ------------------------------------------------------- | -------------------------------------------------------- |
| Statut                                 | Variable (`FEASIBLE`/`UNKNOWN` selon le run, cf. §14.1) | `FEASIBLE` **reproductible**                             |
| Séances placées                        | 1437/1437 quand feasible                                | **1437/1437**                                            |
| Trous (créneaux)                       | 273                                                     | **0**                                                    |
| Ordonnancement (violations/total)      | 0/204 (vrai minimum, palier verrouillé)                 | 4/204 (molle, niveau semaine)                            |
| Sanctuarisation SAE                    | 0 violation                                             | **0 violation** (vérifié indépendamment, hors dashboard) |
| Ordre pédagogique / éval après contenu | 0 violation                                             | **0 violation**                                          |
| Semaine d'intégration S1               | 0 violation                                             | **0 violation**                                          |
| Duo salle rare (WR110)                 | Non testé à cette échelle (§12)                         | **0 violation**, H.017/H.022 correctement affectées      |
| Temps de calcul                        | Jusqu'à 900s, résultat incertain                        | ~25-30 min mais **résultat fiable**                      |


Le décomposé perd un peu sur l'ordonnancement (4 violations molles au lieu
de 0 garanti) — attendu, l'étage 2 ne compare les positions qu'au niveau
semaine, plus grossier que le palier dédié du modèle joint — mais gagne sur
tout le reste, et surtout sur ce qui manquait : un résultat **reproductible**
plutôt qu'un coup de dé à 900s. Seul point encore en écart avec les données
réelles : `room_capacity` (274 séances où l'effectif de cohorte dépasse la
capacité de la salle affectée, dont les TP WR110 dans le Studio H.017/H.022,
20/16 places pour des groupes de 30) — **point de donnée déjà signalé en
§13.1, toujours en attente de confirmation des effectifs réels**, pas un
défaut du solveur décomposé lui-même.

### 14.5 Câblage

`TimetableSolver.solve_decomposed(...)` (délègue à `solver/decomposed.py`,
même contrat `SolverResult` que `solve()`/`solve_tiered()`) ; `cal-iut solve --decomposed` en CLI et `SolveRequest.decomposed=true` côté API (prioritaire
sur `--legacy-weighted`/`legacy_weighted` si les deux sont fournis). Recommandé
pour tout run BUT1-S1 complet ; `solve_tiered` reste pertinent pour des
sous-ensembles ou des itérations rapides où le modèle joint est déjà fiable.

## 15. Retrait des SAE de l'algorithme + séances "doubles" (TP 3h collés)

Deux changements demandés par l'utilisateur (retour direct) sur le même
chantier S1, tous deux appliqués aux deux moteurs (`solve()`/`solve_tiered()`
dans `cpsat.py` et `solve_decomposed()` dans `decomposed.py`).

### 15.1 Les séances SAE (WSxxx) ne sont plus planifiées par l'algorithme

Constat utilisateur : une SAE est définie par les enseignants eux-mêmes (pas
par le solveur) — les planifier était donc du travail inutile, voire
trompeur (un horaire "proposé" par le solveur n'a aucune valeur si
l'enseignant décide autrement). Seules les **dates calendaires réelles**
d'une SAE (semaine/jour, ex. "WS101 semaine 9") restent utiles : elles
continuent de **sanctuariser** les jours correspondants pour les cours
classiques du même parcours (§8 cahier des charges, inchangé).

- `add_sae_sanctuarization_constraints` (constraints.py) ne dérive plus rien
elle-même à partir des séances passées en paramètre : elle prend désormais
`blocked_by_parcours` déjà calculé par l'appelant.
- Chaque appelant (`cpsat.py::_build_hard_model`, `decomposed.py:: solve_decomposed`) calcule ce `blocked_by_parcours` **une fois, sur la
liste encore WS-incluse**, puis retire les séances WS de `unlocked` avant
toute autre étape. Ordre important : si on filtrait d'abord, plus aucune
séance WS ne serait présente pour indiquer à quel parcours rattacher ses
jours bloqués.
- `assign_weeks` (étage 2 du solveur décomposé) reçoit désormais
`blocked_by_parcours` directement (paramètre), au lieu de le re-dériver
via `sae_days_by_course` en interne — même correction, appliquée à son
propre échelon.
- Piège identifié en écrivant le test de non-régression : le test
`test_sae_sanctuarization_blocks_classic_course_on_sae_day` (tests/
test_policy_constraints.py) était **vide de sens** avant même ce chantier —
il ne passait jamais de séance WS999 réelle dans le lot d'entrée, donc
`sae_blocked_days_by_parcours` ne trouvait jamais de correspondance, sous
l'ancien design comme le nouveau. Corrigé : le test inclut maintenant une
vraie séance WS999 et vérifie à la fois la sanctuarisation ET que la
séance WS999 elle-même est absente de `result.placements`.

Résultat sur le run réel BUT1-S1 : 1389 séances ingérées (WS incluses,
utilisées pour le blocage), 1013 séances classiques effectivement
planifiées — écart cohérent avec le nombre de séances WS du planning SAE.

### 15.2 Séances "doubles" : TP WR110 en blocs de 3h (2×1h30 collées)

Constat utilisateur : certains TP (WR110 en premier, d'autres à venir)
doivent être des blocs continus de 3h, pas 2 créneaux de 1h30 pouvant être
dispersés dans la semaine par le solveur. Le champ `duration_slots` existait
déjà sur `SessionToPlace` mais n'était respecté nulle part dans le pipeline —
chantier pour le rendre réellement effectif, de bout en bout, de façon
générique (pas un correctif spécifique à WR110).

**Déclaration (donnée jamais devinée)** : `data/config/double_sessions.yaml`
— liste de règles `{course_code, session_type, slots_per_session}`, chargées
par `ingestion/config_loader.py::load_double_sessions`. Seule entrée à ce
jour : `WR110 / TP / 2`.

**Fusion à l'ingestion** (`ingestion/normalize.py::_merge_double_sessions`,
appelée depuis `expand_course_to_sessions`) : fusionne par paires
consécutives (ordre pédagogique croissant) les entrées du type ciblé dans
`course.seance_sequence`, avant l'expansion par groupe — chaque paire
devient UNE entrée avec `duration_slots=2`, qui se propage ensuite à TOUS
les groupes TP concernés (la fusion a lieu avant l'expansion, donc uniforme
pour les 8 groupes TP). Un reliquat impair reste en séances simples de 1h30
plutôt que d'inventer un créneau (règle "donnée fraîche").

**Chaîne de corrections côté solveur/salle**, chacune nécessaire pour que
`duration_slots>1` soit réellement respecté partout où une séance est
"occupée" dans le temps :

1. **Domaine du** `start` (`constraints.py::add_duration_domain_constraints`,
  nouveau) : un bloc de N créneaux ne peut démarrer que dans un run de
   créneaux réellement collés dans le temps. Piège trouvé en écrivant les
   tests : la journée n'est PAS un seul bloc de 6 créneaux continus — il y a
   une pause méridienne (12h30-14h00) entre les slots 2 et 3. Un bloc de 2
   créneaux ne peut donc démarrer qu'en {0,1} (matin) ou {3,4} (après-midi),
   jamais en slot 2 (chevaucherait la pause) ni en slot 5 (déborderait sur le
   jour suivant). Généralisé via `_valid_duration_starts(duration)`, pas
   codé en dur pour `duration=2` seulement.
2. **NoOverlap** (`resources.py::add_aliased_no_overlap`) : intervalle créé
  avec la vraie durée (`model.new_interval_var(start, duration, ...)`) au
   lieu d'une longueur 1 fixe — sinon deux séances "doubles" pouvaient se
   chevaucher partiellement sans être détectées. `add_student_and_teacher_  no_overlap` et `add_duo_synchronized_rare_room_constraints` (le duo
   WR110 est justement aussi le cas double-séance) passent désormais un
   dict `durations` par séance.
3. **Créneaux ponctuellement bloqués** (jeudi PAC, dispo enseignant
  récurrente) : `_forbid_slot_for_duration` (nouveau) interdit tout `start`
   dont l'occupation touche le créneau bloqué, pas seulement le `start`
   littéralement égal — sinon un bloc de 2 créneaux pouvait déborder sur un
   créneau interdit sans que son propre `start` soit, lui, dans la liste
   interdite. Les fonctions qui bloquent des **journées entières** (calendrier,
   sanctuarisation SAE, semaine d'intégration S1, présence FC) n'ont pas eu
   besoin de ce correctif : bloquer les 6 créneaux d'un jour interdit déjà
   tout `start` possible ce jour-là, quelle que soit la durée.
4. **Affectation salle** (`rooms.py::assign_rooms`) : occupe et vérifie la
  disponibilité sur TOUS les créneaux du bloc (`_occupied_indices`), pas
   seulement le premier — sinon la 2e moitié d'un TP double pouvait se voir
   attribuer une salle déjà prise par une autre séance à cet instant-là (y
   compris dans le cas du duo, `_duo_room_overrides`).
5. **Rendu HTML** (`export/html_view.py` + `templates/timetable.html`) : le
  payload expose `dur` par séance ; les 3 grilles (Vue Groupe/Enseignant via
   `renderGenericCalendar`, Vue Promo via `renderPromoTab`) rendent une
   séance double avec un `<td rowspan>` couvrant ses créneaux au lieu d'un
   `<td>` vide sur la 2e moitié — sans ça, un TP de 3h ressemblait à un TP de
   1h30 suivi d'un créneau libre, trompeur pour la lecture de l'EDT.
6. **Audit** `weekly_cap` (`html_view.py::_rule_checks`) : comptait 1 par
  placement au lieu de `duration_slots` — sous-estimait la charge réelle
   d'une cohorte ayant des séances doubles. Corrigé pour peser par
   `duration_slots`, même calcul que la contrainte dure du solveur.

Validé sur WR110 seul (62 séances, duo + double-séance combinés) : `FEASIBLE`
62/62, 0 chevauchement de pause méridienne, 0 débordement de jour, 0 conflit
de salle, 0 séance sans salle.

### 15.3 Bug de rééquilibrage trouvé pendant la régénération du run complet

Le premier run complet post-15.1/15.2 est revenu `PARTIAL_WEEKS_FAILED`
(1 puis 3 semaines en échec sur des runs successifs, dont la semaine-index
0 — la semaine d'intégration BUT1, censée rester strictement vide). Cause
trouvée : `_rebalance_failed_weeks` (le rééquilibrage post-échec, §14.3
point 5) vérifie le plafond enseignant/cohorte et le blocage SAE complet
d'une semaine cible (`fits()`), mais **pas** le verrou "semaine
d'intégration S1" — un déplacement pouvait donc légalement pousser une
séance classique en semaine 0, que l'étage 3 ne parvenait ensuite pas à
placer proprement (jours réellement disponibles très réduits cette
semaine-là), consommant en plus un budget de rééquilibrage sur un
déplacement de toute façon voué à l'échec. Corrigé en ajoutant le même
verrou dans `fits()`. Après correctif, run complet BUT1-S1 :
`FEASIBLE`**, 1013/1013 séances classiques placées, 12 trous, 0 jour isolé,
0 violation dure** (room_capacity, weekly_cap, thursday_pac,
sae_sanctuarization, eval_room, s1_integration_lock, pedagogical_order,
eval_after_content — tous `PASS`).

## 16. Interface Groupe/Promo — corrections d'affichage (04/08/2026)

Retour utilisateur sur la démo : trois corrections d'affichage HTML, pas de
changement solveur.

- **Rowspan des séances doubles ne coloriait pas la 2e moitié** : le
`<td rowspan>` introduit en §15.2 ne fonctionnait pas visuellement — la
`<div class="session">` interne a une hauteur fixe par contenu, pas
étirée à la hauteur de la cellule fusionnée, laissant la 2e moitié du
bloc visuellement vide. Corrigé en dupliquant la même séance dans chacune
de ses `dur` cases plutôt que d'utiliser rowspan — chaque case occupée
est alors pleinement coloriée (`renderGenericCalendar` et
`renderPromoTab`, `templates/timetable.html`).
- **Décompte de progression sous-estimé pour un cours à séances doubles** :
`_course_catalog` (onglet Référence) comptait 1 séance par bloc fusionné
au lieu de `duration_slots` — un cours WR110-like affichait "48 TP" au
lieu de "96". Corrigé pour pondérer par `duration_slots` (`html_view.py`).
- **Jours fériés / événements du planning jamais affichés dans la grille** :
`PlanningBundle.blocked_labels` était calculé mais jamais consommé
ailleurs, et `INSTITUTIONAL_EVENTS` (fériés/vacances) n'existait que dans
un onglet séparé. Ajout de `PlanningBundle.events` (labels textuels bruts
non-SAE/non-bloqués du planning officiel — "Rentrée 09h00", "Intégration",
"VSS 10h00-12h0", etc., cf. `planning_loader.py::_parse_planning_weeks`)
et de `AcademicCalendar.date_to_week_day_any` (localise une date même si
elle est fériée — `date_to_week_day` renvoie toujours `None` pour ces
dates par construction). Affichés dans la grille (badge "Férié"/"Vacances"
ou "événement") dès qu'une case serait sinon vide.
- **Vue Promo n'affichait pas le type de cours** : ajout d'un `<span class="ty">`
(CM/TD/TP + durée si double-séance) dans le chip promo.



## 17. Données S3-CREACOM-FC + duo WR110 + PPP WR119 (04/08/2026)



### 17.1 Vérification/correction S3-CREACOM-FC (retour utilisateur détaillé)

L'utilisateur a fourni le détail complet des 19 modules WRA30xM/WRA31xM
(BUT2-CREACOM-FC, S3) : enseignant, volumes CM/TD/TP. Recoupement avec
`data/exports/maquette.json` : 18/19 déjà corrects. Un seul écart réel —
**WRA304M "Culture numérique"** assigné à ARA (Anthony Rageul) dans la
maquette source, alors que l'enseignant réel est **JTH (Jérôme Thomas)**.
(WRA303M a un écart apparent — `lead`=ALO alors que l'enseignement réel est
JHU — mais `profs[0]` avait déjà JHU, donc aucun impact fonctionnel : le
solveur lit `profs`, pas `lead`, pour l'affectation TD/TP.)

Comme `data/exports/maquette.json` est récupéré depuis une source distante
(`mmi23x02.mmi-troyes.fr`, écrasée à chaque `cal-iut fetch`), un edit direct
du JSON aurait été perdu au prochain fetch. Nouveau mécanisme durable :
`TeacherCorrection` (modèle), `data/config/course_corrections.yaml`,
`merge.py::apply_teacher_corrections` — appliqué juste après la fusion
maquette+progression dans `run_ingestion`. `correct_teacher_code` est
résolu par recoupement avec n'importe quel autre cours utilisant déjà ce
code (jamais ressaisi nom/prénom à la main).

Structure de groupes CREACOM-FC (1 TD + 1 TP, mode "Solo" — un seul
enseignant sur l'intégralité du TD+TP de chaque module) déjà correcte dans
`groups.yaml`, mais labellisée génériquement ("TD CREACOM FC" / id `-td-1`).
Renommé en `TD GH` / `TP G` (id `-td-gh` / `-tp-g`) pour correspondre au
nommage réel confirmé par l'utilisateur, cohérent avec la convention
lettrée BUT1/BUT2-DEV-FI.

**BUT2-DEV-FC (Développement Web, alternance)** : confirmé par l'utilisateur
comme "en veille" (gelé) pour 2026-2027, effectif d'alternants insuffisant.
Vérifié : 0 cours pour ce parcours dans la maquette source cette année —
déjà naturellement ignoré par le solveur (aucun cours = aucune séance
générée), aucun changement de code nécessaire. Structure conservée en
commentaire dans `groups.yaml` pour une réouverture future (TD "EF", TP "E"/"F").

### 17.2 Retour Kyllian Bresson (04/08/2026, transcript relayé)

**Réaffectation groupes TP du duo WR110** : l'affectation par défaut
(curseur séquentiel sur les blocs `profs`, cf. `normalize.py:: _teacher_for_group`) donnait KBR=A,B / KNG=C,D / FLI=E,F / VBU=G,H — ce qui,
combiné à l'appariement positionnel de `duo_episode_pairs` (trie les ids de
chaque enseignant et les apparie par position), produit des épisodes
co-animés "boiteux" : A&C puis B&D (pas de correspondance visuelle avec un
regroupement TD naturel). Demande : KBR=A,C / KNG=B,D / FLI=E,G / VBU=F,H,
pour que l'épisode co-animé lise "A&B" (cohérent avec TD AB), puis "C&D"
(cohérent avec TD CD).

Nouveau mécanisme générique : `TeacherDuo.group_overrides` (dict code
enseignant -> lettres de groupe), `data/config/teacher_duos.yaml`,
`normalize.py::_duo_teacher_for_group` — appelé en premier dans
`_teacher_for_group`, avant le curseur séquentiel par défaut. Validé sur
données réelles : `but1-tp-a→KBR, tp-b→KNG, tp-c→KBR, tp-d→KNG, tp-e→FLI, tp-f→VBU, tp-g→FLI, tp-h→VBU` — exactement la demande.

**Délai PPP WR119** : "je préfère qu'ils aient le temps de passer quelques
semaines à l'IUT avant que l'on aborde avec eux le PPP S1". Nouveau
mécanisme générique : `CourseMinWeekRule`, `data/config/ course_scheduling_rules.yaml`, `solver/constraints.py:: add_course_min_week_constraints` (modèle joint) + contrainte équivalente
dans `decomposed.py::assign_weeks` (étage 2, même logique que le verrou
semaine d'intégration S1). D'abord fixé à `min_week=4` (3 semaines de
battement, lecture initiale de "quelques semaines"), puis réduit à
`min_week=3` (2 semaines) après diagnostic empirique — cf. §17.3, "quelques
semaines" n'étant pas un chiffre exact donné par l'utilisateur.

### 17.3 Diagnostic fiabilité — semaines à charge exacte du plafond

Après §17.1/17.2, plusieurs runs BUT1-S1 complets consécutifs sont revenus
`PARTIAL_WEEKS_FAILED` (1 à 4 semaines), avec un temps de résolution monté
jusqu'à ~3h sur le run joint multi-parcours (§18) — bien au-delà du budget
habituel (quelques minutes à ~40 min).

**Cause structurelle identifiée** : diagnostic direct sur l'étage 2 seul
(`assign_weeks`, rapide, pas de résolution complète) — une semaine en échec
avait ses **8 cohortes TP à EXACTEMENT 22/22** (le plafond dur FI), contre
19/22 pour une semaine sans difficulté et 21-22/22 pour une semaine
intermédiaire. Une semaine où chaque cohorte est à charge pile plafond ne
laisse aucune marge à l'étage 3 pour composer avec le verrou jeudi PAC (3
créneaux FI en moins) et le NoOverlap enseignant/cohorte — ce n'est pas de
la malchance de seed, c'est un vrai goulot structurel.

**Tentatives de correctif, dans l'ordre, avec résultats empiriques** :

1. Retry par diversité de seed au lieu de budget×3 sur chaque semaine en
  échec (`_solve_week_with_retry` : (budget normal, seed A), (budget
   normal, seed B), (budget×3, seed C) au lieu de (budget, budget×3) sur la
   même seed) + filet final de 3 tentatives supplémentaires après les 6
   rounds de rééquilibrage (`solve_decomposed`). **N'a pas résolu** : test
   S1 seul toujours `PARTIAL_WEEKS_FAILED` après 42 min (contre un run
   normal de quelques minutes).
2. `stage2_cap_margin` : plafond légèrement plus strict côté étage 2 (défaut
  testé : 2 créneaux de moins que le vrai plafond) pour forcer de la marge
   structurelle. **N'a pas clairement aidé** : a simplement déplacé la
   semaine qui coince (résultats bruyants sur 5 runs : 4, 3, 2, 1, 3
   semaines en échec) — hypothèse retenue : réduire la capacité PAR semaine
   à volume total inchangé peut aussi durcir l'étage 2 lui-même (doit
   étaler davantage un volume déjà tendu).
3. Relâchement de `min_week` WR119 de 4 à 3 (§17.2) : contribue à la
  tension (60 créneaux WR119 concentrés sur 15 semaines au lieu de 18 avec
   min_week=4) mais pas la seule cause — amélioration partielle et bruitée
   (2, 1, 3 semaines en échec sur 3 runs après relâchement).
4. `stage2_cap_margin` **désactivé (remis à 0, défaut actuel)** : run
  suivant `FEASIBLE`, 1004/1004 placées, **0 trou**, 0 jour isolé — la
   marge de capacité était probablement nette négative, pas juste neutre.
   Retenu comme défaut ; gardé configurable (paramètre `solve_decomposed`)
   pour retester isolément si besoin, plutôt que supprimé.

**Conclusion opérationnelle** : le run BUT1-S1 seul reste occasionnellement
sujet à variance CP-SAT (retry manuel utile, filet interne de 2 tentatives
insuffisant à lui seul dans ~40% des runs observés ce jour-là) — traiter
comme un job d'arrière-plan (`/solve/async` déjà prévu à cet effet), pas une
opération interactive instantanée. Le mécanisme seed-diversity (point 1)
est conservé (changement neutre à légèrement positif, pas clairement nocif
contrairement à `stage2_cap_margin`).

## 18. Run global multi-parcours (retour utilisateur, 04/08/2026)

Retour utilisateur : "il faut que tu fasses les choses nécessaires pour que
les parcours fonctionnent tous ensemble" — un seul run global (confirmé, pas
des runs séparés par parcours) pour garantir qu'un enseignant partagé entre
plusieurs parcours n'est jamais programmé à 2 endroits en même temps, ce
qu'un run par parcours indépendant ne peut structurellement pas détecter.

**Clé architecturale** : `semester_week_offset`/`default_horizon_weeks`
renvoient déjà des valeurs **identiques** pour S1/S3/S5 (semestres impairs,
démarrage début septembre, horizon calé sur le même 1er février 2027) et
pour S2/S4/S6 (semestres pairs) — ces 3 semestres de chaque groupe partagent
donc déjà le même axe temporel par construction, sans code supplémentaire.
Combiner tous les parcours d'un groupe de semestres concurrents dans un
seul `solve_decomposed(...)` suffit : pas besoin d'un mécanisme d'axe
temporel partagé séparé.

**Câblage** : `ingestion/pipeline.py::SEMESTRE_GROUPS`
(`{"odd": {S1,S3,S5}, "even": {S2,S4,S6}}`) + `SEMESTRE_GROUP_ANCHOR`
(`{"odd": "S1", "even": "S2"}`) — source unique, importée par `cli.py` et
`api/main.py`. `run_ingestion(..., semestre_group="odd")` ingère tous les
parcours (aucun filtre parcours/semestre) puis filtre les séances au groupe
demandé. `cal-iut ingest --semestre-group odd` / `cal-iut solve --semestre-group odd` (CLI) et `IngestRequest.semestre_group` /
`SolveRequest.semestre_group` (API) exposent le même mécanisme.

**Validation empirique (Groupe A = S1+S3+S5, tous parcours actifs sauf
BUT2-DEV-FC gelé)** : 3108 séances ingérées (dont SAE), 2379 séances
classiques — `FEASIBLE`, **2379/2379 placées** (0 écart réel, les 729
"manquantes" sont exactement les séances SAE exclues par design, cf. §15.1),
**0 conflit enseignant, y compris 0 conflit entre parcours différents**
(vérifié explicitement : un même enseignant sur 2 parcours n'est jamais
programmé au même horaire) — exactement la garantie recherchée. Temps de
résolution : ~3h (avant le diagnostic §17.3 ; probablement plus rapide
depuis, non re-mesuré à cette échelle par manque de temps ce jour).

**Non fait à ce jour** : re-validation du Groupe A à pleine échelle avec
tous les correctifs de §17.3 (coûteux, plusieurs heures) ; validation du
Groupe B (S2+S4+S6) ; régénération de l'export web pour un run global (fait
uniquement pour BUT1-S1 seul jusqu'ici, cf. §19).

## 19. Interface web réelle — remplacement d'Artifact (retour utilisateur, 04/08/2026)

Retour utilisateur : "je voudrais arrêter d'utiliser des Artifact mais faire
une vraie interface web générée dans le projet, par contre je veux garder
exactement l'UI que tu a produit."

Nouvel endpoint `GET /` sur l'API FastAPI (`api/main.py::timetable_view`) :
sert le rendu HTML EXACT de `export/html_view.py::build_and_render` (même
template `templates/timetable.html`, aucune duplication), généré en direct
depuis l'état courant du serveur (dernier `POST /solve`) plutôt qu'un
fichier statique republié. `AppState` étendu avec `last_status`/
`last_objective_value`/`last_gap_penalty` (le solve les enregistre, la vue
web les affiche au lieu d'un "CACHED"/None trompeur).

Testé de bout en bout (`cal-iut serve` local, `POST /ingest` → `POST /solve/async` → `GET /solve/status` → `GET /`) : 200 OK, toutes les
fonctionnalités présentes (chips promo, journées SAE/fériés/événements,
onglet Contraintes).

**Mise à jour (05/08/2026)** : sur demande explicite, Artifact est finalement
republié EN PLUS de l'interface interne (pas remplacé) à chaque étape
notable — les deux canaux coexistent. Nouveau helper de déploiement rapide
(`scratchpad/load_run_to_db.py`, script one-off, pas dans le repo) : charge
un `data/generated/timetable.json` déjà résolu par le CLI directement dans
la base du serveur (`PlanningRepository.save_run`) — évite de re-résoudre
depuis zéro juste pour afficher un run déjà obtenu ; repris automatiquement
au démarrage par `_try_restore_latest`.

## 20. Blocage réel des événements du planning (retour utilisateur, 05/08/2026)

Retour utilisateur : "17h / 18H30 Présentation des services aux nouveaux
étudiants / 9h30 Echange IA / Cela n'est pas respecter les 2 créneaux ne
sont pas bloqué" — ces événements (déjà affichés dans la grille depuis §16)
n'étaient qu'informatifs : rien n'empêchait le solveur de placer un cours
classique en même temps.

**Extraction d'horaire** : `planning_loader.py::_slots_for_event_text`
cherche les motifs `\d{1,2}[h:]\d{0,2}` dans le libellé brut d'un événement
et calcule l'intersection avec les 6 bornes horaires des créneaux de 1h30.
Un seul horaire trouvé (ex. "9h30 Echange IA") bloque le créneau qui le
contient ; deux horaires (ex. "17h / 18H30 Présentation...", "VSS
10h00-12h0") bloquent tous les créneaux chevauchant l'intervalle
[min, max] — "VSS 10h00-12h0" bloque ainsi 2 créneaux (9h30-11h ET
11h-12h30). Un événement **sans** horaire explicite (ex. "Rattrapages",
"Clés de Troyes") n'est jamais bloqué, seulement affiché — règle "donnée
fraîche" : on ne devine pas un créneau non indiqué. Validé sur les vraies
données S1 : exactement `{(semaine1, mardi, slot 9h30-11h),
(semaine1, mardi, slot 17h-18h30), (semaine2, jeudi, slot 9h30-11h),
(semaine2, jeudi, slot 11h-12h30)}` — correspond précisément aux 2 créneaux
signalés par l'utilisateur (+ VSS, repéré au passage).

**Contrainte dure** : `constraints.py::add_planning_event_block_constraints`
(grain du créneau, pas du jour entier comme la sanctuarisation SAE) — câblée
dans le modèle joint (`cpsat.py::_build_hard_model`, auto-chargée comme les
fenêtres SAE via `SolverConfig.enforce_planning_events`, défaut `True`) et
dans l'étage 3 du solveur décomposé (`decomposed.py::solve_week_detail`,
calculée une fois globalement dans `solve_decomposed` puis tranchée par
semaine comme `blocked_by_parcours`).

**Régression trouvée et corrigée** : `enforce_planning_events=True` par
défaut a fait échouer `test_thursday_afternoon_locked_for_fi` — ce test
isole une seule contrainte sur des séances synthétiques ("WRX"), mais le
nouveau blocage charge les VRAIES données S1 par défaut (comme les drapeaux
SAE), donc un créneau réel bloqué en semaine 0/1 suffisait à faire passer un
test à la limite de capacité (27 séances / 27 créneaux dispo) en
`INFEASIBLE`. Corrigé en ajoutant `enforce_planning_events=False` à
`_base_config()` (tests/test_policy_constraints.py), même traitement que les
2 drapeaux SAE déjà présents — les tests utilisant de vraies données BUT1-S1
(test_solver.py, test_html_export.py, test_student_cohort.py) n'ont pas
besoin de ce correctif, le chargement réel y est déjà pertinent.

Validé sur le run complet BUT1-S1 régénéré : `FEASIBLE`, 1004/1004,
0 trou, 0 violation dure (8/8 règles `PASS`), et confirmation directe que les
2 créneaux signalés sont désormais vides de tout cours classique.

## 21. Run global multi-parcours — câblage CLI/API + validation finale (05/08/2026)

Suite du §18 (architecture) : câblage effectif en CLI et API, puis
re-validation à pleine échelle avec tous les correctifs des §17.3/§20.

`ingestion/pipeline.py::SEMESTRE_GROUPS`/`SEMESTRE_GROUP_ANCHOR` déplacés
depuis `cli.py` (source unique, importée aussi par `api/main.py`).
`run_ingestion(..., semestre_group="odd"|"even")` ingère tous les parcours
puis filtre les séances au groupe demandé — remplace un filtrage post-hoc
dupliqué dans `cli.py`.

- **CLI** : `cal-iut ingest --semestre-group odd` / `cal-iut solve
  --decomposed --semestre-group odd`. Le semestre "ancre" du groupe (S1 pour
  odd, S2 pour even) résout calendrier/horizon pour `solve_decomposed`.
- **API** : `IngestRequest.semestre_group` / `SolveRequest.semestre_group`,
  `AppState.semestre_group` (persisté par `/ingest`, relu par `/solve` et
  `GET /` pour résoudre le semestre ancre si `filter_semestre` est vide).
- **Restauration DB** : `PlanningRun.parcours`/`.semestre` ne sont pas
  nullable (pas de migration de schéma pour ce chantier) — un run
  multi-parcours restauré au démarrage (`_try_restore_latest`) est donc
  encodé via un sentinel reconnu dans la colonne `semestre` ("ODD"/"EVEN",
  distinct des vraies valeurs "S1".."S6"), qui déclenche `run_ingestion(...,
  semestre_group=...)` au lieu du filtre parcours/semestre normal.

**Re-validation à pleine échelle (Groupe A, tous les correctifs du jour)** :
3108 séances ingérées, 2379 classiques. 4 tentatives avant convergence
(`PARTIAL_WEEKS_FAILED` sur 5, puis 1, puis 2, puis 3 semaines — bruyant,
même profil que le run BUT1-S1 seul du §17.3, à plus grande échelle) puis
**`FEASIBLE`** : 2379/2379 placées, 126 trous, 3 jours isolés (qualité molle
en retrait par rapport au run BUT1-S1 seul à 0 trou — attendu, problème
~2,4x plus gros), **0 conflit enseignant, y compris 0 conflit entre
parcours différents** (revérifié explicitement après re-run), couverture
salle 100%. **8/8 règles dures `PASS`** (room_capacity, weekly_cap,
thursday_pac, sae_sanctuarization, eval_room, s1_integration_lock,
pedagogical_order, eval_after_content) sur les 6 parcours actifs combinés
(BUT1 1004, BUT2-DEV-FI 587, BUT2-CREACOM-FC 190, BUT3-DEV-FI 252,
BUT3-DEV-FC 173, BUT3-CREACOM-FC 173 séances placées).

Chargé dans l'interface web (`scratchpad/load_run_to_db.py` + sentinel
"ODD") et republié sur Artifact — `GET /meta` confirme les 6 parcours
visibles, le payload contient bien les groupes BUT2/BUT3.

**Non fait à ce jour** : Groupe B (S2+S4+S6) jamais validé, ni à l'ancien ni
au nouveau code.

## 22. Interface — sélecteurs par année, Vue Promo unifiée (retour utilisateur, 05/08/2026)

Trois retours successifs sur l'interface interne (`timetable.html`), suite au
run Groupe A (6 parcours actifs, l'ancien affichage par parcours seul devenait
illisible) :

- **Sélecteurs regroupés par année/parcours** (pas juste par type
  promo/TD/TP) : `groupSelect` (Vue Groupe) prend un `<optgroup>` par
  parcours au lieu d'un par kind — à 6 parcours actifs, "TD AB"/"TP A"
  apparaissaient à l'identique sous plusieurs parcours (BUT1, BUT2-DEV-FI,
  BUT3-DEV-FI), sans repère. `yearPrefixOf(parcours)` (regex `^BUT(\d)`)
  sert de clé de tri commune.
- **Vue Promo unifiée** : suppression du sélecteur de parcours individuel,
  remplacé par un tableau UNIQUE montrant TOUS les parcours actifs
  ensemble (retour : "il faudrait que l'on voit sur le même tableau toutes
  les promo les 3 années") — 19 colonnes pour le run Groupe A. En-tête à
  2 niveaux (bande `colspan` par parcours + libellé de groupe en dessous),
  et séparation visuelle : chaque parcours a sa propre teinte (6 couleurs du
  thème existant, cycliques) + trait plus épais en début de parcours, sur
  toute la hauteur du tableau.
- **Ordre FI avant FC** : les parcours FC (formation continue) de 2e/3e année
  doivent apparaître APRÈS les FI de la même année (retour utilisateur),
  pas dans l'ordre alphabétique brut (qui mettait "CREACOM-FC" avant
  "DEV-FI" car C < D). `compareParcoursForDisplay` : tri année, puis
  `isFcParcours(pc) = pc.includes('FC')` comme second critère, appliqué à
  la fois au `groupSelect` et à la Vue Promo.

Tout vérifié en simulant la logique JS extraite (`node`) contre le vrai
payload servi par le serveur, pas seulement un check de syntaxe — méthode
reprise pour tout le reste de ce chantier (§23).

## 23. Édition manuelle du planning — verrou passé/en cours, exceptions, régénération ciblée, glisser-déposer, dashboard (retour utilisateur, 05/08/2026)

Besoin exprimé : une fois le planning publié, pouvoir le corriger à la marge
(enseignant absent, cours à déplacer) sans tout recalculer, **sans jamais
pouvoir toucher une semaine déjà passée ou en cours**, et avec une interface
réorganisée en dashboard (même thème visuel, agencement différent). Feuille
de route détaillée dans un plan dédié avant implémentation (`EnterPlanMode`,
approuvé par l'utilisateur) — résumé ci-dessous.

**Calendrier** (`calendar/academic.py`) : `current_relative_week(calendar,
semestre, today=None)` résout la date du jour en index de semaine relatif
(retombe sur le prochain lundi enseignable si `today` tombe un week-end/
vacances) ; `week_status(calendar, semestre, week_index, today=None) ->
"past"|"current"|"future"`. Seules les semaines `"future"` sont
éditables/régénérables — appliqué aussi bien côté serveur (garde-fou réel)
que côté client (weekbar grisée, tooltip).

**Nouvelle table DB** `ScheduleException` (`db/models.py`) : exceptions
ponctuelles (`teacher_absence`, `room_unavailable`) par date absolue,
soft-delete (`active`, cohérent avec `Correction` jamais supprimée). Nouvelle
méthode repository `upsert_current_placements` : upsert CIBLÉ par
`session_id`, délibérément SANS le `.delete()` global que fait `save_run` —
sécurité centrale du chantier (une régénération partielle ne doit jamais
pouvoir raser tout `CurrentPlacement`).

**Solveur** (`solver/decomposed.py`) : `solve_week_detail` généralisé de
"1 semaine fixe" à `num_weeks` semaines JOINTES (1 ou 2), avec deux nouveaux
paramètres :
- `fixed: dict[session_id, créneau_local]` — séances verrouillées dans la
  portée régénérée : incluses dans le modèle (comptent dans les NoOverlap)
  mais leur `session_starts` est figé par une contrainte d'égalité, jamais
  omises comme le fait `solve_decomposed` au niveau global (qui exclut
  entièrement les séances `locked` du modèle — sûr uniquement pour des
  verrous isolés, pas pour "geler 15 semaines pendant qu'on en régénère 2").
- `allowed_weeks: dict[session_id, {semaines locales admissibles}]` —
  calculé via `_build_sequence_neighbors`/`_movable_bounds` (déjà existants,
  utilisés par le rééquilibrage étage 3), pour qu'une séance ne puisse
  jamais migrer vers l'autre semaine si ça violerait l'ordre pédagogique
  avec un voisin hors de la fenêtre régénérée.

Un vrai bug corrigé au passage : `_apply_sae_sanctuarization_for_week`
calculait `base = day * SLOTS_PER_DAY` sans tenir compte de la semaine
locale — pour un lot à 2 semaines jointes, ça bloquait implicitement le même
jour dans LES DEUX semaines locales au lieu de la seule concernée. Signature
corrigée en `dict[parcours, {(semaine_locale, jour)}]`.

Nouvelle contrainte `add_teacher_weekly_hour_cap_constraints`
(`solver/constraints.py`, jumelle de `add_weekly_hour_cap_constraints` mais
par enseignant) : nécessaire uniquement quand `num_weeks > 1`, car le
plafond hebdo enseignant n'est garanti par l'étage 2 (`assign_weeks`, cap
20 par défaut — divergence préexistante avec le `14` de
`solve_decomposed`, non liée à ce chantier, tranchée pour 20 ici) que tant
qu'une séance ne change pas de semaine.

Les exceptions ponctuelles réutilisent un mécanisme **déjà existant** côté
solveur (`TeacherAvailability.metadata["forbidden_dates"]`, cf. §20) — aucun
changement solveur nécessaire pour ça, juste la persistance/API/UI.

Testé isolément (script scratch, avant tout branchement API) : 2 semaines
jointes + exception enseignant → migration correcte vers la semaine libre ;
`fixed` → séance immobile au créneau imposé ; `allowed_weeks` restrictif →
`INFEASIBLE` (confirme que la contrainte mord) ; sanctuarisation SAE
multi-semaines → jour bloqué respecté dans la bonne semaine locale
uniquement ; plafond hebdo enseignant joint → répartition correcte sur les
2 semaines.

**API** (`api/regen.py`, nouveau fichier — `main.py` faisait déjà 735
lignes) : `POST /regen/week` (`{week, extend_next}`, job asynchrone même
patron que `/solve/async` — thread + verrou global, PARTAGÉ avec le verrou
solve existant), `GET /regen/status`, `POST/GET/DELETE /exceptions`,
`GET /weeks/status`. Garde-fou explicite dans `regen_and_persist` : avant
persistance, vérifie que chaque id retourné appartient à la portée calculée
en amont, sinon lève une erreur plutôt que d'écrire. `assign_rooms`
(`solver/rooms.py`) étendu avec `course_cm_room_seed` : une régénération
partielle seed la règle `same_room_for_course` avec la salle déjà utilisée
par le même cours HORS de la fenêtre régénérée, pour ne pas faire changer de
salle un cours qui n'a pas changé de semaine.

Rattrapage sur l'endpoint unitaire existant (`PATCH /placements/{id}`,
`POST /placements/{id}/validate`) : n'avait jusqu'ici aucune conscience de la
date réelle — un simple déplacement (futur glisser-déposer) aurait pu
toucher une séance déjà passée. Ajout de `_check_move_editable` (vérifie
`week_status` sur la semaine SOURCE et DESTINATION), 409 sinon.

Validé en conditions réelles sur le run Groupe A (port 8123) : exception
enseignant KBR sur un lundi précis → régénération de la semaine → KBR
effectivement à 0 séance ce jour-là (toutes ses séances redistribuées sur
les 4 autres jours) ; tentative de régénération/déplacement sur la semaine
en cours → rejetée (409) ; régénération jointe sur 2 semaines (328 séances)
→ `FEASIBLE`, séances réparties sur les deux semaines comme attendu.

**Frontend** (`export/templates/timetable.html`, nouvel onglet "Vue
Semaine") : glisser-déposer natif HTML5 (pas de librairie, cohérent avec le
reste du fichier — 100% vanilla JS, aucune dépendance externe). Une séance
verrouillée reste affichée (cadenas) mais non déplaçable. Sur dépôt, un seul
`PATCH /placements/{id}` ; en cas de conflit (409), le détail renvoyé par
`validate_move` est affiché avec une option "forcer". Panneau latéral :
liste des exceptions + formulaire de création, contrôles de régénération
("cette semaine" / "+ semaine suivante") avec sondage de `GET /regen/status`
(`setInterval`, même sémantique que le job serveur). Après toute action
(déplacement, régénération), `payload.rows` est mis à jour EN MÉMOIRE par id
et tous les onglets sont ré-affichés sans recharger la page.

**Réagencement dashboard** (même thème visuel, agencement différent) :
Vue Semaine devient le 1er onglet (surface actionnable avant les vues de
lecture) ; le panneau "Calendrier institutionnel" quitte le haut de page
pour devenir un 3e sous-onglet de Référence ; un indicateur "prochaine
semaine modifiable" apparaît dans l'en-tête à côté du statut.

**Non couvert dans cette itération** (priorisation assumée, cf. plan) :
exceptions `room_unavailable` acceptées côté schéma/DB mais pas encore
propagées dans le solveur (seul `teacher_absence` agit réellement sur la
régénération) ; pas de 3e type d'exception (indisponibilité ad hoc d'un
groupe entier) ; test réel du glisser-déposer limité à une simulation de la
logique JS contre le vrai payload (`node`, pas de navigateur dans cet
environnement) — l'API sous-jacente est, elle, entièrement vérifiée en
conditions réelles.

## 24. Indisponibilités enseignants non résolues — 3 corrigées, 1 réellement ambiguë (retour Kyllian, 05/08/2026)

Question posée sur DAN ("l'algo n'a pas compris tous les jours ?") : vérifié
en rechargeant `load_all_constraints` — DAN a 3 tokens hebdomadaires
("lundi matin", "mardi de 15h30 à 18h30", "vendredi après-midi"). Seul le 2e
échouait (`moment: "plage_horaire_precisee_dans_raw"`, un horaire précis que
`parse_teacher_constraints_json` refusait — à raison — de deviner à partir
d'un `moment` non catégorisé). En listant TOUS les `unresolved_tokens` du
fichier (mécanisme déjà présent, `TeacherAvailability.metadata`, mais jamais
affiché nulle part jusqu'ici), 3 autres enseignants dans le même cas :

- **DAN** "mardi de 15h30 à 18h30" — horaire borné explicite.
- **AFR** "les jeudis après 17h00" — horaire à borne ouverte.
- **KNG** "du lundi 2 au vendredi 6 novembre 2026" — plage de dates dont la
  borne de début n'a pas de mois propre (convention française : le mois
  n'est précisé qu'une fois, sur la fin).
- **ARA** "1 ou 2 semaines /mois" — **génuinement ambigu** (quelles
  semaines précisément ?), volontairement laissé non résolu — à demander
  directement à Anthony Rageul, pas une supposition possible.

Corrigé pour les 3 premiers (`ingestion/constraints_loader.py`) :
- `_slots_for_open_ended_time` (nouveau) : gère les bornes OUVERTES
  ("après HHhMM" = tout créneau dont la fin dépasse l'heure citée, pas
  seulement celui qui la contient — distinct de `_slots_for_event_text`
  pensé pour des plages bornées).
- Le cas `recurrent_hebdomadaire` avec `moment` non catégorisé retente via
  `_slots_for_open_ended_time` puis `_slots_for_event_text`
  (`planning_loader.py`, déjà utilisé pour les événements du planning
  officiel — réutilisé tel quel, pas dupliqué) avant d'abandonner.
- Le cas `autre_a_interpreter` (pas de `jour` structuré, contrairement à
  `recurrent_hebdomadaire`) fait de même, mais seulement si un nom de jour
  ET un horaire explicite sont TOUS LES DEUX trouvés dans le texte brut —
  sinon reste non résolu (règle donnée fraîche).
- `_parse_date_token` : la plage "du X au Y" emprunte le mois/année de la
  borne de fin à la borne de début si celle-ci n'en a pas.

Vérifié : DAN/AFR/KNG passent bien de `unresolved_tokens` non vide à vide,
avec les bons créneaux/dates ajoutés (ex. KNG : `forbidden_dates` contient
maintenant 2026-11-02 à 2026-11-06 inclus). ARA reste correctement non
résolu. `pytest tests/test_constraints_data.py tests/test_planning_loader.py`
: 9/9 passent après le changement.

**Gap distinct repéré au passage, non corrigé** : Régis Huez (RHU) a une
absence ponctuelle réelle ("du mardi 19 octobre au vendredi 22 octobre 2026,
conférence à Marseille") mentionnée uniquement dans `explications_raw`
(texte libre), SANS token `date_specifique` correspondant dans
`indisponibilites_tokens` — donc non appliquée par le solveur aujourd'hui.
Nécessite soit une correction du JSON source (`contraintes/05_...json`,
si c'est bien la source canonique et pas un fichier resynchronisé
automatiquement — à confirmer), soit un mécanisme de correction durable
similaire à `TeacherCorrection`/`course_corrections.yaml` (§17) si le
fichier est écrasé à chaque resync.

## 25. Suivi des réponses Kyllian (05/08/2026) — effectifs, CM/TD/TP, duos WR112/WR113, plafond enseignant, absence RHU

**Effectifs BUT1 confirmés** : 30/TD, 15/TP, 120/promo (cf. §7.7, §13.1 mis à
jour) — correspond déjà à `groups.yaml`, aucun changement de config.

**Synchronisation CM stricte — testée puis abandonnée.** Retour Kyllian :
"les CM doivent être faits quand tous les groupes ont eu le même nombre de
TD et TP", contrairement à l'hypothèse initiale du projet (pacing souple
"sans gravité" entre sous-groupes). Implémenté en contrainte DURE,
symétrique (CM après le dernier contenu de CHAQUE cohorte réelle ET avant
son premier contenu suivant), aux deux niveaux concernés :
`constraints.py::add_pedagogical_sequence_constraints` (modèle joint/étage 3)
ET `decomposed.py::assign_weeks` (étage 2 — nécessaire car c'est CETTE
étage qui décide dans quelle SEMAINE tombe chaque séance ; l'étage 3 ne voit
qu'une semaine à la fois, insuffisant seul). Vérifié correct sur un cas
synthétique multi-cohorte (le CM attend bien le sous-groupe le plus lent,
dans les deux sens).

**Testé sur BUT1-S1 réel (1380 séances)** : `PARTIAL_WEEKS_FAILED` sur 5
semaines (2, 3, 7, 8, 9) après ~50 min, 782/1380 séances seulement — pas un
bug (l'affectation semaine réussit, c'est le placement jour/créneau qui
devient trop contraint sur certaines semaines), une vraie dégradation de
fiabilité, exactement le risque que l'ancien commentaire du code redoutait.

**Décision utilisateur (après consultation, AskUserQuestion)** : revenir à
la version molle plutôt que d'investir sur la fiabilité ou passer en
pondéré — code entièrement reverté à l'état d'avant cette tentative,
historique gardé en commentaire dans les deux fichiers pour ne pas retenter
la même chose sans le savoir. Le différentiel de rythme reste donc toléré
entre sous-groupes en pratique.

**WR112/WR113 en salle collée — confirmé et implémenté.** Duos fournis par
Kyllian, vérifiés cohérents avec les enseignants réels du module
(`maquette.json` : WR112 = AHA/FLI/FME/RDE, WR113 = AHA/RDE/RHU/FME) :
- WR112+WR113 duo 1 (commun aux deux cours) : RDE→[A,C], FME→[B,D]
- WR112 duo 2 : FLI→[E,G], AHA→[F,H]
- WR113 duo 2 : RHU→[E,G], AHA→[F,H] (RHU remplace FLI)

Ajouté dans `data/config/teacher_duos.yaml`, réutilise le même mécanisme
`add_duo_synchronized_rare_room_constraints` déjà en place pour WR110 —
aucun changement de code solveur nécessaire.

**Plafond hebdo enseignant — corrigé.** Kyllian : "pour moi non [de
plafond], ou alors maximum 40h devant étudiant". Le cap précédent (14
créneaux/21h côté `solve_decomposed`, 20 créneaux/30h côté `assign_weeks` —
incohérence jamais confirmée) est remplacé par une valeur unique de **26
créneaux (39h, sous la barre des 40h)** aux deux endroits
(`decomposed.py::assign_weeks`/`solve_decomposed`) ainsi que dans
`api/regen.py` (régénération ciblée jointe sur 2 semaines).

**Absence Régis Huez confirmée et corrigée.** "Indisponible du 19 octobre
2026 au 22 octobre 2026" (conférence à Marseille) — mentionnée seulement en
texte libre jusqu'ici (cf. §24), maintenant ajoutée comme token
`date_specifique` structuré dans `contraintes/05_enseignants_contraintes.json`
— vérifié : `forbidden_dates` contient bien 2026-10-19 à 2026-10-22 inclus,
`unresolved_tokens` vide pour RHU.

Suite pytest complète relancée après le revert de la synchro CM : 60/60
passent, aucune régression sur l'ensemble des changements de ce tour
(effectifs, duos WR112/WR113, plafond enseignant, absence RHU).

## 26. Vérification inter-parcours + suggestions d'alternatives sur conflit (retour utilisateur, 06/08/2026)

**Vérification inter-parcours** (question : le glisser-déposer vérifie-t-il
bien les disponibilités des AUTRES parcours ?) : confirmé sur un cas réel,
pas supposé — `validate_move`/`PATCH /placements/{id}` valident contre
`state.timetable` en ENTIER, qui contient déjà TOUS les parcours du run
multi-parcours chargé (Groupe A). Testé : déplacer une séance BUT1 de KBR
sur un créneau où KBR a déjà une séance BUT2-DEV-FI (WR311D) est bien
rejeté (`"Conflit enseignant : WR311D (KBR)"`). Aucun changement de code
nécessaire, déjà correct par construction.

**Suggestions d'alternatives sur conflit** (retour utilisateur : "il
faudrait proposer des solutions" plutôt qu'un refus sec) :
`api/validation.py::suggest_alternative_slots` scanne jusqu'à 6 semaines
FUTURES à partir de la semaine visée et propose jusqu'à 3 créneaux sans
conflit connu. Couvre : conflits groupe/enseignant/salle (réutilise
`validate_move`), indispos enseignant déclarées (récurrentes + dates
précises), jours fériés/bloqués du calendrier, verrou semaine passée/en
cours. Limite assumée et documentée dans le code : ne vérifie PAS le
verrou jeudi PAC, la sanctuarisation SAE, ni la capacité de salle vs
effectif — une régénération de semaine (`POST /regen/week`, déjà en place)
reste la seule voie garantie à 100 % si ces suggestions ne suffisent pas.

Câblé dans `POST /placements/{id}/validate` (champ `suggestions` de la
réponse) et `PATCH /placements/{id}` (inclus dans le détail du 409).
Côté frontend : la modale native `confirm()` (conflit → forcer oui/non) est
remplacée par une vraie modale (`#conflictModal`) listant les conflits et
jusqu'à 3 boutons d'alternative cliquables (retente le déplacement avec le
créneau choisi) + "Forcer quand même" + "Annuler".

Vérifié en conditions réelles (port 8123) : `POST /placements/{id}/validate`
et `PATCH /placements/{id}` renvoient bien 3 suggestions concrètes et
correctes sur le cas de conflit inter-parcours ci-dessus. Suite pytest
complète relancée après ce changement.

## 27. Bug réel trouvé — l'étage 2 ignorait `teacher_availability` (06/08/2026)

Run Groupe A relancé avec les correctifs du jour (§25 : duos WR112/WR113,
plafond 39h, absence RHU/KNG) : **2 tentatives consécutives en
`PARTIAL_WEEKS_FAILED`, systématiquement sur les MÊMES semaines** — 1re
tentative `[7, 8]`, 2e `[5, 7, 8]` (pire, pas mieux). Un échec répété sur
les mêmes semaines (contrairement au bruit habituel du CP-SAT, qui varie
généralement d'une tentative à l'autre) a immédiatement fait suspecter une
cause structurelle plutôt qu'une simple malchance de seed — vérifié plutôt
que redevinée : les dates réelles de ces semaines coïncident EXACTEMENT
avec les 2 corrections du jour : semaine 7 = 19-23 octobre 2026 (absence
RHU confirmée 19-22 octobre), semaine 8 = 2-6 novembre 2026 (absence KNG
confirmée sur toute la semaine).

**Cause racine confirmée** : `assign_weeks` (étage 2 — décide dans quelle
semaine tombe chaque séance) n'a **jamais reçu `teacher_availability`**
comme paramètre, contrairement à l'étage 3 (`solve_week_detail`) qui la
connaît bien. L'étage 2 pouvait donc assigner une séance de RHU ou KNG à
une semaine où ils sont partiellement ou totalement absents, sans le
savoir — l'étage 3, lui, refuse ensuite catégoriquement de la placer nulle
part dans cette semaine (tous les jours interdits pour KNG semaine 8 ;
4 jours sur 5 pour RHU semaine 7), semaine entière en échec. Ce bug
préexistait silencieusement : tant que `forbidden_dates` de RHU/KNG
n'étaient pas correctement parsées (§24, avant les corrections du jour),
l'étage 2 ne pouvait pas se tromper sur une contrainte qu'il ignorait déjà
partout — corriger le parsing a donc RÉVÉLÉ ce bug plus profond, sans le
créer.

**Corrigé** : `assign_weeks` accepte désormais `teacher_availability` ;
nouvelle fonction `_teacher_available_slots_by_week` calcule, pour chaque
(enseignant, semaine), le nombre de créneaux réellement disponibles
(créneaux hebdo théoriques moins récurrents + dates précises tombant dans
cette semaine) — le plafond hebdomadaire enseignant de l'étage 2 est
désormais `min(plafond générique, disponibilité réelle cette semaine)` au
lieu d'un plafond fixe aveugle à `teacher_availability`. Une semaine
totalement bloquée pour un enseignant donne une disponibilité de 0,
excluant de fait toute assignation à cette semaine pour lui (pas seulement
"découragée", réellement à 0). Vérifié sur un cas synthétique (professeur
totalement absent une semaine précise) : l'étage 2 évite bien
correctement cette semaine. Suite pytest complète relancée après ce
correctif.

Un seul point d'appel en production (`solve_decomposed`), déjà mis à jour
pour passer `teacher_availability` à `assign_weeks`.

**Convergence** : 4 tentatives — 1re `PARTIAL_WEEKS_FAILED:[7,8]` (avant
correctif), 2e `[5,7,8]` (avant correctif, pire), 3e `[9]` (APRÈS
correctif — semaines 7/8 définitivement résolues, ne reviennent plus ; le 9
restant est une semaine avec jour férié le 11 novembre, capacité réduite à
4 jours, cause différente et déjà connue/modélisée), 4e **`FEASIBLE`,
2379/2379 séances placées**. Confirme que le correctif a bien réglé sa
cause précise sans en introduire une nouvelle.

**Résultat final (run id=14, chargé en DB, remplace le run précédent)** :
`FEASIBLE`, 2379/2379 séances classiques placées, 197 trous, 3 jours
isolés, **8/8 règles dures `PASS`** (capacité salle, plafond hebdo,
jeudi PAC, sanctuarisation SAE, salle éval A.018, semaine d'intégration
BUT1, ordre pédagogique CM→TD→TP, éval après contenu). Ordonnancement
inter-matières (molle) : 4/76 non respectées (mieux que 8/76 sur le run
précédent). Vérifié en conditions réelles sur le serveur (port 8123) :
RHU a bien 0 séance sur sa semaine d'absence (19-23 oct.), KNG idem
(2-6 nov.), et les duos WR112/WR113 apparaissent bien synchronisés dans
les salles couplées H.017/H.022 avec la répartition de groupes confirmée
(RDE=A,C / FME=B,D / FLI=E,G / AHA=F,H sur WR112 ; RDE=A,C / FME=B,D /
RHU=E,G / AHA=F,H sur WR113).

Artifact volontairement non republié (consigne explicite : le laisser tel
quel pour ce chantier) — uniquement l'interface interne mise à jour.

## 28. Bug d'affichage — événements horodatés répétés sur toute la journée (retour utilisateur, 06/08/2026)

Repéré sur capture d'écran (Vue Semaine, semaine du 7-11 sept. 2026) : les
repères "9h30 Echange IA" et "17h / 18H30 Présentation des services aux
nouveaux étudiants" apparaissaient répétés dans PLUSIEURS créneaux du
mardi au lieu de leurs 2 créneaux réels — et ces cases n'étaient plus
déposables en glisser-déposer une fois qu'une séance en avait été retirée
(cf. retour : "on peut déplacer un cours qui était dessus mais pas le
remettre à sa place"). Retour utilisateur complémentaire : "pour les
séances Clé de Troyes ce ne sont pas des séances bloquées, c'est juste
indicatif" — distinction à faire entre les deux catégories.

**Cause racine** : `planning_events_as_week_days` (affichage) construisait
un repère au grain du JOUR ENTIER (tous les libellés du jour regroupés),
alors que `planning_event_blocked_slots` (blocage réel côté solveur, cf.
§20) travaille déjà au grain du CRÉNEAU précis — l'affichage n'avait jamais
été mis à jour pour suivre la même granularité que le blocage, donc un
événement avec horaire explicite (ex. "9h30 Echange IA") polluait toutes
les cases vides du jour au lieu de sa seule case réelle, ET rendait ces
cases indûment non-déposables (branche `else if (events)` prioritaire sur
la case "libre" déposable).

**Corrigé** (`planning_loader.py`) : `planning_events_as_week_days` ne
garde désormais QUE les événements SANS horaire extractible (ex. "Clés de
Troyes", "Intégration", "Armistice") — jour entier, purement indicatif,
JAMAIS bloquant pour un dépôt. Nouvelle fonction
`planning_events_as_week_day_slots` pour les événements AVEC horaire —
un repère par créneau précis, cohérent avec `planning_event_blocked_slots`.
Nouveau champ payload `eventSlotRows` (à côté de `eventRows`, désormais
untimed uniquement) ; `dayBandsForWeek` (JS) expose `eventSlots[d][s]` en
plus de `events[d]`. Ordre de priorité par case dans
`renderGenericCalendar`/`renderPromoTab` : séance > férié > PAC > SAE >
événement HORODATÉ (non déposable) > événement INDICATIF (déposable) >
case libre.

Vérifié sur le cas exact du retour utilisateur (semaine du 7 sept. 2026,
mardi) : "9h30 Echange IA" n'apparaît plus qu'au créneau 9h30-11h, "17h/
18h30 Présentation..." qu'au créneau 17h-18h30 — les 4 autres créneaux du
mardi redeviennent libres/déposables. Suite pytest complète relancée.

## 29. Suggestions d'alternatives — contraintes complètes + inter-parcours (retour utilisateur, 06/08/2026)

Retour utilisateur : "les suggestions... doivent prendre en compte les
contraintes et vérifier si cela est possible dans tous les autres
parcours". Le conflit groupe/enseignant/salle était déjà vérifié contre
`state.timetable` COMPLET (tous les parcours du run chargé), confirmé de
nouveau ci-dessous — mais §26 documentait aussi des limites assumées
(verrou jeudi PAC, SAE, événements horodatés, ordre pédagogique) jamais
comblées. Comblées maintenant :

- **Verrou jeudi PAC** : exclu pour toute séance FI (jamais FC).
- **Événements du planning officiel à horaire précis** : réutilise
  `planning_event_blocked_slots` (même source que le blocage réel côté
  solveur, cf. §20/§28) — une suggestion ne tombe jamais sur "9h30 Echange
  IA" ni "17h/18h30 Présentation...".
- **Jours SAE sanctuarisés** : réutilise `sae_blocked_days_by_parcours`,
  scopé au parcours de la séance déplacée.
- **Ordre pédagogique** : réutilise `_build_sequence_neighbors`/
  `_movable_bounds` (déjà utilisés par la régénération ciblée, `api/regen.py`)
  — une suggestion ne peut tomber que dans une semaine qui ne violerait pas
  l'ordre avec un voisin de séquence (même garantie que §23).
- **Synchronisation duo salle rare** (WR110/112/113) : nouvelle détection
  `_is_duo_synced` — aucune suggestion générée pour une moitié de duo
  (déplacer une seule moitié casserait la synchronisation ; seule une
  régénération de semaine, qui connaît `add_duo_synchronized_rare_room_constraints`,
  gère ce cas correctement).

Vérifié en conditions réelles (port 8123, run Groupe A) : suggestions sur
un conflit réel ne contiennent aucun jeudi après-midi (seulement jeudi
matin) ; tentative de déplacement d'une séance WR110 (duo KBR/KNG) vers un
créneau en conflit renvoie bien `"suggestions": []` (pas de fausse
suggestion qui casserait la synchronisation). Suite pytest complète
relancée.

## 30. Avertissement duo + recalcul de salle (retour utilisateur, 06/08/2026)

Deux retours : (1) quand aucune suggestion n'est proposée pour une moitié de
duo synchronisé, il faut un vrai message explicatif, pas juste une liste
vide ; (2) "on est d'accord que l'on vérifie les conflits sur les 3 années"
(confirmé : déjà le cas, `state.timetable` du run Groupe A couvre BUT1/
BUT2/BUT3 ensemble) "et il faut faire attention à la salle, si on modifie
il faut recalculer cela" — un déplacement ne doit pas être bloqué juste
parce que la salle D'ORIGINE n'est plus libre au nouveau créneau, si une
autre salle adaptée l'est.

**Avertissement duo** : nouveau champ `suggestions_note` (`ValidationResponse`
+ détail du 409 de `PATCH /placements/{id}`) — message explicite quand
`_is_duo_synced` bloque toute suggestion, affiché dans la modale de conflit
à la place du message générique "aucune alternative trouvée".

**Recalcul de salle** : nouvelle fonction `find_room_for_slot`
(`solver/rooms.py`) — même logique de priorité que `assign_rooms` (type de
salle préféré/fallback, capacité vs effectif) mais pour une requête
ponctuelle. Garde la salle actuelle si encore libre au nouveau créneau,
recalcule sinon ; ne bloque le déplacement QUE si vraiment aucune salle
adaptée n'est libre. Câblé dans `move_session` (déplacement réel),
`validate_placement` (dry-run — doit rester cohérent avec ce que fera le
déplacement réel) et `_suggestions_for` (chaque créneau suggéré teste
d'abord la salle d'origine, sinon une autre ; exclu si aucune salle du
tout, plutôt que de proposer un horaire finalement injouable). Uniquement
quand l'utilisateur n'a pas explicitement demandé une salle précise
(`body.room_id`) : dans ce cas son choix est respecté tel quel.

**Bug réel trouvé en testant en conditions réelles (pas juste sur cas
synthétique)** : la première version câblait `_resolve_room` sur
`_as_placed(state.timetable)`, qui construit des `PlacedSession` SANS le
champ `room_id` (seul `PlacedSessionWithRoom` l'a) — `find_room_for_slot`
ne voyait donc JAMAIS aucune salle comme occupée, et un déplacement testé
en réel a provoqué un vrai double-booking (2 séances dans H.103 au même
horaire, détecté en revérifiant l'occupation après coup, pas supposé
correct sur la seule confirmation `valid:true`). Corrigé : `_resolve_room`
passe `state.timetable` directement (pas `_as_placed`). Revérifié sur le
même cas exact : la séance change bien de salle (H.103 occupée → H.111
recalculée), zéro double-booking après coup. DB remise à l'état propre
(run Groupe A intact) après ces tests. Suite pytest complète relancée.

## 31. Verrous institutionnels réellement opposables au déplacement (retour utilisateur, 06/08/2026)

Retour utilisateur : "vérifie bien que n'importe quelle modification, recalcul
etc. ne casse pas tout, et vérifie bien toutes les contraintes avant que ça
s'effectue". Faille réelle trouvée en relisant `move_session`/
`validate_placement` : les règles ajoutées en §29/§30 (verrou jeudi PAC,
sanctuarisation SAE, événements horodatés du planning officiel, ordre
pédagogique, synchronisation duo) n'étaient câblées QUE dans
`_suggestions_for` — elles filtraient les suggestions proposées, mais
**aucun garde-fou ne les vérifiait sur le déplacement réellement demandé**.
Un glisser-déposer direct sur une case arbitraire (pas depuis une
suggestion), ou un appel `PATCH /placements/{id}` avec `force:true`,
pouvait donc concrètement poser une séance un jeudi après-midi PAC, un
jour SAE sanctuarisé, sur un événement du planning officiel à horaire
précis, hors de la fenêtre d'ordre pédagogique, ou casser une
synchronisation duo — malgré la présence de code qui "savait" que c'était
interdit.

**Distinction volontaire, actée pour ce correctif** : les conflits de
RESSOURCES (groupe/enseignant/salle déjà occupés) restent `force`-ables —
un humain peut avoir une bonne raison ponctuelle de les outrepasser. Les
règles INSTITUTIONNELLES/PÉDAGOGIQUES (verrou PAC, sanctuarisation SAE,
événement planning, ordre pédagogique, synchro duo) ne le sont JAMAIS,
même avec `force:true` : casser l'une d'elles n'a jamais de bonne raison
ponctuelle, contrairement à un conflit de ressources.

**Corrigé** (`api/main.py`) :
- `_hard_constraint_context(state, session)` : extrait de l'ancien corps
  de `_suggestions_for` — calcule `(extra_blocked, allowed_weeks)` pour une
  séance donnée (jeudi PAC, SAE, événements horodatés, ordre pédagogique).
  Réutilisé maintenant à la fois pour filtrer les suggestions ET pour
  bloquer réellement un déplacement.
- `_institutional_violations(week, day, slot, extra_blocked, allowed_weeks)`
  : traduit ce contexte en messages de violation, jamais contournables.
- `move_session` et `validate_placement` appellent désormais
  `_is_duo_synced` puis `_hard_constraint_context`/`_institutional_violations`
  en tout premier (avant toute résolution de salle ou vérification de
  conflit de ressources), et retournent 409/`valid:false` sans jamais
  regarder `body.force` pour ces cas précis.

Vérifié en conditions réelles (port 8123, run Groupe A, 2379 placements) :
- Déplacer WR101 (FI, donc PAC concerné) vers jeudi 15h30 (créneau 3) :
  `validate` renvoie `valid:false` avec le message de verrou PAC ; `PATCH`
  sans `force` → 409 ; `PATCH` avec `force:true` → **toujours 409**, message
  identique (avant ce correctif, `force:true` aurait fait passer le
  déplacement).
- Déplacer WR113 (moitié du duo RDE/FME) seule vers un créneau libre :
  `validate` renvoie `valid:false` avec le message `_DUO_SYNC_NOTE` ;
  `PATCH` avec `force:true` → **toujours 409**, même message.
- Déplacement légitime (WR105 vers un créneau libre sans aucun conflit) :
  `validate` renvoie `valid:true`, `PATCH` réussit normalement — aucune
  régression sur le chemin nominal.

DB remise à l'état propre (run Groupe A intact, `load_group_a_to_db.py`,
run id=17) après ces tests ; serveur redémarré pour recharger cet état.
Suite pytest complète relancée.

## 32. Trois bugs réels trouvés en vérifiant les semaines SAE années 2/3 (retour utilisateur, 06/08/2026)

Retour utilisateur : "regarde aussi sur le calendrier pour les années 2 et
3 il y a les semaines de SAE etc, il faut faire attention à cela, pour les
alternants..." — en creusant ce point (avant de proposer un compromis de
date de fin de semestre pour les FC), 3 bugs réels et confirmés ont été
trouvés sur des données déjà en production (run Groupe A déjà résolu,
FEASIBLE 2379/2379). Aucune supposition : chaque bug est vérifié en
comparant `data/exports/maquette.json`/`data/generated/sessions.json`
(réalité) au comportement du code.

### 32.1 Sanctuarisation SAE : mauvaise feuille lue pour les FC

`load_mmi_planning` ne lisait QUE la feuille FI (`S3S4-FI`/`S5S6-FI`) quel
que soit le parcours, alors que la source (`contraintes/
04_planning_hebdomadaire_par_promo.json`) contient déjà des feuilles FC
dédiées (`S3S4DEV-FC`, `S3S4CREACOM-FC`, `S5S6DEV-FC`,
`S5S6CREACOM-FC`) jamais lues. Exemple concret (S5) : SAE501D (FI) tombe
le 19 oct-2 nov 2026, alors que la vraie prochaine SAE des FC (SAE601D/
601C) est le 29-30 mars 2027 — les FC héritaient donc des mauvaises dates.

### 32.2 Sanctuarisation SAE : zéro protection pour les parcours FI

Le générateur de code cours à partir d'un token SAE (`sae_token_to_course_codes`)
produisait TOUJOURS un code préfixé "WSA" (ex. SAE501D → WSA501D) pour tout
numéro ne commençant pas par 1/2 — mais le vrai code des séances FI est
"WS501D" (sans "A"). Résultat vérifié sur `sessions.json` : AUCUNE séance
SAE (au sens sanctuarisation) ne matchait jamais pour BUT2-DEV-FI/
BUT3-DEV-FI — zéro jour protégé, malgré des dates réelles de SAE
existantes dans la feuille FI. Par coïncidence, ce même code "WSA{num}"
matchait les VRAIS codes des parcours FC (§32.1), d'où le mélange des deux
bugs sur le run déjà résolu.

**Corrigé** (`ingestion/planning_loader.py`) : nouvelle convention de code
par feuille, vérifiée empiriquement (pas déduite d'un motif générique) —
`_SHEET_CODE_TEMPLATE` (`WS{num}` pour S1S2, `WS{num}D` pour les feuilles
FI de S3+, `WSA{num}D` pour DEV-FC, `WSA{num}M` pour CREACOM-FC niveau
BUT2 — héritage "MMI" — `WSA{num}C` pour CREACOM-FC niveau BUT3 : la
feuille CREACOM-FC écrit pourtant "C" aux deux niveaux, seul le VRAI code
de séance fait foi). `load_mmi_planning` charge et fusionne maintenant
TOUTES les feuilles concurrentes d'un semestre (`_SHEETS_BY_SEMESTRE`),
chaque feuille apportant ses propres codes ET ses propres dates — sans
risque de collision (les préfixes/suffixes des 3 pistes ne se recouvrent
jamais, vérifié sur `sessions.json`). `events`/`blocked_labels` restent
sourcés uniquement depuis la feuille FI (portée volontairement limitée à
la SAE pour ce correctif). 5 nouveaux tests de régression
(`tests/test_planning_loader.py`), dont 3 couvrant explicitement ces 2
bugs (FI protégé avec son propre code, FC avec ses propres dates
distinctes de celles de la FI, CREACOM-FC BUT2 avec le suffixe M).

### 32.3 Co-animation séquentielle : le second enseignant disparaissait

Trouvé en vérifiant les 3 nouveaux modules CREACOM-FC détaillés par
l'utilisateur (WRA505C/506C/508C, "17 séances pour X et 17 pour Y") :
comparaison systématique maquette déclarée vs enseignants réellement
présents dans `sessions.json` → **10 cours réels** du semestre impair où
un enseignant déclaré n'apparaît dans AUCUNE séance planifiée (WS104,
WR312D, WSA301M, WRA505C, WRA506C, WRA508C, WS501D, WSA501D, WSA502C,
WSA502D).

Cause : `_teacher_for_group` (ingestion/normalize.py) répartissait les
enseignants par GROUPE via `nbGpTd`/`nbGpTp` — correct pour un cours à
plusieurs groupes réels où chaque enseignant en couvre un sous-ensemble
disjoint (ex. WR112 : 4 groupes TD, 4 profs, `nbGpTd=1` chacun). Mais pour
un cours en "groupe unique" (organisation confirmée des parcours FC) où 2
enseignants se partagent le MÊME groupe par tranche chronologique (ex. "17
séances ALO puis 17 AFR"), `nbGpTd=1` pour LES DEUX blocs → le curseur
par groupe assignait TOUJOURS le premier bloc de la liste à la totalité
des séances, le second enseignant n'était jamais planifié. Vérifié aussi
présent hors FC (WS104 : 3 profs déclarent chacun `nbGpTd=4`, soit la
totalité des 4 groupes réels — même dégénérescence).

**Corrigé** : `_teacher_for_group` utilise maintenant `block.td`/`block.tp`
(nombre RÉEL de créneaux que ce bloc délivre, tous groupes confondus) — vérifié
fiable sur toutes les données réelles inspectées : leur somme égale
toujours `volumes[type] × nombre de groupes réels`, contrairement à
`nbGpTd`/`nbGpTp` qui peut être dégénéré. Remplit la grille
(groupe, occurrence-dans-la-séquence-de-ce-groupe) groupe par groupe
complet — reproduit à l'identique l'ancien découpage correct pour les
cours multi-groupes (WR112, WR103... — vérifié : `test_wr110_teacher_per_tp_group`
et les autres tests d'ingestion existants passent sans modification) ET
couvre nativement le cas "groupe unique partagé chronologiquement".

Cas particulier : WRA505C a une contrainte de progression CONFIRMÉE par
l'utilisateur ("commencer avec Ariane Loizon, basculer sur Anthony Froli
en fin de module") — mais la maquette source liste AFR avant ALO (alors
qu'ALO est le lead). Donnée jamais devinée : nouvel override explicite
`_KNOWN_TEACHING_ORDER = {"WRA505C": ["ALO", "AFR"]}` dans
`ingestion/normalize.py`, avec la citation exacte en commentaire. Les 2
autres cours CREACOM-FC (WRA506C, WRA508C) n'ont aucun ordre de
progression précisé par l'utilisateur — laissés sans override (répartition
par ordre de la maquette, sans garantie chronologique particulière).

Vérifié par ré-ingestion complète (`cal_iut.cli ingest --semestre-group odd`,
3108 séances, total inchangé) puis comparaison systématique maquette vs
séances réelles sur les 10 cours : les 10 ont désormais TOUS leurs
enseignants déclarés présents, avec les bons volumes (ex. WRA505C : ALO=17/
AFR=17 exactement). Reste 2 cas non liés au bug (WSA301M/FLI,
WSA502C-D/OCH) où la maquette source déclare littéralement 0 créneau pour
le second enseignant — fidèlement respecté, à vérifier auprès de Kyllian
si c'est intentionnel plutôt qu'un trou de saisie. Suite pytest complète
relancée.

## 33. Horizon étendu pour les alternants uniquement (retour utilisateur, 06/08/2026)

Suite de §32 : retour utilisateur — "le semestre n'est pas obligé de finir
le 19 février [pour les alternants], il faut trouver un bon compromis de
date pour qu'il n'y ait pas trop de cours au 2e semestre... j'étends
l'horizon... oui mais que les parcours alternance" (pas un allongement
global).

**Chiffrage, basé sur le calendrier réel de présence IUT des alternants**
(`contraintes/03_calendrier_alternance_officiel.json`, fourni par
l'utilisateur — jamais deviné) : BUT3-DEV-FC/CREACOM-FC S5 ne sont
physiquement à l'IUT que 8 semaines dans l'horizon standard actuel (19
semaines, jusqu'au lundi 25/01/2027) → 216 séances ÷ 8 = 27 créneaux/
semaine nécessaires, 90% de la capacité max (30 créneaux/semaine =
5 jours × 6 créneaux). Leurs 2 prochaines semaines de présence réelle
sont le 15-19 février et le 8-12 mars 2027 ; leur SAE601 (prochain jalon
réel, cf. §32.1) tombe juste après, le 30 mars. Étendre à 24 semaines
(jusqu'au 8 mars inclus, juste avant la SAE) porte leur présence utile à
10 semaines → 216 ÷ 10 = 21,6 créneaux/semaine (72%).

**Corrigé** (`solver/decomposed.py::assign_weeks`) : nouveau paramètre
`fi_max_week: int | None = None`. Quand fourni et `< max_week`, restreint
le domaine de `week_var` à `[0, fi_max_week]` pour toute séance dont le
parcours ne contient PAS "FC" — les séances FC gardent le domaine complet
`[0, weeks-1]`. Fil de bout en bout : `decomposed.py::solve_decomposed`
(nouveau paramètre, transmis à l'unique appel d'`assign_weeks`) →
`cpsat.py::SolverConfig.fi_max_week` → `TimetableSolver.solve_decomposed`
→ `cli.py --fi-max-week` (mode `--decomposed` uniquement, cohérent avec
`--weeks` déjà existant). `None` par défaut partout : comportement
strictement inchangé si non utilisé.

Vérifié par 3 nouveaux tests synthétiques ciblés
(`tests/test_assign_weeks_fi_max_week.py`, pas de fixture réelle
nécessaire) : 20 séances d'un même enseignant, plafond hebdo forcé à 1
créneau/semaine (donc 20 semaines distinctes strictement nécessaires) —
(a) en parcours FI avec `fi_max_week=18` sur un horizon `weeks=24` :
INFEASIBLE (19 semaines dispo, pas assez) — confirme que l'extension ne
fuit jamais vers les FI ; (b) mêmes séances en parcours FC : FEASIBLE, au
moins une séance au-delà de la semaine 18 — confirme l'usage réel de
l'extension ; (c) mélange FI+FC réaliste : toutes les séances FI restent
`<= 18`, au moins une séance FC dépasse. Suite pytest complète relancée.

## 34. Calcul de nuit — run de production + bug réel trouvé en vérifiant (06/08/2026)

Lancé : `cal_iut.cli solve --decomposed --semestre-group odd --weeks 24
--fi-max-week 18` sur les 3120 séances ré-ingérées (correctifs §32 +
WR100BU). **`FEASIBLE` dès la 1ère tentative** (pas besoin de retry cette
fois) : 2391/2391 séances classiques placées (2379 + 12 WR100BU), 187
trous, 1 jour isolé.

**Vérification systématique post-solve** (pas seulement la sortie du
solveur — mêmes invariants durs que le run précédent, §17.3/§27) :
0 conflit enseignant (y compris inter-parcours), 0 conflit groupe, 0
violation verrou jeudi PAC (FI), 0 séance BUT1 en semaine d'intégration,
0 séance FI au-delà de la semaine 18 (`fi_max_week` respecté), séances FC
allant bien jusqu'à la semaine 23 (extension utilisée réellement) — et
WRA505C/506C/508C confirmés 17/17 sur la sortie réelle du solveur (pas
seulement à l'ingestion).

**Bug réel trouvé à cette vérification, corrigé avant de considérer le run
terminé** : 1 double-booking de salle détecté (amphi H.018 — la seule
salle de ce type, capacité 150 — occupée simultanément par un CM BUT1
(WR105) et un CM BUT2-DEV-FI (WR314D) au même horaire). Cause
(`solver/rooms.py::assign_rooms`) : la règle `same_room_for_course`
(chaque CM d'un même cours réutilise la même salle) affectait la salle en
cache SANS jamais vérifier ni mettre à jour `room_schedule` — un second
cours, traité ensuite, pouvait donc légitimement (de son point de vue)
récupérer la même salle unique au même créneau via le chemin normal.
Pré-existant (pas introduit aujourd'hui), jamais déclenché sur les runs
précédents faute du bon mélange de créneaux CM — la vérification
explicite "0 conflit salle" n'avait jusqu'ici jamais été faite aussi
systématiquement, seul "0 conflit enseignant" l'avait été.

**Corrigé** : la branche `same_room_for_course` vérifie maintenant
`room_schedule` avant de réutiliser la salle en cache, et le met à jour
si elle l'utilise ; si la salle habituelle du cours est déjà prise à CE
créneau précis, retombe sur la sélection normale (qui, elle, respecte
toujours `room_schedule`) plutôt que de forcer un double-booking. Nouveau
test de régression synthétique
(`test_assign_rooms_same_room_cache_does_not_double_book`, 2 cours
distincts partageant une salle unique, collision reproduite puis
vérifiée corrigée). Salles réaffectées sur le run déjà résolu (rejouer
juste `assign_rooms` sur les placements semaine/jour/créneau déjà
décidés — pas besoin de relancer tout le CP-SAT, l'affectation de salle
est une passe déterministe séparée) : 0 conflit salle après correction,
tout le reste inchangé. Suite pytest complète relancée.

**Statut final** : `FEASIBLE`, 2391/2391, 0 conflit (enseignant/groupe/
salle), tous les correctifs du jour vérifiés sur la sortie réelle. Chargé
dans l'interface (sentinel "ODD") pour consultation.

## 35. Corrections ponctuelles + bug réel de rééquilibrage FC (07/08/2026)

Deux corrections de données, plus un bug réel trouvé en creusant la
question de l'utilisateur.

**Événement corrigé** (`contraintes/04_planning_hebdomadaire_par_promo.json`,
feuille S1S2, semaine du 7 sept. 2026, mardi) : "Présentation des services
aux nouveaux étudiants" était indiqué "17h / 18H30" — retour utilisateur :
en réalité 9h30-12h30. Corrigé directement dans la source (texte réécrit
"9h30 / 12h30 Présentation..." — le même parseur par horaire extrait du
texte s'applique sans changement de code) ; vérifié : `_slots_for_event_text`
retombe bien sur les créneaux 1 et 2 (9h30-11h, 11h-12h30).

**Nouvelle contrainte enseignant** (`teacher_availability.yaml`) : Kyllian
Bresson (KBR) ne débute ses cours qu'à partir de 9h30 — `forbidden_slots`
sur le créneau 0 (8h-9h30), les 5 jours.

**Bug réel trouvé** (retour utilisateur : "pourquoi pour les S5 FC créa et
com la semaine 16 est une semaine de cours ?") : vérification confirmée —
"Semaine 16" (département) = semaine-index interne 13 = 7-11 déc. 2026,
absente des 3 calendriers de présence IUT des alternants concernés. Étendu
à TOUS les parcours FC du run sur demande explicite ("vérifie pour tous
les parcours") : **BUT2-CREACOM-FC (19 séances), BUT3-CREACOM-FC (17),
BUT3-DEV-FC (16)** avaient tous des séances à cette même semaine 13 —
absente de leurs 3 calendriers de présence respectifs.

Cause (`solver/decomposed.py::_rebalance_failed_weeks`) : la contrainte
dure de présence FC existe bien à l'étage 2 (`assign_weeks`, section
"Présence FC", `add_allowed_assignments`) et est correcte (vérifié
empiriquement : `allowed_week_days_for_parcours` exclut bien la semaine 13
pour les 3 parcours). Mais le rééquilibrage post-échec
(`_rebalance_failed_weeks`, qui déplace des séances d'une semaine
surchargée vers une semaine voisine avec de la marge) ne vérifiait AUCUNE
contrainte de présence dans son critère `fits()` — une semaine hors
présence FC est TOUJOURS vide (aucune séance FC n'y est jamais assignée
normalement), donc maximalement attractive pour ce critère (plafond
enseignant/cohorte au plus bas), ce qui explique que les 3 parcours FC
distincts aient tous convergé vers LA MÊME semaine 13.

**Corrigé** : nouveau paramètre `allowed_weeks_by_parcours` sur
`_rebalance_failed_weeks`, construit une fois (mêmes calendriers que
l'étage 2) et vérifié dans `fits()` pour toute séance dont le parcours
contient "FC". 2 nouveaux tests synthétiques
(`tests/test_rebalance_fc_presence.py`) : un cas où une semaine hors
présence serait la cible la plus proche (doit être évitée), un cas
témoin sans données de présence (comportement historique inchangé,
prouve que le 1er test est significatif et n'aurait pas passé sans le
correctif). Suite pytest complète relancée.

## 36. Lissage des emplois du temps de 3e année (retour utilisateur, 07/08/2026)

Retour utilisateur : "pour les emplois du temps de 3ème année essaie de
faire en sorte qu'elle soit le plus lissée possible en évitant au max les
cours de 8h et de 17h, limite si on peut les faire finir à 15h30 c'est
bien". Distinct d'`add_avoid_zone_penalties` (déjà existant, cahier des
charges §2) qui ne pénalise QUE lundi 8h et vendredi 17h, pour TOUS les
parcours — ici il faut n'importe quel jour, et uniquement pour la 3e
année (`annee == "BUT3"`, donc BUT3-DEV-FI/FC et BUT3-CREACOM-FC).

**Ajouté** (`solver/objectives.py::add_edge_slot_penalties`) : pénalité
molle à 2 paliers, sur `slot_in_day` (n'importe quel jour) — poids 25
pour les créneaux 8h-9h30 et 17h-18h30 (préférence forte, "au max"),
poids 10 pour 15h30-17h (préférence plus faible, "si on peut" — objectif
secondaire explicitement marqué comme moins prioritaire par
l'utilisateur). Câblé dans `solve_week_detail` (étage 3, mode
`--decomposed`), sur `week_sessions` filtrées à `annee == "BUT3"` avant
l'appel — ne change strictement rien pour BUT1/BUT2. 5 nouveaux tests
(`tests/test_objectives_edge_slots.py`) : pénalité correcte par créneau,
poids nul = aucun terme ajouté, et un solveur libre de choisir minimise
bien vers un créneau non-bordure.

Non câblé dans le modèle joint (`cpsat.py`) — hors périmètre : les runs
de production actuels utilisent tous `--decomposed` (cf. §14).

## 37. Bug réel majeur — BUT2/BUT3 sans AUCUNE protection SAE ni événement (07/08/2026)

Retour utilisateur : "dans les documents il n'y avait pas des séances
obligatoires pour 2e/3e année à propos de leur rentrée ? vérifie" +
"refait un check global des contraintes". En vérifiant, découverte d'un
bug bien plus large que prévu — pas limité à la "rentrée".

**Root cause** : un run multi-parcours (Groupe A, `--semestre-group odd`)
résout S1+S3+S5 ensemble, mais `TimetableSolver.solve_decomposed`
appelait `load_mmi_planning(root, semestre)` avec `semestre` = **l'ANCRE
du groupe** ("S1" seulement, cf. `SEMESTRE_GROUP_ANCHOR`), pas les 3
semestres réels. Confirmé empiriquement en reproduisant l'appel exact :
`load_mmi_planning(root, "S1")` ne retourne QUE les codes SAE de BUT1
(WS101-107, WS203) — aucun code BUT2 (S3) ni BUT3 (S5), malgré le
correctif §32 (qui fusionne bien les feuilles PAR semestre, mais
n'était jamais invoqué pour S3/S5 dans un run multi-parcours réel).

**Conséquence vérifiée sur le run alors en production** : 260 violations
réelles de sanctuarisation SAE (une séance classique BUT2-DEV-FI/
BUT3-DEV-FI posée sur un vrai jour de SAE de son parcours) — la
vérification n'avait jamais porté sur cet invariant précis jusqu'ici (les
checks précédents portaient sur conflits enseignant/salle/groupe, pas sur
la sanctuarisation SAE elle-même sur la sortie réelle). Même bug pour les
événements du planning officiel (rentrées, etc.) : les feuilles BUT2/BUT3
(`S3S4-FI`, `S3S4DEV-FC`, `S3S4CREACOM-FC`, `S5S6-FI`, `S5S6DEV-FC`,
`S5S6CREACOM-FC`) contiennent bien des "Rentrée"/"Rentrées Alternants"
horodatées propres à ces années (ex. "Rentrée 11h00" le 1er février 2027
pour BUT2-DEV-FI/BUT2-CREACOM-FC S4, "Rentrée 14h00" même jour pour
BUT3-DEV-FI/BUT3-DEV-FC/BUT3-CREACOM-FC S6) — jamais chargées ni
bloquées pour un run multi-parcours.

**Corrigé** : nouvelle fonction `load_mmi_planning_for_semestres(data_root,
semestres)` (`planning_loader.py`) — fusionne `load_mmi_planning` sur
PLUSIEURS semestres réels à la fois (sûr : `semester_week_offset` est
identique — 0 — pour S1/S3/S5, vérifié). Câblée à TOUS les points d'appel
concernés, chacun recalculant la liste des semestres réels à partir des
séances effectivement en jeu (pas de l'ancre) :
- `cpsat.py::TimetableSolver.solve_decomposed` (mode décomposé, production)
- `cpsat.py::TimetableSolver._build_hard_model` (modèle joint, `solve`/`solve_tiered`)
- `decomposed.py::solve_decomposed` (événements du planning officiel, étage 3)
- `api/main.py::timetable_view` (affichage live, `GET /`)
- `api/regen.py::regen_and_persist` (régénération ciblée)
- `cli.py::cmd_export` (export HTML autonome)

Volontairement PAS touché : `api/main.py::_hard_constraint_context` —
déjà correct, utilise `session.semestre` (le semestre réel d'UNE séance
précise, jamais une ancre de groupe).

4 nouveaux tests (`tests/test_planning_loader.py`) : l'ancre seule ne voit
aucun code BUT2/BUT3 (preuve que le test est significatif face au bug
d'origine), la fusion multi-semestres les couvre bien (SAE et
événements), et un semestre listé en double ne duplique pas ses fenêtres.

**Impact** : nécessite un nouveau calcul complet pour corriger les 260
violations SAE déjà en production, cf. §38 pour le résultat vérifié.

## 38. Salles — effectifs FC corrigés (retour utilisateur, 07/08/2026)

Retour utilisateur : les BUT2/BUT3-CREACOM-FC font TOUJOURS plus de 15
personnes, y compris en TP (groupe unique, jamais scindé) — éviter les
petites salles. Les BUT3-DEV-FC sont EN DESSOUS de 15 (effectif réel : 6)
— privilégier les petites salles (ex. H.005, "c'est parfait"). H.005 a
justement une capacité de 15 pile — le seuil compte.

Vérifié : `_headcount_for_groups`/`assign_rooms` filtrent déjà par
`capacity >= headcount` puis trient par type de salle préféré (ordre de
`rooms.yaml` en cas d'égalité, H.005 est la 1ère salle `tp_standard`
listée) — aucun changement de logique nécessaire, seul l'effectif
(`groups.yaml`) était faux : BUT3-CREACOM-FC était à 15 pile (donc H.005
ÉLIGIBLE à tort, confirmé sur le run réel : 9 séances BUT3-CREACOM-FC en
H.005) ; BUT3-DEV-FC était à 20 (donc H.005 exclue à tort — 0 séance en
H.005 sur le run réel, malgré "H.005 c'est parfait").

**Corrigé** (`groups.yaml`), chiffres donnés par l'utilisateur : BUT2-CREACOM-FC
reste à 18 ("pas encore connu mais > 15, on peut partir sur 18") ;
BUT3-CREACOM-FC 15 → **19** ("18-20", milieu retenu) ; BUT3-DEV-FC 20 →
**10** (effectif réel 6, "8-10 si on prend large", haut de fourchette
retenu). Revérifié : H.005 exclue pour BUT2/BUT3-CREACOM-FC (19>15),
éligible pour BUT3-DEV-FC (10≤15).

## 39. Recalcul complet avec tous les correctifs de la soirée (07/08/2026)

Relance `--decomposed --semestre-group odd --weeks 24 --fi-max-week 18`
avec l'ensemble cumulé : §35 (événement + KBR + rééquilibrage présence
FC), §36 (lissage BUT3), §37 (sanctuarisation SAE + événements multi-
semestres — le plus significatif), §38 (effectifs salles FC).

**3 tentatives avant convergence** (`PARTIAL_WEEKS_FAILED:[5,7,9]` →
`PARTIAL_WEEKS_FAILED:[7,8]` → `FEASIBLE`) — attendu et cohérent avec le
constat du projet : la sanctuarisation SAE de BUT2/BUT3 était
INEXISTANTE sur tous les runs précédents de la soirée (§37), donc chaque
essai précédent avait artificiellement plus de marge ; une fois la vraie
contrainte active, retrouver une solution demande la même variance de
graine déjà documentée ailleurs sur ce projet (cf. §14/§17.3/§27).
Semaines 7-8 revenues 2 fois de suite — signal potentiellement
structurel (comme pour le bug §27) plutôt que pur bruit, mais résolu à
la 3e tentative sans investigation supplémentaire nécessaire.

Vérifié sur la sortie réelle (pas seulement le statut du solveur) :
statut, 0 conflit enseignant/groupe/salle, 0 violation PAC, KBR jamais à
8h, présence FC 100% respectée (3/3 parcours), **0 violation de
sanctuarisation SAE** (contre 260 avant le correctif §37), salles FC
cohérentes avec les effectifs corrigés (H.005 : 0 séance BUT2/BUT3-CREACOM-FC,
10 séances BUT3-DEV-FC), répartition BUT3 vers les créneaux non-bordure
(7,0% en 8h/17h sur ce run). Chargé dans l'interface (port 8123, run
id=21, 2391/2391). Suite
pytest complète : 78/78.

## 40. Structure des groupes, SAE des alternants, capacité physique (08/08/2026)

Série de retours utilisateur ("les 3e années n'ont pas de SAE", "le TD CD en
3e année FI n'a pas de cours", "en FC il faut considérer tous les cours
comme des TD car c'est un même groupe", "pour les 3e année dev FC il faut
les mettre dans la H.005", "refais un check de toutes les contraintes").
Six correctifs, dont quatre bugs réels, tous vérifiés sur données réelles.

### 40.1 SAE des alternants jamais détectées (notation différente)

Les feuilles d'alternants (`S3S4CREACOM-FC`, `S5S6DEV-FC`,
`S5S6CREACOM-FC`) notent leurs SAE avec le **code de cours brut**
(`WSA501C`, `WSA502D`, `WSA666`), jamais avec le mot "SAE" — la seule
notation que reconnaissait `_normalize_sae_token`. Ces journées finissaient
donc classées en simples événements informatifs : **zéro sanctuarisation**
pour BUT3-DEV-FC et BUT3-CREACOM-FC (0 jour SAE avant, 2 et 12 après).
Corrigé par un second motif `WSA?(\d{2,3})[A-Z]?` en `fullmatch` — volontaire,
pour ne pas attraper `WS5PJ`/`WSA5PRJ` (projet enseignants) ni une cellule
contenant du texte libre. Le numéro seul est retenu, la convention de la
feuille faisant foi (la feuille CREACOM-FC écrit "WSA401C" alors que le vrai
code BUT2 est "WSA401M").

### 40.2 BUT3-DEV-FI : groupes orphelins

`groups.yaml` déclarait 2 TD (AB/CD) + 4 TP pour 50 étudiants, alors que la
maquette déclare **1 TD + 2 TP** sur les 14 modules S5 sans exception.
`_td_group_ids`/`_tp_group_ids` ne prenant que les `groupes_td`/`groupes_tp`
premiers groupes, TD CD et TP C/D ne recevaient jamais aucune séance.
Décision utilisateur : "suis la maquette" — groupes en trop supprimés,
effectif ramené à 25 (= 13 + 12, somme des 2 TP conservés) au lieu de 50 :
un groupe TD unique de 50 ne tiendrait dans aucune salle `standard`
(35 places) et basculerait tout en amphi. **À confirmer** si l'effectif réel
diffère.

### 40.3 Cohortes à groupe unique : tout en TD

BUT2-CREACOM-FC, BUT3-CREACOM-FC et BUT3-DEV-FC déclarent 1 TD **et** 1 TP :
les deux "groupes" sont la même cohorte physique. Le découpage produisait
deux entrées distinctes pour les mêmes étudiants dans l'interface et faisait
viser des salles TP à un groupe qui ne se scinde jamais. Les séances TP sont
désormais émises en TD sur le groupe TD unique — dérivé de la maquette
(`groupes_td == groupes_tp == 1`) plutôt que codé en dur, donc les parcours
qui se scindent réellement (BUT1 4/8, BUT2-DEV-FI 2/4, BUT3-DEV-FI 1/2) ne
sont jamais concernés. L'affectation d'enseignant reste calculée sur le type
d'ORIGINE (`block.tp` ≠ `block.td`) : seuls le type émis et le groupe cible
changent, le volume total est conservé (test dédié).

Le groupe TP reste déclaré dans `groups.yaml` : il porte la définition de la
cohorte étudiante utilisée par le plafond hebdomadaire. Il est en revanche
masqué de l'interface (`build_payload` + `/meta` filtrent tout groupe sans
séance) pour ne pas afficher une entrée systématiquement vide.

### 40.4 Salles : "best fit" + petites salles pour BUT3-DEV-FC

À type de salle égal, `assign_rooms` retenait la première salle déclarée
dans `rooms.yaml` ; un groupe de 8 pouvait donc occuper une salle de 30
pendant qu'une salle de 15 restait libre. Tri secondaire par capacité
croissante ajouté. Complété par une règle dédiée pour les 9 modules
`WRA50xD` non-anglais de BUT3-DEV-FC (`tp_standard` en préféré) : leurs
séances étant toutes émises en TD, elles auraient sinon visé les salles
`standard` (toutes à 35 places). Résultat mesuré : **92 séances sur 173 en
H.005** pour BUT3-DEV-FC, **0** pour BUT2/BUT3-CREACOM-FC (19 étudiants > 15
places).

### 40.5 Événements du mardi 8 septembre — attribution corrigée

Correction d'une erreur introduite la veille : l'horaire donné par
l'utilisateur avait été appliqué au mauvais événement. Réalité confirmée :
**"Échange IA" = 9h30-12h30** (créneaux 1-2) et **"Présentation des services
aux nouveaux étudiants" = 17h-18h30** (créneau 5). Les deux plages sont
désormais bloquées, ce qui correspond exactement au retour "le mardi de la
3e semaine les cours de 9h30 à 12h30 et de 17h à 18h30 sont interdits".

### 40.6 Capacité PHYSIQUE des semaines — cause des runs de 7 h

Symptôme : après activation des SAE partout (§40.1), le pipeline tournait
**7 heures sans converger**. Diagnostic instrumenté semaine par semaine
(`scratchpad/diag_weeks.py`) : l'étage 2 convergeait en 184 s, mais 4
semaines étaient déclarées **INFEASIBLE en 0-10 s** — donc *prouvées*
impossibles, pas un manque de temps.

Cause : les plafonds de l'étage 2 étaient des plafonds **nominaux** (22
FI / 23 FC créneaux, 26 par enseignant) sans aucune conscience de ce que la
semaine peut *physiquement* contenir. Exemple : semaine 15, 23 séances
affectées à BUT3-CREACOM-FC alors que 2 jours sur 5 sont sanctuarisés SAE,
soit 18 créneaux maximum. Trois angles morts corrigés :

- **Cohorte** : nouveau `_physical_slots_by_week(...)` — jours ouvrables
  moins fériés, moins journées SAE, moins jeudi après-midi PAC (FI), et pour
  les alternants uniquement leurs jours de présence IUT. Le plafond devient
  `min(nominal, physique − marge)`.
- **Enseignant** : `_teacher_available_slots_by_week` ignorait les fériés
  ET le fait qu'un enseignant intervenant *uniquement* en FI ne peut jamais
  utiliser le jeudi après-midi. Mesuré : JLE plafonné à 21 créneaux en
  semaine 8 pour un maximum réel de 18 — l'étage 2 lui en assignait 20.
  Un défaut physique est aussi calculé pour les enseignants sans
  disponibilité déclarée, qui gardaient sinon le plafond nominal.
- **Rééquilibrage** : `_rebalance_failed_weeks` bornait par le plafond
  nominal uniquement — une semaine à 2 jours ouvrables paraissait attractive
  puisque son compteur d'occupation était bas. Il reçoit désormais les mêmes
  capacités physiques.

Une `physical_margin` de 2 créneaux est laissée sous la capacité physique
(cohorte et enseignant) : remplir jusqu'au dernier créneau rend l'étage 3
infaisable dès qu'il doit entrelacer plusieurs cohortes et enseignants sur
les mêmes créneaux — constaté sur des semaines où *aucune* ressource n'était
individuellement saturée (BUT1 22/27, JLE 20/21) mais sans combinaison
valide. Vérifié avant application que le volume total tient pour chaque
cohorte.

**Une tentative antérieure de réduction avait été abandonnée (cf. §14)** :
elle retranchait les jours bloqués du plafond NOMINAL, ce qui rendait
l'étage 2 lui-même infaisable. Le `min(...)` avec la capacité physique ne
peut jamais durcir au-delà du réel.

### 40.7 Constat structurel : BUT1 saturé à ~89%

Vérifié, à signaler à l'équipe pédagogique : la maquette BUT1-S1 demande
**216 séances par étudiant (324 h)** de cours classiques, alors que **37 %
du semestre est sanctuarisé SAE** (35 jours sur 95), dont **4 semaines
entièrement bloquées** (11, 15, 16, 17) et 4 fortement amputées. Il reste
~11 semaines utilisables, soit ~20 séances/semaine (30 h) contre un plafond
de 22 (33 h) : **216 séances pour 244 créneaux réellement disponibles, 89 %
d'occupation**. Ce n'est pas un bug — c'est ce que disent les données — mais
ça explique la difficulté de convergence et laisse très peu de marge à toute
contrainte supplémentaire.

### 40.8 Résultat vérifié

`FEASIBLE`, **2391/2391** séances placées, 245 trous, **0 jour isolé**.
Vérificateur global (`scratchpad/verify_all.py`, 13 familles de contraintes)
: **0 échec** — 0 conflit enseignant/groupe/salle, 0 salle en sous-capacité,
0 séance FI le jeudi après-midi, 0 cours classique un jour SAE (les 6
parcours ont bien des jours SAE), 0 cours sur un événement horodaté, les
créneaux du mardi de la semaine 3 et la rentrée BUT3-FI sont libres, 0
séance d'alternant hors semaine de présence, FI terminée avant le 1er
février, 0 séance BUT1 en semaine d'intégration, disponibilités enseignants
respectées (dont KBR jamais à 8 h), cohortes à groupe unique toutes en TD,
salles cohérentes avec les effectifs. Suite pytest : **94/94**. Chargé dans
l'interface (port 8123, run id=22).

## 41. Continuité de salle + Vue Semaine des cohortes FC (08/08/2026)

### 41.1 Changement de salle entre créneaux consécutifs

Retour utilisateur, capture à l'appui (WRA507D/Barthélémy TOMASINA réparti
sur H.007, puis H.201, puis H.008 sur trois créneaux qui s'enchaînent) :
"c'est la même matière et le même prof à chaque heure consécutive, il
faudrait donc que ce soit dans la même salle et qu'il n'y ait pas de
changement".

`assign_rooms` n'avait aucune notion de continuité hors `same_room_for_course`,
réservé aux CM et qui fige au contraire UNE salle pour tout le semestre.
Mesure initiale : **40 ruptures de salle sur 158 enchaînements** (même cours,
même groupe, même enseignant, créneaux contigus le même jour).

Une première approche par simple reconduction séance après séance a échoué :
une autre séance traitée avant, au même créneau, raflait la salle
entre-temps. Retenu à la place — nouvelle fonction `_consecutive_runs(...)`
qui regroupe en amont les séances enchaînées, puis **réservation de la salle
pour toute la série dès sa première séance**. Si aucune salle n'est libre de
bout en bout, la série se scinde plutôt que de créer un conflit (test dédié).
Les évaluations sont exclues du regroupement : elles doivent passer par leur
règle A.018. Résultat : **0 rupture sur 158**, et la vérification globale
reste à 0 échec (dont 0 double-booking).

### 41.2 Aucun cours visible en Vue Semaine pour les cohortes FC

La Vue Semaine excluait *tous* les groupes TD (`groupKind !== 'td'`), au
motif qu'un TD s'affiche en deux colonnes TP — incompatible avec un
glisser-déposer par séance. Or depuis §40.3 les cohortes à groupe unique
portent TOUTES leurs séances sur leur unique groupe TD, et leur groupe TP
(vide) est désormais masqué : il ne restait donc que la promo, elle-même
sans séance. Aucun cours n'était visible pour BUT2-CREACOM-FC,
BUT3-CREACOM-FC ni BUT3-DEV-FC.

Corrigé : le filtre exclut désormais uniquement les TD qui se scindent
réellement (`payload.groupTpPair[gid]` présent). `renderSemaineTab` n'utilise
de toute façon jamais le mode deux colonnes. Les 3 cohortes FC sont à nouveau
sélectionnables et affichent leurs cours.