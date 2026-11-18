# Données privées des enseignants (18/11/2026)

Le dépôt est public. Les vraies données personnelles des enseignants n'y sont
plus : e-mails, texte libre des contraintes, commentaires, noms.

## Ce qui est dans le dépôt
Des versions **anonymisées** de même structure (noms → « Prenom CODE »,
e-mails → `code@example.invalid`, commentaires et texte libre supprimés). Elles
servent aux tests et à la CI. Les trigrammes et les créneaux y sont conservés.

## Où sont les vrais fichiers
Dans le volume de production, sous `/app/data/state/prive/`, avec la même
arborescence relative que le dépôt :

```
data/config/teacher_contacts.yaml
data/config/teacher_availability.yaml
data/config/teacher_duos.yaml
data/config/sae_teacher_phases.yaml
data/config/enseignants_supplementaires.yaml
contraintes/05_enseignants_contraintes.json
contraintes/07_modules_maquette_progression.json
contraintes/maquette.json
contraintes/progression.json
contraintes_update/CONTRAINTES ENSEIGNANTS MMI 2026_2027 - Feuille 1(1).csv
contraintes_update/maquette.json
contraintes_update/progression.json
```

Au démarrage, `scripts/docker-entrypoint.sh` recopie ce dossier par-dessus
`/app/` (backend et `celcat-nuit`). Si le dossier est vide ou absent, l'appli
démarre avec les données anonymisées et le journal l'indique.

## Modifier ces fichiers
Éditer la copie du volume, puis redémarrer le conteneur. Ne jamais commiter la
vraie version : `data/state/prive/` est dans le `.gitignore`.

## Régénérer les versions anonymisées
`python scripts/anonymiser_donnees_privees.py <dossier_prive>` (le dossier
reprend les chemins relatifs ci-dessus), puis commiter le résultat.
