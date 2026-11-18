#!/bin/sh
# Recopie les fichiers PRIVÉS (volume data/state/prive/) par-dessus les versions
# anonymisées embarquées dans l'image, avant de démarrer l'appli.
# Voir docs/DONNEES-PRIVEES.md.
set -e
PRIVE="${CAL_IUT_PRIVE_DIR:-/app/data/state/prive}"
if [ -d "$PRIVE" ] && [ -n "$(ls -A "$PRIVE" 2>/dev/null)" ]; then
  cp -R "$PRIVE"/. /app/
  echo "[entrypoint] fichiers privés appliqués depuis $PRIVE"
else
  echo "[entrypoint] ATTENTION : $PRIVE absent ou vide — l'appli démarre avec les données anonymisées du dépôt (e-mails et contraintes réels absents)."
fi
exec "$@"
