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
| `05_enseignants_contraintes.json` | 22 enseignants : indisponibilités, **disponibilités en liste blanche**, règles de parité de semaine, regroupement mensuel | `CONTRAINTES ENSEIGNANTS MMI 2026_2027` |
| `06_salles.json` | Cartographie du bâtiment H | Conversation préparatoire — **non généré** |
| `07_modules_maquette_progression.json` | 182 modules fusionnant maquette (enseignants/volumes/blocs) et progression (ordre des séances, ordonnancement inter-modules) | `maquette.json` + `progression.json` |
| `08_alertes_qualite_donnees.json` | Conflits calendrier, incohérences maquette, SAE sans dates, points ouverts | Calculé |
| `09_dates_sae.json` | Dates de chaque SAE, **module par module**, avec restriction de groupe éventuelle | `DATES SAE 2026_2027` |
| `10_dates_fixes.json` | Événements fixes horodatés (rentrées, interventions), **avec le parcours concerné** | `Dates MMI 26_27 - DATES OK` |
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
8. **WS501D** : le plan enseignant détaillé d'ALO est ignoré (SAE non planifiée
   par le solveur, et sa tranche « 26-30 octobre » tombe en pause pédagogique).
   Seules les dates du CSV comptent.
9. **WRA505C** : ALO avant AFR en objectif mou.
10. **WRA308M** : bloc de 4h30 sur les **3 derniers TD uniquement**.
11. **WR100BU** : fenêtres de dates **dures** par séance.

## Points restés ouverts

- **WSA501D** (S5 BUT3-DEV-FC, 34 TD) : dates « ??? » dans le fichier source →
  aucune sanctuarisation possible. Signalé dans `08`.
- **Dates de début de stages BUT2 et BUT3** : « à définir pour mi-avril ».
  Listées dans `10_dates_fixes.json > a_fixer`.
- **Salles** : aucun fichier source officiel. `01_regles_generales.json` et
  `data/config/rooms.yaml` viennent de la conversation préparatoire.
- **BUT2-DEV-FC gelé** cette année (effectif alternants insuffisant, cf.
  `Maquette 2026 BUT2 S3-DEV-FC.docx`) : aucun module dans la maquette, le
  solveur l'ignore naturellement. `Dates MMI` lui donne pourtant une rentrée le
  14 septembre 2026 — sans effet, mais à retirer de la source si le gel se
  confirme.
