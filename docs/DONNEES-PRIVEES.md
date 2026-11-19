# Données privées des enseignants

Le dépôt est public. Les fichiers de contraintes des enseignants (e-mails,
indisponibilités, texte libre, commentaires, noms) ne doivent pas y rester.

## Où ils vivent
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

## Comment ça marche
`scripts/docker-entrypoint.sh` (backend et `celcat-nuit`) s'exécute au
démarrage :
1. **Copie initiale** : tout fichier de la liste absent du volume est copié
   depuis l'image, à condition que ce soit la vraie version (pas l'anonymisée).
   Un fichier déjà dans le volume n'est jamais écrasé.
2. **Application** : le contenu du volume est recopié par-dessus `/app/`.
3. Quand les 12 fichiers sont dans le volume, un repère `.copie_ok` est posé et
   `/health` répond `"donnees_privees": true`.

## Modifier ces fichiers
Éditer la copie du volume puis redémarrer, jamais le dépôt. À terme, ces
contraintes seront saisies dans l'interface (chantier « tous les paramètres de
génération dans l'interface »).
