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
# Lancement (les deux options sont NÉCESSAIRES à openconnect) :
#   docker run --rm -it --cap-add NET_ADMIN --device /dev/net/tun \
#     --env-file .env cal-iut-celcat <commande>
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

RUN apt-get update \
 && apt-get install -y --no-install-recommends openconnect iproute2 dnsutils curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /travail
# Les navigateurs sont deja dans /ms-playwright : seul le paquet Python
# manque, et sa version doit correspondre a celle de l'image.
RUN pip install --no-cache-dir playwright==1.55.0 python-dotenv httpx pyyaml

# Le code est monté au lancement plutôt que copié : cette image sert à
# EXPLORER Celcat, et on ne veut pas la reconstruire à chaque essai.
CMD ["bash"]
