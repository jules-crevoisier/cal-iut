#!/bin/sh
# Fichiers PRIVÉS des enseignants (voir docs/DONNEES-PRIVEES.md).
#
# 1) COPIE INITIALE : pour chaque fichier de la liste, s'il n'est pas encore
#    dans le volume (data/state/prive/) et que la version de l'image est la
#    vraie (pas la version anonymisée du dépôt), on la copie dans le volume.
#    Jamais d'écrasement d'un fichier déjà présent dans le volume.
# 2) APPLICATION : tout ce que contient le volume est recopié par-dessus /app/.
# 3) Quand les 12 fichiers sont dans le volume, un repère .copie_ok est posé ;
#    /health l'indique (donnees_privees: true).
set -e
PRIVE="${CAL_IUT_PRIVE_DIR:-/app/data/state/prive}"
FICHIERS="data/config/teacher_contacts.yaml
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
contraintes_update/progression.json"

mkdir -p "$PRIVE"
manquants=0
OLDIFS="$IFS"; IFS='
'
for f in $FICHIERS; do
  if [ ! -f "$PRIVE/$f" ]; then
    src="/app/$f"
    if [ -f "$src" ] && ! grep -q "example.invalid" "$src" && ! grep -q "Prenom " "$src" && ! grep -q "\"PRENOM\"" "$src"; then
      mkdir -p "$(dirname "$PRIVE/$f")"
      cp "$src" "$PRIVE/$f"
      echo "[entrypoint] copié dans le volume : $f"
    else
      manquants=$((manquants + 1))
    fi
  fi
done
IFS="$OLDIFS"

if [ "$manquants" -eq 0 ]; then
  touch "$PRIVE/.copie_ok"
else
  echo "[entrypoint] ATTENTION : $manquants fichier(s) privé(s) absents du volume $PRIVE — l'appli utilise les données anonymisées pour ceux-là."
fi

cp -R "$PRIVE"/. /app/ 2>/dev/null || true
exec "$@"
