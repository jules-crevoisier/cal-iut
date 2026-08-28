# syntax=docker/dockerfile:1

# ── cal-iut frontend — build multi-étages, optimisé pour Dokploy ──
#
# Étage 1 : compile le SPA (tsc -b && vite build) dans un environnement
# Node complet. Étage 2 : sert UNIQUEMENT le résultat statique (`dist/`)
# via nginx — l'image finale ne contient ni Node ni node_modules ni le
# code source, juste les fichiers buildés + nginx (~40-50 Mo au lieu de
# plusieurs centaines).
#
# L'API cal-iut (FastAPI) tourne dans un AUTRE conteneur — ce Dockerfile ne
# contient QUE le frontend, volontairement. Le SPA appelle des chemins
# relatifs (`api/client.ts` : `const BASE = ""`, ex. `/meta`, `/timetable`,
# `/solve`…) : nginx reverse-proxy tout ce qui n'est pas un fichier statique
# vers `$BACKEND_URL` (cf. nginx.conf.template) — variable d'env à définir
# dans Dokploy, pointant vers le service backend (ex.
# `http://cal-iut-api:8000` sur le réseau interne du projet).
#
# Le routage interne de l'app se fait par FRAGMENT d'URL (`#vue=...`),
# jamais envoyé au serveur (cf. hooks/useHashRoute.ts) — pas de repli SPA
# `try_files ... /index.html` nécessaire pour des routes profondes, juste
# pour servir `/` lui-même.

# ─── Étage 1 : build ───
FROM node:22-alpine AS build
WORKDIR /app

# Couche dépendances séparée du code source : `npm ci` ne se refait que si
# package.json/package-lock.json changent, pas à chaque modif de src/.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ─── Étage 2 : runtime (nginx, statique uniquement) ───
FROM nginx:1.27-alpine AS runtime

# Gabarit substitué au démarrage par l'entrypoint officiel nginx
# (`docker-entrypoint.d/20-envsubst-on-templates.sh`, déjà présent dans
# cette image) — seules les vraies variables d'environnement du conteneur
# sont substituées, les variables nginx (`$uri`, `$host`…) restent
# intactes puisqu'elles n'existent pas dans l'environnement du process.
ENV BACKEND_URL=http://backend:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O- http://127.0.0.1/healthz || exit 1
