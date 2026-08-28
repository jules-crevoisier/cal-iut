"""Saisie automatisée des séances dans CELCAT (outil URCA, sans API).

Trois couches volontairement séparées, pour que l'essentiel soit testable
sans navigateur ni identifiants :

- `mapping.py`  : nos placements -> entrées Celcat (pure traduction) ;
- `sync.py`     : ce qui a déjà été saisi, donc ce qu'il reste à faire ;
- `driver.py`   : le seul module qui pilote réellement un navigateur.

Seul `driver.py` a besoin de Celcat ; tout le reste se vérifie hors ligne.
"""
