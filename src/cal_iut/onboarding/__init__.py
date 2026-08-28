"""Prise en main par quelqu'un qui n'a pas écrit ce projet.

Objectif (demande utilisateur du 26/08/2026) : que l'an prochain, une autre
personne puisse produire les emplois du temps sans rien connaître du code ni du
solveur. Trois commandes, dans cet ordre, et rien d'autre à savoir :

    cal-iut doctor     -> est-ce que tout est en place ? que faire ensuite ?
    cal-iut refresh    -> récupérer maquette + progression officielles, voir ce qui a changé
    cal-iut annee      -> dérouler toute la chaîne jusqu'à l'emploi du temps
    cal-iut regles     -> lister en français toutes les règles actives

Principes tenus dans ce module :

- **Aucune trace d'erreur Python.** Un fichier manquant, un réseau coupé, un
  JSON mal formé : chacun donne une phrase en français et l'action à faire.
- **Jamais d'écrasement silencieux.** `refresh` montre ce qui change AVANT
  d'écrire, et garde une copie horodatée de l'ancien fichier.
- **Toujours dire l'étape suivante.** Une commande qui réussit se termine par
  « maintenant, lancez … ». C'est ce qui distingue un outil utilisable d'un
  outil qui suppose qu'on connaît déjà le pipeline.
"""

from cal_iut.onboarding.doctor import run_doctor
from cal_iut.onboarding.refresh import refresh_sources
from cal_iut.onboarding.regles import inventorier

__all__ = ["inventorier", "refresh_sources", "run_doctor"]
