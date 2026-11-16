"""Génération d'un emploi du temps complet, en tâche de fond.

Lot 2 du chantier « générer un semestre depuis l'interface » (16/11/2026).
La recette (préparer les séances, vérifier, relancer le solveur avec
plusieurs graines, garder le meilleur résultat, compléter, attribuer les
salles) vivait dans `scripts/solve_until_ok.py` et `cal-iut annee` — hors de
l'image de production, qui ne copie pas `scripts/`.

- `recherche` : le score d'un résultat et le diagnostic d'un résultat
  incomplet (repris tels quels du script) ;
- `taches` : l'état d'une génération, sur disque dans le volume persistant ;
- `ouvrier` : le processus qui déroule les étapes (`python -m
  cal_iut.generation.ouvrier <dossier>`).
"""
