# syntax=docker/dockerfile:1

# ── cal-iut backend (FastAPI + solveur CP-SAT) — image pour Dokploy ──
#
# Contexte de build = RACINE du repo (pas frontend/) : `src/cal_iut/api/
# main.py` et `src/cal_iut/db/session.py` calculent leurs chemins de
# données en remontant depuis LEUR PROPRE emplacement (`Path(__file__).
# resolve().parents[...]`) jusqu'à la racine du projet — l'image doit donc
# reproduire la même arborescence relative (`data/config`, `contraintes`,
# `data/cal-iut.db`), pas juste le package Python installé.
#
# La base SQLite (`data/cal-iut.db`) est copiée telle quelle depuis le poste
# de build — c'est la BASE ACTUELLE (le run déjà chargé en local), pour que
# le premier déploiement affiche tout de suite les vraies séances plutôt
# qu'un planning vide (aucun `cal-iut solve`/`load-run` n'est lancé au
# démarrage du conteneur). `VOLUME /app/data` ci-dessous fait que Docker/
# Dokploy ne recopie ce contenu dans le volume qu'UNE fois, à la création —
# les modifications faites depuis l'interface déployée (glisser-déposer,
# régénération ciblée...) survivent ensuite aux redémarrages. Pour pousser
# un planning plus récent : reconstruire l'image avec un `data/cal-iut.db`
# à jour ET supprimer le volume existant dans Dokploy (sinon l'ancien
# contenu du volume reste prioritaire).

FROM python:3.11-slim
WORKDIR /app

# libgomp1 : OR-Tools (CP-SAT) en a besoin au runtime, pas forcément déjà
# présent sur l'image slim de base.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Dépendances installées avant de copier les données — un changement dans
# contraintes/*.json ne force pas un `pip install` complet au rebuild.
#
# `-e` (éditable) et NON une install normale : `pip install .` copierait le
# package dans site-packages, ce qui casse `CONFIG_DIR`/`DB_PATH`
# (calculés dans le code via `Path(__file__).resolve().parents[N]`,
# relatif à l'emplacement RÉEL du fichier source — trouvé en testant
# l'image le 28/08/2026 : `FileNotFoundError` sur
# `/usr/local/lib/python3.11/data/config/groups.yaml` avec une install
# normale). En éditable, le code reste servi depuis `/app/src/cal_iut/...`,
# donc `parents[3]` retombe bien sur `/app` où `data/`/`contraintes/`
# sont copiés juste après.
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e .

COPY data/config/ data/config/
COPY data/cal-iut.db data/cal-iut.db
COPY contraintes/ contraintes/
COPY contraintes_update/ contraintes_update/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u; import sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# --host 0.0.0.0 obligatoire : le défaut CLI (127.0.0.1) ne serait
# joignable que depuis L'INTÉRIEUR du conteneur, pas par le frontend/nginx.
CMD ["cal-iut", "serve", "--host", "0.0.0.0", "--port", "8000"]
