"""Audit systématique du projet : données, configuration, capacité, résultat.

Pourquoi ce module existe (25/08/2026, demande utilisateur : « cela fait
beaucoup de bugs que tu trouves, il faudrait auditer tout cela pour essayer de
trouver tous les bugs possibles »). Les défauts trouvés jusqu'ici se rangent
dans quatre familles, et AUCUNE n'était détectable autrement qu'en lisant le
code ligne à ligne :

1. **Une règle déclarée qui ne s'applique pas.** Les fenêtres de dates
   (WR100BU), le regroupement mensuel (ARA/JHU) et l'ordre entre enseignants
   (WRA505C) étaient documentés « actifs » dans le README et posés uniquement
   dans le modèle joint — jamais dans `--decomposed`, le seul mode réellement
   utilisé. Idem pour le plafond de 22 créneaux, annulé partout sauf sur le
   chemin d'appel qui compte.
2. **Une règle qui pointe dans le vide.** Un code de cours mal orthographié
   dans un YAML ne lève rien : la règle est silencieusement ignorée.
3. **Une donnée source mal comprise.** « mercredi 23/09/26 » lu comme « tous
   les mercredis », un trigramme perdu parce qu'il est collé au nom précédent.
4. **Une impossibilité arithmétique.** Un enseignant à qui l'on assigne plus de
   créneaux qu'il n'en a réellement — prouvé infaisable en 0,1 s, mais après
   des heures de calcul.

Le principe directeur : **une règle sans vérification est un bug en attente**.
L'audit liste donc aussi les règles qu'il ne sait PAS vérifier, plutôt que de
laisser croire à une couverture complète.

    cal-iut audit                       # données + config + capacité
    cal-iut audit --timetable <run>     # + vérification du résultat
    cal-iut audit --json                # sortie machine
"""

from cal_iut.audit.report import AuditReport, Finding, Severity
from cal_iut.audit.runner import run_audit

__all__ = ["AuditReport", "Finding", "Severity", "run_audit"]
