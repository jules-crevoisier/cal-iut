# Flux `.ics` — intégration pour une appli tierce

Doc à donner telle quelle à qui développe une appli qui consomme l'emploi du
temps MMI. Base : `https://cal-iut-mmi.srko.fr`.

## 1. Les liens abonnables

```
GET /ics/prof/{code}.ics?t=<n'importe quoi>
GET /ics/groupe/{group_id}.ics?t=<n'importe quoi>
```

- `{code}` = trigramme enseignant (ex. `JSA`), `{group_id}` = identifiant de
  groupe (ex. `but3-dev-fc-td-ef`).
- `?t=` est obligatoire (n'importe quelle valeur non vide suffit — c'est un
  lien personnel, pas un vrai secret cryptographique). Sans lui : `401`.
- Un lien **groupe** renvoie la cohorte complète : le groupe lui-même + son
  CM de promo + son TP jumelé (ou son TD parent si c'est un lien TP) — les
  mêmes séances qu'un étudiant de ce groupe verrait sur son planning perso.
- Réponse : `text/calendar; charset=utf-8`, standard iCalendar (RFC 5545).
  `Cache-Control: no-store` — le contenu est recalculé en direct à chaque
  requête, jamais mis en cache côté serveur.

## 2. Fuseau horaire

Toutes les dates sont en `TZID=Europe/Paris` avec un vrai bloc `VTIMEZONE`
(bascule heure d'été/hiver gérée automatiquement). Pas d'heure flottante,
pas d'UTC à décaler à la main — un parseur ICS standard gère ça tout seul.

## 3. Détecter les modifications sans tout retélécharger

Ne PAS repoller `/ics/prof/*` ou `/ics/groupe/*` en boucle serrée — chaque
appel recalcule le calendrier complet. Il existe un endpoint dédié, léger,
pensé pour être sondé très souvent :

```
GET /ics/version?t=<n'importe quoi>
```

Réponse :

```json
{
  "groupes": [
    {
      "id": "but3-dev-fc-td-ef",
      "label": "TD EF",
      "derniere_modification": "2026-09-03T12:03:59.123456",
      "lien": "/ics/groupe/but3-dev-fc-td-ef.ics"
    }
  ],
  "enseignants": [
    {
      "code": "JSA",
      "label": "JULES SABATER",
      "derniere_modification": "2026-09-03T12:03:59.123456",
      "lien": "/ics/prof/JSA.ics"
    }
  ]
}
```

- `derniere_modification` : `null` si rien n'a encore de trace de
  modification connue (planning jamais retouché depuis sa génération), sinon
  un horodatage ISO 8601 (UTC, sans suffixe `Z` explicite mais c'est de
  l'UTC).
- `lien` : chemin relatif prêt à requêter (à concaténer avec le domaine),
  il ne reste plus qu'à ajouter `?t=...`.

**Intégration recommandée** : garder en mémoire (ou en base) la dernière
`derniere_modification` vue pour chaque groupe/enseignant suivi. À chaque
sondage de `/ics/version`, comparer : si la date a avancé (ou si elle passe
de `null` à une vraie date), aller rechercher le `.ics` complet correspondant
via `lien`. Sinon, ne rien faire. `/ics/version` peut être sondé aussi
souvent que voulu (quelques secondes si besoin) — c'est un simple
dictionnaire d'horodatages, pas un recalcul de calendrier.

## 4. Ce qu'on ne peut pas garantir

- `/ics/version` dit QUAND ça a bougé, jamais CE QUI a changé précisément
  dans la séance — il faut retélécharger le `.ics` du groupe/enseignant
  concerné pour voir le détail.
- Pas de push/webhook pour l'instant : c'est encore du polling, juste rendu
  bon marché. Si un vrai besoin de push apparaît plus tard, à revoir.
