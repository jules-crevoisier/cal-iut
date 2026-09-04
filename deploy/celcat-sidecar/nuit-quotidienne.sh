#!/usr/bin/env bash
# Boucle de service : draine la file Celcat (create/update/delete) et scanne
# les extras une fois par nuit, à 00h00 heure du conteneur.
#
# Pourquoi une boucle bash plutôt qu'un vrai cron : pas de démon
# supplémentaire à superviser (pas de syslog à router), les logs vont
# directement sur stdout (donc `docker logs`), et le calcul du prochain
# 00h00 est trivial. Le conteneur reste volontairement à part de
# l'application (cf. Dockerfile) : c'est CE conteneur, et lui seul, qui
# monte le VPN URCA.
#
# Déployé comme service `celcat-nuit` dans `docker-compose.yml`, à côté de
# `backend`/`frontend` — Dokploy le construit et le démarre automatiquement
# à chaque déploiement, comme les deux autres. Partage `data/state/` avec
# `backend` via le même volume nommé `cal-iut-data` : ce script voit donc
# les VRAIS jobs mis en file par l'appli déployée, jamais une copie locale.
#
# `--base`/`--production` volontairement en dur ci-dessous (URCA_2026,
# écriture réelle) : ce script n'a pas vocation à tourner sur autre chose
# qu'une vraie nuit de production. Suivre : `docker compose logs -f
# celcat-nuit` (ou `docker logs -f <container>` en Dokploy).

set -euo pipefail
cd /app

# Filet de sécurité seulement : l'image bake déjà le paquet au build
# (Dockerfile). Utile si ce script tourne monté par-dessus une image plus
# ancienne pendant une itération manuelle.
pip install --quiet -e . >/dev/null 2>&1 || true

while true; do
  maintenant=$(date +%s)
  minuit_prochain=$(date -d 'tomorrow 00:00:00' +%s)
  attente=$((minuit_prochain - maintenant))
  echo "[$(date -Is)] prochain passage dans ${attente}s (à $(date -d "@${minuit_prochain}" -Is))"
  sleep "${attente}"

  echo "[$(date -Is)] job de nuit Celcat — début"
  if python3 scripts/celcat_nuit.py --ecrire --vpn --production --base URCA_2026; then
    echo "[$(date -Is)] job de nuit Celcat — terminé"
  else
    code=$?
    echo "[$(date -Is)] job de nuit Celcat — ÉCHEC (code ${code}), on retentera demain"
  fi
done
