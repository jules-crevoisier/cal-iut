#!/usr/bin/env bash
# Boucle de service : deux rythmes distincts.
#   1) TEMPS RÉEL (~30s) : draine la file create/update/delete dès qu'elle
#      n'est pas vide (retour utilisateur 07/09/2026 : « sur les update on
#      veut tenter en temps réel, pas la nuit »). Vérification locale (JSON,
#      sans VPN) à chaque tour ; connexion Live seulement s'il y a vraiment
#      quelque chose à pousser.
#   2) UNE FOIS PAR JOUR (00h00 UTC passé) : balaie les semaines validées
#      (enfile ce qui manque) et scanne les extras Live — c'est le vrai job
#      de nuit, `scripts/celcat_nuit.py`, qui draine aussi la file au passage
#      (filet de sécurité si le rythme temps réel a raté un job).
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
# redémarrage) retient la dernière date déjà traitée pour le rythme (2).
# Le rythme (1), lui, n'a pas besoin de marqueur : la file elle-même EST
# l'état à traiter, un redémarrage la retrouve intacte dans le volume
# partagé.
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
RYTHME_TEMPS_REEL=30

# Filet de sécurité seulement : l'image bake déjà le paquet au build
# (Dockerfile). Utile si ce script tourne monté par-dessus une image plus
# ancienne pendant une itération manuelle.
pip install --quiet -e . >/dev/null 2>&1 || true

echo "[$(date -Is)] démarrage — marqueur : $(cat "$MARQUEUR" 2>/dev/null || echo '(aucun)')"

while true; do
  # --- (1) temps réel : la file d'attente (create/update/delete), à
  # chaque tour. `celcat_immediat.py` se termine tout de suite sans VPN si
  # la file est vide — coût quasi nul dans le cas courant. -----------------
  if python3 scripts/celcat_immediat.py --ecrire --vpn --production --base URCA_2026; then
    :
  else
    echo "[$(date -Is)] drainage temps réel — ÉCHEC (code $?), on retentera au tour suivant"
  fi

  # --- (2) une fois par jour : semaines validées + extras. -----------------
  aujourdhui=$(date -u +%Y-%m-%d)
  deja_fait=$(cat "$MARQUEUR" 2>/dev/null || echo "")

  if [ "$aujourdhui" != "$deja_fait" ]; then
    echo "[$(date -Is)] job de nuit Celcat — début (jour $aujourdhui, dernier passage : ${deja_fait:-jamais})"
    if python3 scripts/celcat_nuit.py --ecrire --vpn --production --base URCA_2026; then
      echo "[$(date -Is)] job de nuit Celcat — terminé"
      echo "$aujourdhui" > "$MARQUEUR"
    else
      code=$?
      echo "[$(date -Is)] job de nuit Celcat — ÉCHEC (code ${code}), on retentera au prochain tour"
    fi
  fi

  sleep "$RYTHME_TEMPS_REEL"
done
