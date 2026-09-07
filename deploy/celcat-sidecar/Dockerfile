# Conteneur de SAISIE Celcat — VPN + navigateur, isolé de tout le reste.
#
# Pourquoi un conteneur à part, et non l'image de l'application. La
# passerelle de l'URCA pousse un tunnel COMPLET : monter ce VPN dans le
# conteneur qui sert cal-iut détournerait tout son trafic sortant et
# couperait le site public. Ici, le tunnel ne concerne que ce conteneur.
#
# Il contient exactement deux choses que l'application n'a pas :
#   - openconnect, client libre du protocole AnyConnect (Cisco ne fournit
#     pas de client Linux) ;
#   - un navigateur, puisque Celcat n'expose aucune API.
#
# Deux usages, une seule image :
#   1. Exploration ponctuelle — code monté au lancement (`-v $PWD:/app`),
#      pour itérer sans reconstruire à chaque essai :
#        docker run --rm -it --cap-add NET_ADMIN --device /dev/net/tun \
#          --env-file .env -v "$PWD:/app" -w /app cal-iut-celcat <commande>
#      (le montage écrase ce que COPY a mis en place au build — sans effet
#      de bord, `pip install -e .` se relance de toute façon au besoin)
#   2. Service permanent (drain nocturne, `docker-compose.yml::celcat-nuit`)
#      — l'app est bakée dans l'image au build (comme le Dockerfile
#      principal), le CMD ci-dessous tourne tout seul, `data/state/`
#      partagé avec le service `backend` via le volume nommé `cal-iut-data`.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

RUN apt-get update \
 && apt-get install -y --no-install-recommends openconnect iproute2 dnsutils curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Même logique que le Dockerfile principal (racine du repo) : `-e` pour
# que CONFIG_DIR/DB_PATH (calculés via Path(__file__).resolve().parents[N])
# retombent sur CETTE arborescence, pas sur site-packages.
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e . playwright==1.55.0 python-dotenv httpx pyyaml

COPY scripts/ scripts/
COPY data/config/ data/config/
# `contraintes/` comme dans le Dockerfile principal : sans lui, le
# calendrier retombe sur la copie codée en dur de `calendar/academic.py`
# (avertissement à chaque démarrage, constaté en production le 07/09/2026).
# Les deux calendriers coïncident aujourd'hui — vérifié, 38 lundis
# identiques — donc rien n'était faux ; mais faire dépendre les DATES d'un
# planning d'un repli explicitement documenté comme « potentiellement
# obsolète » ne tient que jusqu'à la prochaine modification du calendrier
# officiel, qui ne serait alors vue que par le backend.
COPY contraintes/ contraintes/
COPY deploy/celcat-sidecar/nuit-quotidienne.sh deploy/celcat-sidecar/nuit-quotidienne.sh

ENV PYTHONUNBUFFERED=1
VOLUME ["/app/data/state"]

# Repris à l'identique par le service exploration (`docker run ... bash`) :
# un CMD par défaut ne gêne pas un `docker run` qui précise sa propre
# commande, il ne sert que quand rien n'est précisé (service permanent).
CMD ["bash", "deploy/celcat-sidecar/nuit-quotidienne.sh"]
