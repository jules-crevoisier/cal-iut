# S'abonner à son emploi du temps dans un agenda

Ce document explique comment voir son emploi du temps MMI dans Google Agenda, Outlook ou l'agenda Apple.
Il est pour tout le monde : enseignants, étudiants, secrétariat. La fin est pour les techniciens.

**Sommaire**

1. [Ce que fait l'abonnement](#1-ce-que-fait-labonnement)
2. [Trouver son lien agenda](#2-trouver-son-lien-agenda)
3. [Google Agenda](#3-google-agenda)
4. [Outlook](#4-outlook)
5. [iPhone, iPad, Mac](#5-iphone-ipad-mac)
6. [Questions fréquentes](#6-questions-fréquentes)
7. [Pour les techniciens](#7-pour-les-techniciens)

---

## 1. Ce que fait l'abonnement

- Les séances apparaissent dans votre agenda habituel, avec la salle et les enseignants.
- L'agenda **se met à jour tout seul** quand le planning change. Rien à retélécharger.
- Un agenda de groupe montre aussi les **semaines de projet SAE** (bandeaux sur la journée entière).
- L'abonnement est en lecture seule : on ne peut pas modifier le planning depuis son agenda.

---

## 2. Trouver son lien agenda

Chaque enseignant et chaque groupe (TD, TP) a son propre lien agenda.

**Vous avez reçu un lien personnel** (par mail, de la part du département) :

1. Ouvrir le lien. Votre planning s'affiche.
2. Cliquer sur **Ajouter à mon agenda**. Un menu s'ouvre avec trois choix :
   - **Copier le lien d'abonnement** : à coller dans n'importe quelle application d'agenda ;
   - **iPhone, Mac, Outlook** : ouvre directement la fenêtre d'abonnement ;
   - **Google Agenda** : ouvre Google Agenda avec le lien déjà rempli.

**Vous avez un compte dans l'appli** (secrétariat, responsables) :

1. Ouvrir **Vue Enseignant** ou **Vue TD / TP**, puis choisir la personne ou le groupe.
2. Cliquer sur **Lien agenda**. Le lien est copié.

Autre chemin : **Référence** → onglet **Liens & partage** → colonne **Lien agenda**, pour tous les enseignants et groupes.

Le lien ressemble à ceci :

```
https://cal-iut-mmi.srko.fr/ics/prof/KBR.ics?t=KBR
https://cal-iut-mmi.srko.fr/ics/groupe/but1-tp-a.ics?t=but1-tp-a
```

> **À savoir :** ce lien n'est pas secret au sens fort. Ne pas le publier sur un site ou un réseau social.

---

## 3. Google Agenda

Le plus simple : dans le menu **Ajouter à mon agenda**, choisir **Google Agenda**, puis confirmer.

À la main, sur ordinateur (l'application mobile ne permet pas d'ajouter un agenda par lien) :

1. Copier le lien agenda (cf. [§ 2](#2-trouver-son-lien-agenda)).
2. Ouvrir [Google Agenda](https://calendar.google.com) dans un navigateur.
3. À gauche, à côté de **Autres agendas**, cliquer sur **+**, puis **À partir de l'URL**.
4. Coller le lien, puis cliquer sur **Ajouter l'agenda**.

L'agenda « Planning MMI — … » apparaît dans la liste. Il s'affiche aussi sur le téléphone lié au même compte Google.

---

## 4. Outlook

Le plus simple : dans le menu **Ajouter à mon agenda**, choisir **iPhone, Mac, Outlook**.

À la main, dans Outlook sur le web (ou le nouvel Outlook) :

1. Copier le lien agenda.
2. Ouvrir le **Calendrier**, puis **Ajouter un calendrier**.
3. Choisir **S'abonner à partir du web**.
4. Coller le lien, donner un nom, puis cliquer sur **Importer**.

Dans Outlook classique pour Windows : **Accueil** → **Ajouter un calendrier** → **À partir d'Internet**, puis coller le lien.

---

## 5. iPhone, iPad, Mac

Le plus simple : ouvrir son lien personnel **sur l'appareil**, puis **Ajouter à mon agenda** → **iPhone, Mac, Outlook**.
L'appareil propose de s'abonner : accepter.

À la main sur iPhone ou iPad :

1. Copier le lien agenda.
2. Ouvrir **Réglages** → **Calendrier** → **Comptes** → **Ajouter un compte** → **Autre**.
3. Choisir **Ajouter un calendrier avec abonnement**, coller le lien, puis **Suivant** et **Enregistrer**.

À la main sur Mac : application **Calendrier** → menu **Fichier** → **Nouvel abonnement à un calendrier**,
coller le lien, puis **S'abonner**.

> **À savoir :** les noms des menus de Google, Microsoft et Apple peuvent varier selon la version.

---

## 6. Questions fréquentes

**Au bout de combien de temps un changement apparaît-il ?**
Le serveur est toujours à jour. C'est votre agenda qui décide quand il relit le lien.
Le fichier demande une relecture toutes les heures, mais chaque agenda fait à sa façon.
Google Agenda relit en général toutes les 12 à 24 h, et on ne peut pas l'accélérer.
Pour une information urgente, votre lien personnel (la page web) est toujours exact.

**Une séance déplacée apparaît-elle en double ?**
Non. Chaque séance garde le même identifiant : l'agenda la déplace au lieu d'en créer une autre.

**Les heures sont décalées d'une ou deux heures.**
Le fichier indique le fuseau Europe/Paris, avec le changement d'heure. Vérifier le fuseau réglé dans votre agenda.

**Je ne vois pas les semaines SAE.**
Elles ne sont que dans les agendas de **groupe**. L'agenda d'un enseignant montre ses séances.

**Comment arrêter ?**
Supprimer l'agenda « Planning MMI — … » dans votre application d'agenda (« Se désabonner » ou « Supprimer »).

---

## 7. Pour les techniciens

Cette partie est pour qui développe une application qui lit les flux `.ics`.
Pour lire des données structurées (JSON), l'API v1 est plus adaptée : [API.md](API.md).

### Les adresses

| Adresse | Contenu |
|---|---|
| `GET /ics/prof/{code}.ics?t=…` | Séances d'un enseignant (`{code}` = trigramme, ex. `JSA`) |
| `GET /ics/groupe/{id}.ics?t=…` | Séances d'un groupe et de sa cohorte (ex. `but3-dev-fc-td-ef`) |
| `GET /ics/version?t=…` | Date de dernière modification de chaque flux (JSON) |

- `?t=` est obligatoire : sa **présence** suffit (valeur non vide). Sans lui ni compte : `401`.
  L'appli met le code lui-même (`?t=KBR`). Une clé API ou une session de compte marche aussi.
- Un flux de **groupe** contient la cohorte complète : le groupe, le CM de sa promo, et son TD parent ou ses TP.
  Ce sont les mêmes séances que sur le lien personnel du groupe. Groupe inconnu : `404`.
- Un flux d'**enseignant** au code inconnu renvoie un calendrier vide.

### Le format

- `text/calendar; charset=utf-8`, iCalendar standard (RFC 5545). Nom : `Planning MMI — <nom>`.
- Heures en `TZID=Europe/Paris`, avec un vrai bloc `VTIMEZONE` (heure d'été et d'hiver).
  Pas d'heure « flottante », pas d'UTC à décaler.
- `UID` stable par séance (`prof-KBR-<id de séance>@cal-iut`) : un déplacement met à jour l'évènement.
- `SEQUENCE` et `LAST-MODIFIED` augmentent quand la séance change.
- `REFRESH-INTERVAL` et `X-PUBLISHED-TTL` suggèrent une relecture toutes les heures (sans garantie côté client).
- Contenu d'une séance : `SUMMARY` = code du cours et groupes ; `LOCATION` = salle ;
  `DESCRIPTION` = intitulé, groupes, enseignants.
- Flux de groupe seulement : un évènement **journée entière** par semaine de projet SAE
  (`DTSTART;VALUE=DATE`, fin exclusive, `TRANSP:TRANSPARENT`, plus `X-MICROSOFT-CDO-ALLDAYEVENT:TRUE` pour Outlook).
  Même découpage que `GET /api/v1/sae/periodes`.

### Relire sans gaspiller

Chaque réponse porte un `ETag` et `Cache-Control: no-cache`. Un client qui renvoie `If-None-Match` reçoit
`304` sans contenu tant que rien n'a changé. Côté serveur, le calendrier n'est recalculé qu'après un changement.

Pour savoir **quel** flux relire, sonder `GET /ics/version?t=…` :

```json
{"groupes": [{"id": "but3-dev-fc-td-ef", "label": "TD EF",
              "derniere_modification": "2026-09-03T12:03:59.123456", "lien": "/ics/groupe/but3-dev-fc-td-ef.ics"}],
 "enseignants": [{"code": "JSA", "label": "JULES SABATER",
                  "derniere_modification": "2026-09-03T12:03:59.123456", "lien": "/ics/prof/JSA.ics"}]}
```

- `derniere_modification` : horodatage en UTC (sans `Z`), ou `null` si aucune séance n'a été retouchée depuis la génération.
- `lien` : chemin à compléter avec le domaine et `?t=…`.

Méthode conseillée :

1. Garder la dernière `derniere_modification` vue pour chaque flux suivi.
2. Sonder `/ics/version` (avec `If-None-Match`), au plus toutes les 30 s.
3. Relire un `.ics` seulement si sa date a avancé (ou est passée de `null` à une date).

### Limites

- `/ics/version` dit **quand** un flux a bougé, pas **ce qui** a changé : relire le `.ics` pour le détail.
- Pas de notification poussée (webhook) : c'est du sondage, rendu peu coûteux.
- Sans compte, le trafic est compté par adresse IP. Si la protection anti-aspiration est en mode `enforce` :
  120 requêtes par minute pour les `.ics`, 60 par minute pour `/ics/version`. Au-delà : `429` et `Retry-After`.
  Voir [ANTI-ASPIRATION.md](ANTI-ASPIRATION.md).
- Le code est dans `src/cal_iut/api/ics_feed.py` (format) et `src/cal_iut/api/main.py` (routes `/ics/…`).
