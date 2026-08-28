# Contraintes structurées — Générateur EDT BUT MMI 2026-2027

**Ces fichiers sont GÉNÉRÉS. Ne jamais les éditer à la main.**

Ils sont produits par `scripts/build_contraintes.py` à partir des fichiers
sources officiels de `contraintes_update/` (CSV Google Sheets, `maquette.json`,
`progression.json`, maquettes `.docx`). Après toute mise à jour d'un fichier
source :

```powershell
python scripts/build_contraintes.py
```

## Fichiers et provenance

| Fichier | Contenu | Source |
|---|---|---|
| `01_regles_generales.json` | Règles stables : créneaux horaires, plafonds 33h/35h, couches de priorité, logique de compactage, modes de répartition, cartographie des salles, règle de sanctuarisation SAE | Conversation préparatoire (aucun fichier officiel équivalent) — **non généré** |
| `02_calendrier_iut.json` | Vacances/pauses pédagogiques, jours fériés, jalons | `INDISPONIBILITÉS IUT TROYES - 2026-2027` |
| `03_calendrier_alternance_officiel.json` | Semaines IUT vs entreprise pour BUT2-FC et BUT3-FC + conflits détectés contre le calendrier IUT | `DISPONIBILITÉS ÉTUDIANTS BUT2` + `BUT3` |
| `05_enseignants_contraintes.json` | 23 enseignants : indisponibilités, **disponibilités en liste blanche**, règles de parité de semaine, regroupement mensuel | `CONTRAINTES ENSEIGNANTS MMI 2026_2027` |
| `06_salles.json` | Cartographie du bâtiment H | Conversation préparatoire — **non généré** |
| `07_modules_maquette_progression.json` | 182 modules fusionnant maquette (enseignants/volumes/blocs) et progression (ordre des séances, ordonnancement inter-modules) | `maquette.json` + `progression.json` |
| `08_alertes_qualite_donnees.json` | Conflits calendrier, incohérences maquette, SAE sans dates, points ouverts | Calculé |
| `09_dates_sae.json` | Dates de chaque SAE, **module par module**, avec restriction de groupe éventuelle | `DATES SAE 2026_2027` |
| `10_dates_fixes.json` | Événements fixes horodatés (rentrées, interventions), **avec le parcours concerné** ; `annules` liste ceux retirés par arbitrage | `Dates MMI 26_27 - DATES OK` |
| `maquette.json` / `progression.json` | Copies figées des exports officiels — `ingestion/fetch.py` les préfère au téléchargement distant | `contraintes_update/` |

`04_planning_hebdomadaire_par_promo.json` a été **supprimé** le 10/08/2026 :
remplacé par `09` + `10`, qui nomment directement le module et le parcours là
où l'ancienne feuille de tableur obligeait à deviner à quel code de cours
correspondait un libellé « SAE103 » selon la piste.

## Arbitrages utilisateur du 10/08/2026

Ces décisions ne se déduisent d'aucun fichier — elles ont été prises
explicitement et sont câblées dans `scripts/build_contraintes.py`
(cf. `_ARBITRAGES`) ou dans `data/config/*.yaml`.

1. **`DATES SAE` fait foi, sans repli.** L'ancien planning n'est plus lu. En
   conséquence, **S2/S4/S6 sont hors périmètre** pour 2026-2027 : le fichier ne
   date que les SAE de S1/S3/S5. `pipeline.py::SEMESTRES_HORS_PERIMETRE`
   avertit si on les demande quand même.
2. **WS502D** : le découpage « 12/01 (AB) & 19/01 (CD) » vient d'une année
   antérieure. BUT3-DEV-FI n'a plus qu'un TD (AB) : seules les dates du 12 et
   13 janvier 2027 sont retenues, **pour le TD AB uniquement**.
3. **Événements fixes = `Dates MMI` uniquement.** Les repères de l'ancien
   planning (Intégration, Clés de Troyes, Conseil, Rattrapages, Stages,
   Soutenances) disparaissent. Le S1 ne démarre pas avant le lundi 7 septembre
   2026 (semaine 3) ; les dates de fin de semestre FI/FC restent inchangées.
4. **Parité TCA** = numéro de semaine **département** (semaine 1 = ISO 35 2026),
   basculable en ISO via `parity_reference` dans `05`, sans toucher au code.
