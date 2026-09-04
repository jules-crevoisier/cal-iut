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
# Lancement (une fois, en arrière-plan, sur la machine qui sert cal-iut) :
#
#   docker build -t cal-iut-celcat deploy/celcat-sidecar
#   docker run -d --restart unless-stopped --name celcat-nuit \
#     --cap-add NET_ADMIN --device /dev/net/tun \
#     --env-file /chemin/vers/.env \
#     -v /chemin/vers/le/vrai/depot/cal-iut:/travail \
#     cal-iut-celcat /travail/deploy/celcat-sidecar/nuit-quotidienne.sh
#
# IMPORTANT : `-v` doit pointer sur le MÊME `data/state/` que l'application
# déployée (celui qui reçoit vraiment les déplacements faits sur le site) —
# jamais une copie locale à part, sans quoi ce conteneur draine une file
# que personne ne remplit. `--base` et `--production` sont volontairement
# en dur ci-dessous (URCA_2026, écriture réelle) : ce script n'a pas
# vocation à tourner sur autre chose qu'une vraie nuit de production.
#
# Suivre : `docker logs -f celcat-nuit`. Arrêter : `docker stop celcat-nuit`.

set -euo pipefail
cd /travail

echo "[$(date -Is)] installation du paquet cal-iut…"
pip install --quiet -e . >/dev/null 2>&1 || pip install --quiet -e .

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
