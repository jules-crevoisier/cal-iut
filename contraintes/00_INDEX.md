# Package de données structurées — Générateur EDT BUT MMI 2026-2027

Ce package remplace et complète les extractions précédentes issues uniquement de la conversation PDF : il est construit **directement à partir des 6 fichiers sources officiels** que tu as fournis (CSV/XLSX/JSON), qui font foi. Les fichiers JSON numérotés sont conçus pour être chargés indépendamment par ton algorithme.

## Fichiers et provenance

| Fichier | Contenu | Source |
|---|---|---|
| `01_regles_generales.json` | Règles stables : créneaux horaires, plafonds 33h/35h, couches de priorité, logique de compactage, 3 modes de répartition, cartographie des salles, règle de sanctuarisation SAE | Conversation préparatoire (aucun fichier officiel équivalent fourni) |
| `02_calendrier_iut.json` | Vacances/pauses pédagogiques, jours fériés, jalons (rentrées, fin de semestre) | `INDISPONIBILITE_S_IUT_TROYES_-_2026-2027_-_Feuille_1.csv` |
| `03_calendrier_alternance_officiel.json` | Semaines IUT vs entreprise pour BUT2-FC et BUT3-FC + conflits détectés automatiquement contre le calendrier IUT | `DISPONIBILITE_S_E_TUDIANTS_S3-FC___S4-FC...csv` + `...S5-FC___S6-FC...xlsx` |
| `04_planning_hebdomadaire_par_promo.json` | Le planning officiel semaine par semaine (48 semaines) pour les 7 promotions/parcours (S1S2, S3S4-FI, S3S4DEV-FC, S3S4CREACOM-FC, S5S6-FI, S5S6DEV-FC, S5S6CREACOM-FC) : SAE actives, vacances, stages, rentrées, événements ponctuels | `Plannings_MMI_2026_2027.xlsx` (cellules fusionnées résolues) |
| `05_enseignants_contraintes.json` | 20 enseignants avec contraintes brutes + une tentative de tokenisation (jour récurrent vs date précise) | `CONTRAINTES_ENSEIGNANTS_MMI_2026_2027_-_Feuille_1.csv` |
| `06_salles.json` | Cartographie du bâtiment H | Conversation préparatoire (pas de fichier officiel dédié fourni) |
| `07_modules_maquette_progression.json` | **182 modules** fusionnant la maquette (enseignants/volumes/blocs) et la progression pédagogique (ordre des séances CM/TD/TP, contraintes d'ordonnancement inter-modules) | `maquette.json` + `progression.json` (jointure sur `code_matiere`, unique) |
| `08_alertes_qualite_donnees.json` | Conflits calendrier détectés, incohérences numériques dans la maquette, points restés flous | Calculé automatiquement + notes manuelles |

## Points critiques à connaître avant intégration

1. **Conflit non signalé par le fichier source lui-même** : la semaine du **26 au 30 avril 2027** est indiquée comme semaine IUT pour les **BUT3-FC (S5/S6)**, mais elle tombe entièrement dans la pause pédagogique de printemps de l'IUT. Contrairement au fichier BUT2-FC (qui auto-signale ses propres semaines en conflit avec la mention "mais IUT en pause pédagogique"), le fichier BUT3-FC ne signale rien pour cette semaine-là. Voir `08_alertes_qualite_donnees.json`.
2. Le fichier `CONTRAINTES_ENSEIGNANTS` **confirme et clarifie** plusieurs points restés incertains dans l'extraction précédente issue du PDF :
   - Barthélémy Tomasina (BTO) : disponible **mardi matin + mercredi**, indisponible mardi après-midi/jeudi après-midi/lundi/vendredi (résout l'incohérence signalée précédemment).
   - Kévin Ngo (KNG) : en réalité indisponible le **vendredi** et la semaine du **2 au 6 novembre 2026** ; disponible lundi/mardi/mercredi toute la journée, jeudi à partir de 14h (pas "disponible le jeudi matin" comme indiqué dans une ancienne note).
3. Le fichier `maquette.json` (182 modules) est **beaucoup plus complet** que ce qui avait été traité manuellement dans la conversation (qui ne couvrait en détail que S1 et une partie de S3-DEV-FI) : il couvre **tous les semestres S1 à S6** et les 3 parcours. C'est désormais la source de référence pour les volumes et enseignants.
4. Le fichier `progression.json` apporte une donnée qui n'existait dans aucun document précédent : **l'ordre pédagogique des séances** (CM/TD/TP, quelles séances sont des évaluations) et des **contraintes d'enchaînement entre modules** (`ordonnancement`, ex. "WR103 après WR112, avant WS101"). 53 modules sur 182 ont une progression définie.
5. `08_alertes_qualite_donnees.json` liste 36 incohérences numériques (nombre de groupes déclaré vs somme des groupes par enseignant) — fréquentes sur les SAE/PTUT où le champ ne compte pas forcément des groupes concurrents. À vérifier au cas par cas, ne pas corriger automatiquement.

## Ce qui reste à apporter (non couvert par les fichiers fournis)

- Un fichier de salles officiel (la cartographie actuelle vient uniquement de la conversation préparatoire).
- Les contraintes textuelles complexes de certains enseignants (Ariane Loizon sur WS501D/WRA505C, Thomas Castellengo sur la parité de semaine, Marine Riguet sur WR106/WRA308C) restent en texte libre dans `05_enseignants_contraintes.json` (`contraintes_pedagogiques_raw`) : elles nécessitent un encodage manuel dédié au moment de traiter ces modules précis, car leur logique est trop spécifique pour une règle générique.