5. **Disponibilités = liste blanche DURE** (MNI, VBU, KNG, EHU) : les jours non
   listés sont interdits. Sans ça, VBU — qui ne déclare aucune indisponibilité
   mais n'est là que lundi/mardi/mercredi — restait plaçable les 5 jours.
6. **RHU** indisponible du **lundi 19 au vendredi 23 octobre 2026** : le fichier
   source écrit « du mardi 19 au vendredi 22 », or le 19 est un lundi et le 22
   un jeudi — la semaine entière est bloquée pour couvrir les deux lectures.
7. **ARA et JHU** : regroupement mensuel en objectif **mou** fortement pondéré
   (ARA porte à lui seul les 34 TD de WRA507C ; en dur le problème risquerait
   l'infaisabilité).
8. ~~**WS501D** : le plan enseignant détaillé d'ALO est ignoré.~~
   **Annulé et remplacé le 25/08/2026, cf. arbitrage 13 ci-dessous.**
9. **WRA505C** : ALO avant AFR en objectif mou.
10. **WRA308M** : bloc de 4h30 sur les **3 derniers TD uniquement**.
11. **WR100BU** : fenêtres de dates **dures** par séance.

## Arbitrages utilisateur du 25/08/2026

12. **VSS du 17/09/2026 annulé** (9h30-11h, Amphi GMP/GEII, S1) : retiré des
    événements bloquants via `_CANCELLED_FIXED_EVENTS`, le créneau redevient
    plaçable. Le CSV source n'est PAS édité — une réexportation de la feuille
    Google écraserait la correction et on perdrait la trace de la décision.
    L'événement reste visible dans `10_dates_fixes.json > annules`.
13. **WS501D : le plan d'Ariane Loizon est appliqué** (annule l'arbitrage 8),
    via `data/config/sae_teacher_phases.yaml`. Il ne change pas les dates de la
    SAE (le fichier officiel fait toujours foi) mais dit QUI l'encadre quand,
    ce qui libère les autres créneaux de chaque enseignant :
    - FME du 19 au 22 octobre (10 TD) ;
    - **SLO du 19 au 23 octobre** (9 TD) — demandés à l'origine « entre le 26
      et le 30 octobre », semaine où l'IUT est fermé (pause de la Toussaint) et
      pour laquelle `DATES SAE` n'a aucune fenêtre. **Ariane Loizon a confirmé
      le 26/08/2026** (via Kyllian Bresson) qu'il s'agissait de la semaine
      PRÉCÉDENTE. Contradiction close ;
    - FME et ALO du 12 novembre au 15 janvier (5 TD chacun).

    Effet mesurable : ALO passe de 22 jours bloqués sur cette seule SAE à 6,
    et redevient disponible en octobre pour démarrer la WRA505C comme elle le
    demande.
14. **Séance conjointe WRA505C ∥ WS501D** : la séance d'ordre 17 de la WRA505C
    (la dernière portée par ALO) est bornée aux jours de SAE WS501D qui sont
    aussi des jours de présence IUT des alternants CREACOM-FC — 26/27 novembre,
    17/18 décembre, 7/8 janvier. Liste **dérivée** des deux calendriers, pas
    choisie. ALO est libérée de la WS501D ces jours-là (`exclure`).
15. **WSA501D planifiée par le solveur** : seule SAE sans aucune date au
    fichier officiel, mais dont les 34 TD doivent figurer à l'EDT (demande
    utilisateur). Déclarée dans
    `course_scheduling_rules.yaml::solver_scheduled_sae`, découpée en 17 blocs
    de 3h (`double_sessions.yaml`) et étalée sur les 10 semaines de présence
    IUT du parcours.
16. **WRA507D se termine en janvier** : borne dure semaine-index 18 (25-29
    janvier 2027) via `max_week_rules`. Les 8 premières semaines de présence
    BUT3-DEV-FC offrent 184 créneaux pour 173 créneaux de ressources : seule la
    SAE WSA501D a vocation à occuper février et mars.
17. **Vœux EDT « projet Webdocumentaire »** (BUT2-DEV-FI S3, Anthony Rageul,
    `voeux EDT 2026-2027.pdf`) : WR308D CM + TD 1-3 en septembre, TP en
    décembre (fenêtres dures) ; WR304D / WR311D / WR301D bornés au **plancher**
    d'octobre seulement (`min_week: 4`). Pas de borne haute : le document est un
    vœu et précise lui-même que « la répartition CM, TD, TP est à revoir ». Le
    placement des CM de WS302D « vers la moitié » puis « à la toute fin » de la
    SAE n'est PAS modélisé — cette SAE reste organisée par ses enseignants.

