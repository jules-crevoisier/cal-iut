"""Saisie automatisée des séances dans CELCAT.

Couches testables sans navigateur :

- `mapping.py`  : nos placements -> entrées Celcat ;
- `lecture.py`  : `udlTimetables.load` -> événements Live ;
- `diff.py`     : cal-iut ↔ Celcat, manquants seulement (jamais supprimer) ;
- `rpc.py`      : JSON-RPC **dans** la page (la session est la connexion) ;
- `ecriture.py` : garde-fous (1 semaine, FORMATION d'abord) ;
- `sync.py`     : journal local — ce n'est PAS l'état réel de Celcat ;
- `driver.py`   : clicker Playwright, repli seulement (`--clicker`).
"""
