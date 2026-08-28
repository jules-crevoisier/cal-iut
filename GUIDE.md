# Guide de reprise — produire les emplois du temps MMI

Ce guide s'adresse à la personne qui reprend l'outil sans l'avoir écrit. Il ne
suppose aucune connaissance du code ni du solveur. Suivez-le dans l'ordre.

> Le `README.md` explique comment l'outil fonctionne à l'intérieur. Ce
> guide-ci explique seulement comment s'en servir.

---

## 0. En trois lignes

L'outil lit des fichiers officiels (maquette, progression, contraintes des
enseignants, calendrier), en déduit toutes les séances à placer, puis cherche un
emploi du temps qui respecte les règles. Vous n'écrivez jamais d'emploi du temps
à la main : vous **corrigez les données d'entrée** et vous **relancez**.

---

## 1. Installation (une seule fois)

Il faut **Python 3.13**. Ouvrez PowerShell dans le dossier du projet :

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Puis l'interface web (facultatif mais recommandé) :

```powershell
cd frontend
npm install
npm run build
cd ..
```

Vérifiez que tout est en place :

```powershell
cal-iut doctor
```

Cette commande liste ce qui va et ce qui manque, **et vous dit exactement quelle
commande taper ensuite**. Si vous ne savez pas quoi faire, c'est toujours elle
qu'il faut relancer.

---

## 2. Les fichiers que VOUS fournissez

Tout se joue dans le dossier `contraintes_update/`. Ce sont les seuls fichiers
que vous éditez, et ils viennent tous de l'extérieur (Google Sheets exportés en
CSV, ou exports du serveur MMI).

| Fichier | Ce qu'il contient | D'où il vient |
|---|---|---|
| `maquette.json` | Modules, volumes horaires, enseignants | Serveur MMI (`cal-iut refresh`) |
| `progression.json` | Ordre des séances de chaque module | Serveur MMI (`cal-iut refresh`) |
| `CONTRAINTES ENSEIGNANTS … .csv` | Disponibilités et indisponibilités | Google Sheets à remplir par les enseignants |
| `INDISPONIBILITÉS IUT TROYES … .csv` | Vacances, fériés, fermetures | Direction de l'IUT |
| `DATES SAE … .csv` | Dates de chaque SAE | Responsables de SAE |
| `Dates MMI … .csv` | Rentrées, interventions à heure fixe | Département |
| `DISPONIBILITÉS ÉTUDIANTS BUT2 / BUT3 … .csv` | Semaines à l'IUT des alternants | Service alternance |

**Règle d'or : ne modifiez jamais le dossier `contraintes/`** (sans `_update`).
Il est entièrement regénéré à partir de `contraintes_update/`, vos modifications
y seraient effacées sans avertissement.

### Récupérer la maquette et la progression

```powershell
cal-iut refresh
```

Cette commande télécharge les deux exports officiels et **montre ce qui a
changé** (modules ajoutés, retirés, volumes ou enseignants modifiés) **sans rien
écrire**. Vous lisez, et si cela vous convient :

```powershell
cal-iut refresh --ecrire
```

L'ancienne version est sauvegardée dans `data/sauvegardes/<date>/` avant tout
remplacement. Si le serveur est injoignable et qu'on vous a envoyé les fichiers
par mail, mettez-les dans un dossier et faites `cal-iut refresh --depuis <dossier> --ecrire`.

---

## 3. Produire un emploi du temps

Une seule commande enchaîne tout :

```powershell
cal-iut annee
```

Elle déroule quatre étapes, en s'arrêtant net à la première qui coince :

1. **Régénérer les contraintes** — traduit vos CSV en données exploitables.
2. **Préparer les séances** — déduit la liste de tout ce qu'il faut placer.
3. **Vérifier les données** — c'est l'audit, détaillé au § 4. S'il trouve une
   erreur bloquante, l'outil s'arrête : il vaut mieux corriger une donnée que
   produire un emploi du temps faux.
4. **Construire l'emploi du temps** — plusieurs tentatives successives, en
   gardant la meilleure.

Comptez **30 minutes à plusieurs heures** selon la difficulté. C'est normal :
c'est un problème d'optimisation, pas une mise en forme.

Le résultat est dans `data/generated/timetable_best.json`.

### Pourquoi plusieurs tentatives ?

Le solveur n'est pas reproductible : deux exécutions identiques peuvent donner
des résultats différents, et parfois l'une échoue là où l'autre réussit. Relancer
avec un autre tirage est le moyen le plus efficace de débloquer une situation —
c'est exactement ce que fait l'étape 4 automatiquement.

Si vous voulez insister davantage :

```powershell
python scripts/solve_until_ok.py --max-runs 20 --max-hours 8
```

Chaque tentative est consignée dans `data/generated/solve_runs.jsonl`.