18. **WRA507D : répartition alternée** (retour utilisateur du 25/08/2026, après
    l'ajout de Jules Sabater à la maquette). Les 34 TD, partagés 17/17 entre
    Barthélémy Tomasina et lui, alternent une séance sur deux
    (`course_scheduling_rules.yaml::teacher_distribution`) au lieu de former
    deux blocs contigus. **Non appliqué à WSA501D** : l'extension y avait été
    faite « par cohérence », sans demande ; mesurée sur 3 graines, elle
    n'apportait rien (4,3 contre 4,7 semaines en échec, à l'intérieur d'une
    variance de 3 à 6 à configuration identique) et a été retirée — une règle
    qu'on ne peut pas justifier par une demande ni par une mesure ne doit pas
    survivre. WRA505C garde délibérément ses blocs contigus (ALO au début,
    AFR à la fin, cf. arbitrage 9).

19. **Le reliquat de séances non placées est assumé, pas caché** (décision de
    l'utilisateur du 26/08/2026, prise au vu des mesures). Le solveur place
    ~96,5 % des séances ; les dernières butent sur des combinaisons prouvées
    infaisables — 8 semaines sur 24 démontrées impossibles en 0,1 s, sans le
    moindre dépassement de capacité (cf. docs/DATA.md §66). Deux réponses,
    complémentaires : l'étage 2 apprend désormais de ces preuves (coupes de
    Benders logiques, `--benders-rounds`), et ce qui résiste se place à la
    main depuis l'onglet **« À placer »**, qui ne propose que des créneaux
    déjà vérifiés. Avant cela ces séances disparaissaient sans bruit : le
    planning avait l'air complet alors qu'il manquait des heures.

20. **Trois demandes ponctuelles de Kyllian Bresson, 26/08/2026** — ajoutées
    via deux mécanismes qui n'existaient pas jusque-là. Indisponibilité
    enseignant à une DATE ET UN HORAIRE précis (`TeacherDateSlotRule`,
    `teacher_availability.yaml`) : FLI et AFR indisponibles le 3/09/2026
    9h30-12h30 (pré-rentrée BUT2 FC alternants), sans perdre leur après-midi.
    Salle réservée par un tiers (`salles_reservees.yaml`) : amphi H.018
    réservé le 11/09/2026 9h30-12h30 (besoin Direction) — ne déplace aucun
    cours, force seulement l'attribution à trouver une autre salle. Romain
    Delon n'a pas eu besoin d'être marqué indisponible le 3/09 : aucun de ses
    quatre parcours n'a cours cette semaine-là (vérifié, pas supposé).

21. **Six défauts trouvés en auditant le résultat de la complétion
    automatique, 27/08/2026** (cf. docs/DATA.md §67) : score de la boucle de
    coupes qui comptait des semaines au lieu de séances, ordre pédagogique
    inter-cours absent du placement manuel, contraintes enseignant réelles
    perdues par la commande CLI (YAML seul, sans fusion CSV), présence des
    alternants FC jamais vérifiée hors du solveur, ordre au grain de la
    semaine plutôt que du créneau, glouton traitant des séances liées dans le
    mauvais sens. Tous corrigés — résultat final : 2962/3101 (95,5 %), le
    reste rendu à l'onglet « À placer » avec son motif.

## Points restés ouverts

- **Demi-journée de PTUT mensuelle commune DEV / CREACOM** (demande d'Ariane
  Loizon) : non modélisée. Le PTUT n'existe dans aucune progression comme
  séance à placer (`SessionType.PTUT` n'est jamais émis), il n'y a donc rien à
  contraindre aujourd'hui — il faudrait d'abord décider du volume et du
  porteur.
- **Dates de début de stages BUT2 et BUT3** : « à définir pour mi-avril ».
  Listées dans `10_dates_fixes.json > a_fixer`.
- **Salles** : aucun fichier source officiel. `01_regles_generales.json` et
  `data/config/rooms.yaml` viennent de la conversation préparatoire.
- **BUT2-DEV-FC gelé** cette année (effectif alternants insuffisant, cf.
  `Maquette 2026 BUT2 S3-DEV-FC.docx`) : aucun module dans la maquette, le
  solveur l'ignore naturellement. `Dates MMI` lui donne pourtant une rentrée le
  14 septembre 2026 — sans effet, mais à retirer de la source si le gel se
  confirme.
