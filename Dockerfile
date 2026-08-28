# syntax=docker/dockerfile:1

# ── cal-iut backend (FastAPI + solveur CP-SAT) — image pour Dokploy ──
#
# Contexte de build = RACINE du repo (pas frontend/) : `src/cal_iut/api/
# main.py` et `src/cal_iut/db/session.py` calculent leurs chemins de
# données en remontant depuis LEUR PROPRE emplacement (`Path(__file__).
# resolve().parents[...]`) jusqu'à la racine du projet — l'image doit donc
# reproduire la même arborescence relative (`data/config`, `contraintes`,
# `data/state/cal-iut.db`), pas juste le package Python installé.
#
# `data/state/` (PAS `data/` en entier) est monté en volume — corrigé le
# 28/08/2026 : un premier jet montait `/app/data` en entier, ce qui incluait
# `data/config/` (teacher_contacts.yaml, rooms.yaml...) dans le volume. Une
# fois ce volume créé au premier déploiement, Docker ne recopie plus JAMAIS
# le contenu de l'image par-dessus — donc AUCUNE mise à jour de `data/
# config/` ne pouvait plus jamais atteindre le conteneur, même après un
# rebuild complet (bug réel trouvé via retour utilisateur : la config locale
# avait bien tous les emails profs, le site déployé affichait encore "mail
# inconnu" pour tout le monde). `data/config/` reste donc HORS du volume —
# rafraîchi à CHAQUE déploiement, comme n'importe quel autre fichier de
# l'image — tandis que `data/state/` (la base SQLite, le secret HMAC, le
# journal des mails envoyés) reste le seul contenu à faire persister entre
# redémarrages.
#
# La base SQLite (`data/state/cal-iut.db`) est copiée telle quelle depuis le
# poste de build — c'est la BASE ACTUELLE (le run déjà chargé en local),
# pour que le premier déploiement affiche tout de suite les vraies séances
# plutôt qu'un planning vide (aucun `cal-iut solve`/`load-run` n'est lancé
# au démarrage du conteneur). Comme avant : les modifications faites depuis
# l'interface déployée (glisser-déposer, régénération ciblée...) survivent
# aux redémarrages grâce au volume — mais SEULEMENT celles-là désormais,
# plus la config. Pour pousser un planning plus récent : reconstruire
# l'image avec un `data/state/cal-iut.db` à jour ET supprimer le volume
# existant dans Dokploy (sinon l'ancien contenu du volume reste prioritaire
# — cette limite-là reste vraie, seulement réduite à la vraie donnée
# runtime maintenant).

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
COPY data/state/cal-iut.db data/state/cal-iut.db
COPY contraintes/ contraintes/
COPY contraintes_update/ contraintes_update/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
VOLUME ["/app/data/state"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u; import sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# --host 0.0.0.0 obligatoire : le défaut CLI (127.0.0.1) ne serait
# joignable que depuis L'INTÉRIEUR du conteneur, pas par le frontend/nginx.
CMD ["cal-iut", "serve", "--host", "0.0.0.0", "--port", "8000"]
