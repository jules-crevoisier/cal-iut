#!/usr/bin/env bash
# Boucle de service : draine la file Celcat (create/update/delete) et scanne
# les extras une fois par jour, dès que 00h00 UTC est passé.
#
# RÉSISTANT AUX REDÉMARRAGES (corrigé le 06/09/2026) — la toute première
# version calculait "dors jusqu'au PROCHAIN minuit" une seule fois au
# démarrage : un simple redéploiement Dokploy (qui redémarre TOUS les
# services du compose, celcat-nuit inclus, même si LUI n'a pas changé)
# repartait sur un nouveau sommeil de ~24h à chaque fois, remettant le
# compteur à zéro avant d'avoir jamais atteint minuit. Constaté en
# production : démarré le 05/09 à 00h03, redémarré (silencieusement, par
# un merge sans rapport) avant le premier passage prévu, reparti sur le
# minuit du 07/09 — aucun vrai passage en 48h malgré un service qui
# tournait bien.
#
# Le correctif : un MARQUEUR PERSISTANT (`data/state/celcat_nuit_dernier_
# passage.txt`, dans le MÊME volume partagé que backend — survit à un
# redémarrage) retient la dernière date déjà traitée. La boucle vérifie ce
# marqueur toutes les 5 minutes plutôt que de dormir une fois pour toutes :
# un redémarrage ne fait que ré-entrer dans la boucle et relire le
# marqueur, jamais repartir sur un sommeil de 24h.
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
# celcat-nuit` (ou l'équivalent dans le dashboard Dokploy).

set -euo pipefail
cd /app

MARQUEUR=/app/data/state/celcat_nuit_dernier_passage.txt

# Filet de sécurité seulement : l'image bake déjà le paquet au build
# (Dockerfile). Utile si ce script tourne monté par-dessus une image plus
# ancienne pendant une itération manuelle.
pip install --quiet -e . >/dev/null 2>&1 || true

echo "[$(date -Is)] démarrage — marqueur : $(cat "$MARQUEUR" 2>/dev/null || echo '(aucun)')"

while true; do
  aujourdhui=$(date -u +%Y-%m-%d)
  deja_fait=$(cat "$MARQUEUR" 2>/dev/null || echo "")

  if [ "$aujourdhui" != "$deja_fait" ]; then
    echo "[$(date -Is)] job de nuit Celcat — début (jour $aujourdhui, dernier passage : ${deja_fait:-jamais})"
    if python3 scripts/celcat_nuit.py --ecrire --vpn --production --base URCA_2026; then
      echo "[$(date -Is)] job de nuit Celcat — terminé"
    else
      code=$?
      echo "[$(date -Is)] job de nuit Celcat — ÉCHEC (code ${code}), on retentera dans 5 min"
      sleep 300
      continue
    fi
    echo "$aujourdhui" > "$MARQUEUR"
  fi

  sleep 300
done
