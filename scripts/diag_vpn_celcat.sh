#!/usr/bin/env bash
# Diagnostic du tunnel dans le conteneur de saisie : monte le VPN, puis
# vérifie ce dont Celcat a besoin — résolution DNS, route, réponse HTTP.
#
# Les sorties vont dans un fichier : une fois le tunnel monté, le flux
# stdout du conteneur se coupe (constaté le 01/09/2026), et un diagnostic
# qu'on ne peut pas lire ne sert à rien.
#
#   docker run --rm --cap-add NET_ADMIN --device /dev/net/tun \
#     --env-file .env -v "$PWD:/travail" cal-iut-celcat \
#     bash /travail/scripts/diag_vpn_celcat.sh
set -u

SORTIE=/travail/data/releves/diag-vpn.txt
mkdir -p "$(dirname "$SORTIE")"
exec >"$SORTIE" 2>&1

echo "=== montage"
echo "$CELCAT_MOT_DE_PASSE" | openconnect \
  --protocol=anyconnect \
  --user="$CELCAT_UTILISATEUR" \
  --passwd-on-stdin \
  --background \
  --non-inter \
  vpn.univ-reims.fr >/tmp/oc.log 2>&1
echo "code de sortie : $?"
sleep 8

echo "=== resolv.conf"
cat /etc/resolv.conf
echo "=== tun0"
ip -4 addr show tun0 || echo "pas de tun0"
echo "=== routes"
ip route | head -5
echo "=== resolution"
getent hosts celcat-lv.univ-reims.fr || echo "celcat-lv ne resout pas"
echo "=== resolution par le dns du vpn"
awk '/^nameserver/ {print $2}' /etc/resolv.conf | while read -r ns; do
  echo "-- via $ns"
  nslookup celcat-lv.univ-reims.fr "$ns" 2>&1 | tail -4
done
echo "=== http"
curl -s -o /dev/null -w "code=%{http_code}\n" --max-time 25 https://celcat-lv.univ-reims.fr/ \
  || echo "curl en echec"
echo "=== journal openconnect"
tail -12 /tmp/oc.log