---

## 4. L'audit : votre principal outil de diagnostic

```powershell
cal-iut audit
```

Il ne résout rien, il **vérifie**. Trois niveaux :

- **`[ERREUR]`** — l'emploi du temps sera faux ou impossible. À corriger avant
  de continuer.
- **`[ALERTE]`** — une donnée est probablement mal comprise. À regarder.
- **`[INFO]`** — pour information, notamment les règles que l'outil ne sait pas
  vérifier automatiquement.

Chaque ligne dit **où** est le problème et **quoi faire**. Exemples réels :

> `[ERREUR] min_week_rules : aucun cours WR1119 (S1) dans la maquette — règle sans effet.`
> `faire: Vérifier l'orthographe du code.`

> `[ERREUR] AHA : 22 créneaux de FORMATION INITIALE pour 21 créneaux disponibles hors jeudi après-midi (réservé aux PAC).`
> `faire: Le jeudi après-midi ne compte pas pour la formation initiale. Élargir ses disponibilités, ou basculer une partie de son volume en FC.`

Pour vérifier aussi un emploi du temps déjà produit :

```powershell
cal-iut audit --timetable data/generated/timetable_best.json
```

**Faites-le systématiquement avant de diffuser un planning.** L'audit rejoue
toutes les règles sur le résultat réel et dit lesquelles ne sont pas respectées.

---

## 5. Consulter et diffuser

```powershell
cal-iut serve
```

Ouvrez `http://127.0.0.1:8000/`. Vous y trouvez les vues par groupe, par
enseignant, par promotion, le tableau des contraintes avec leur verdict, la
liste « À traiter » et l'onglet « À placer » (§ 5 bis). Chaque enseignant et chaque groupe a un lien personnel
(onglet *Référence > Liens & partage*) qu'on peut envoyer tel quel.

Pour un fichier autonome à envoyer par mail :

```powershell
cal-iut export --format html --output planning.html
```

---

## 5 bis. Placer à la main ce que l'ordinateur n'a pas su placer

Il est normal qu'il reste des séances. L'outil en place environ **96 %** ; les
dernières butent sur des combinaisons réellement impossibles (un enseignant
disponible seulement le mercredi, un bloc de 3h, et deux autres cours qui se
disputent les mêmes créneaux). Ce n'est pas une question de patience : laisser
tourner plus longtemps n'y change rien.

Ces séances **ne sont pas perdues**. Ouvrez l'onglet **« À placer »**.

**Commencez toujours par le bouton « Tout placer automatiquement ».** L'outil
pose lui-même toutes les séances pour lesquelles il trouve un créneau valable,
les plus difficiles d'abord. Comptez quelques minutes. Il ne déplace jamais un
cours déjà placé, et il vous dit ce qu'il n'a pas su faire, avec la raison. En
pratique il en place la quasi-totalité — il n'en reste qu'une poignée.

Pour celles qui restent :

1. Vous voyez la liste de ce qui manque, avec le nombre restant et le
   pourcentage déjà placé.
2. Cliquez sur une séance : l'outil vous propose des créneaux **déjà vérifiés**.
   Aucun d'eux ne viole une disponibilité d'enseignant, ne tombe un jeudi
   après-midi PAC, n'écrase un autre cours du même groupe ni ne réserve une
   salle déjà prise.
3. Cliquez sur « Placer ici ». C'est fait, et c'est enregistré.

Vous n'avez **jamais** à deviner un créneau ni à vérifier quoi que ce soit
vous-même : si un créneau apparaît dans la liste, il est valable.

Sans passer par l'application, la même chose en une commande :

```powershell
cal-iut completer --timetable data\generated\timetable_best.json
```

(`cal-iut annee` le fait déjà tout seul sur le meilleur run, à la fin.)

**Si aucun créneau n'est proposé**, vous avez deux possibilités :

- **Régénérer la semaine entière** (onglet *Vue Semaine*, bouton de
  régénération) : l'outil réarrange les autres cours de cette semaine pour
  faire de la place.
- **Assouplir une règle** (§ 6) — par exemple autoriser une semaine un peu plus
  chargée, ou élargir la période autorisée d'un cours.

---

## 6. Ajuster une règle

**Commencez par regarder ce qui est déjà en place :**

```powershell
cal-iut regles
```

Cette commande liste, en français et sans jargon, toutes les règles actuellement
actives — avec **la raison de chacune** et le fichier où la modifier. C'est le
point de départ avant toute modification : la moitié des questions (« pourquoi
ce cours ne commence-t-il qu'en octobre ? ») y trouve sa réponse.

Les règles métier vivent dans `data/config/` (fichiers `.yaml`). Ce sont des
fichiers texte, éditables dans n'importe quel éditeur. Chaque entrée est
commentée avec **la raison** et **la personne qui l'a demandée**.

| Vous voulez… | Fichier |
|---|---|
| Changer les groupes ou leurs effectifs | `groups.yaml` |
| Changer les salles ou leurs règles | `rooms.yaml` |
| Qu'un cours ne commence pas trop tôt / ne finisse pas trop tard | `course_scheduling_rules.yaml` (`min_week_rules`, `max_week_rules`) |
| Imposer une séance à une date précise | `course_scheduling_rules.yaml` (`session_date_windows`) |
| Faire des cours de 3h au lieu de 1h30 | `double_sessions.yaml` |
| Alterner deux enseignants sur un module | `course_scheduling_rules.yaml` (`teacher_distribution`) |
| Dire qu'un enseignant intervient au début et l'autre à la fin | `course_scheduling_rules.yaml` (`teacher_order_rules`) |
| Faire placer une SAE par le solveur | `course_scheduling_rules.yaml` (`solver_scheduled_sae`) |
| Dire qui encadre une SAE et quand | `sae_teacher_phases.yaml` |
| Autoriser exceptionnellement une semaine plus chargée | `course_scheduling_rules.yaml` (`weekly_cap_exceptions`) |

**Après toute modification, relancez `cal-iut audit`.** Il vous dira notamment
si votre règle pointe vers un cours qui n'existe pas — une faute de frappe dans
un code de module ne provoque aucune erreur, la règle est simplement ignorée en
silence.

**Écrivez toujours un `note:` expliquant pourquoi.** Dans un an, personne ne se
souviendra de la raison, et une règle sans justification finit par être
supprimée ou, pire, conservée à tort.

---

## 7. Quand ça ne marche pas

| Symptôme | Que faire |
|---|---|
| Je ne sais pas où j'en suis | `cal-iut doctor` |
| « PARTIAL_WEEKS_FAILED » | Des semaines n'ont pas pu être remplies. Lancez `cal-iut audit --timetable <fichier>` : il nomme la semaine et l'enseignant en cause. Sinon, relancez avec plus de tentatives. |
| Il manque des séances au planning | Normal, il en reste toujours quelques-unes. Onglet « À placer » (§ 5 bis) : l'outil propose des créneaux valables, un clic suffit. |
| Une contrainte enseignant n'est pas respectée | `cal-iut audit` — regardez « contrainte non interprétée ». Si sa formulation n'est pas reconnue, reformulez-la dans le CSV. |
| J'ai modifié un CSV, rien n'a changé | Vous avez oublié `python scripts/build_contraintes.py` puis `cal-iut ingest`. `cal-iut annee` fait les deux. |
| Un enseignant n'a aucun cours | `cal-iut audit` — « un enseignant porte du volume mais n'a aucune séance ». |
| Le résultat change à chaque exécution | C'est normal (§ 3). Gardez le meilleur : `timetable_best.json`. |

---

## 8. Formuler les contraintes des enseignants

Le CSV des contraintes est du texte libre, et l'outil doit le comprendre.
Les formulations ci-dessous sont **reconnues de façon fiable** :

- `vendredi après-midi` — tous les vendredis après-midi
- `lundi toute la journée`
- `jeudi 12 novembre 2026` — **une seule** date
- `du lundi 2 au vendredi 6 novembre 2026` — une plage
- `les jeudis après 17h00`
- `mardi de 15h30 à 18h30`

À éviter :

- **Les dates en chiffres seuls** (`23/09/26`) sont désormais comprises, mais
  écrire le mois en toutes lettres reste plus sûr et plus lisible.
- Les formulations conditionnelles (« si possible », « idéalement ») : elles
  sont conservées comme note mais **ne contraignent rien**. Si c'est un vrai
  impératif, écrivez-le comme une indisponibilité.
- Mélanger plusieurs idées dans une case : séparez par ` - `.

Après toute mise à jour du CSV, `cal-iut audit` liste les formulations qu'il
n'a **pas** su traduire. Elles ne s'appliquent pas du tout : c'est la première
chose à regarder.

---

## 9. Changer d'année

L'outil est calé sur 2026-2027 à deux endroits :

- `contraintes/02_calendrier_iut.json`, régénéré depuis le CSV
  « INDISPONIBILITÉS IUT » — remplacez simplement le CSV.
- `src/cal_iut/calendar/academic.py`, constante `DEPARTMENT_WEEK_ANCHOR` : le
  lundi de la « semaine 1 » du département. **À changer chaque année** (c'est la
  seule modification de code nécessaire).

Puis :

```powershell
cal-iut refresh --ecrire
cal-iut doctor
cal-iut annee
```

Les arbitrages humains de l'année précédente (décisions qui ne se déduisent
d'aucun fichier) sont listés dans `contraintes/00_INDEX.md`. **Relisez-les** :
certains ne valent que pour une année donnée.
