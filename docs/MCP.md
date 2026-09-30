# Piloter le planning avec Claude (serveur MCP)

Ce document explique comment brancher Claude (ou Cursor) sur l'emploi du temps, pour le lire et le modifier.
Il est pour les techniciens et les responsables du planning à l'aise avec ces outils.

**Sommaire**

1. [Ce que c'est](#1-ce-que-cest)
2. [Qui peut s'en servir ?](#2-qui-peut-sen-servir-)
3. [Obtenir une clé](#3-obtenir-une-clé)
4. [Connecter Claude.ai](#4-connecter-claudeai)
5. [Connecter Claude Code, Claude Desktop ou Cursor](#5-connecter-claude-code-claude-desktop-ou-cursor)
6. [Vérifier que ça marche](#6-vérifier-que-ça-marche)
7. [Les outils disponibles](#7-les-outils-disponibles)
8. [Précautions](#8-précautions)
9. [Pour les techniciens](#9-pour-les-techniciens)

---

## 1. Ce que c'est

MCP (Model Context Protocol) est un moyen standard de donner des outils à un assistant comme Claude.
Le serveur MCP de l'appli est à l'adresse `https://cal-iut-mmi.srko.fr/mcp`.

Avec lui, on peut demander à Claude : « Déplace le TD de WR101 du groupe AB en semaine 7, mardi 14 h ».
Claude lit le planning, prépare le changement, le montre, puis l'applique **après votre accord**.

Toutes les règles de l'appli s'appliquent : indisponibilités, SAE, ordre pédagogique, salles, semaines verrouillées.

---

## 2. Qui peut s'en servir ?

| Rôle du compte | Ce qu'il peut faire avec MCP |
|---|---|
| Lecture seule | Lire (`inspect`) seulement. `plan` et `apply` répondent « Permissions insuffisantes : lecture seule. » |
| Édition, Admin | Lire, préparer (`plan`) et appliquer (`apply`) |
| Accès API | Rien : refus `403`. Ses clés ne lisent que l'API v1 ([API.md](API.md)). |
| Compte désactivé, clé révoquée | Rien : refus `401` |

Les rôles se règlent dans l'écran **Comptes** (administrateurs, cf. [ADMIN.md](ADMIN.md)).

---

## 3. Obtenir une clé

1. Se connecter à l'appli.
2. Ouvrir le menu du compte (avatar, en bas de la barre latérale) → **Clé API**.
3. Donner un nom (ex. « Claude »), puis cliquer sur **Générer une clé**.
4. Copier ce qu'il faut avant de fermer. La page propose trois boutons :
   - **Copier la valeur** : `Bearer caliut_…`, pour Claude.ai ;
   - **Copier l'adresse** : l'adresse du serveur MCP ;
   - **Copier le bloc** : le bloc de configuration pour Claude Code ou Cursor.
5. Cliquer sur **J'ai copié la clé**. La clé ne sera **plus jamais affichée**.

C'est la même clé que pour l'API v1. 5 clés actives au plus par compte. **Révoquer** la coupe aussitôt.

---

## 4. Connecter Claude.ai

Tout se fait dans l'interface de Claude.ai (formule Pro, Max, Team ou Enterprise).

1. Aller dans **Customize** → **Connectors** (Team / Enterprise : **Organization settings** → **Connectors**).
2. Cliquer sur **Add custom connector**.
3. Nom : `cal-iut`. URL : `https://cal-iut-mmi.srko.fr/mcp`.
4. Authentification : **None** (pas OAuth).
5. Dans **Request headers**, ajouter :
   - en-tête : `authorization` ;
   - valeur : `Bearer ` suivi de la clé (le mot `Bearer`, une espace, la clé). Coller la clé seule donne `401`.
6. Cliquer sur **Add**.
7. Dans une nouvelle conversation : **+** → **Connectors** → activer `cal-iut`.

Le connecteur apparaît. Claude demande votre accord avant d'utiliser chaque outil.

> **À savoir :** la section **Request headers** est en bêta et n'est pas toujours visible.
> Sans elle, utiliser Claude Code (section suivante).

**Changer de clé :** révoquer l'ancienne dans l'appli, en générer une nouvelle, puis supprimer et recréer le connecteur.
L'interface ne permet pas de modifier l'en-tête après coup.

---

## 5. Connecter Claude Code, Claude Desktop ou Cursor

Ajouter ce bloc dans le fichier de configuration (ou cliquer sur **Copier le bloc** après avoir généré la clé) :

```json
{
  "mcpServers": {
    "cal-iut": {
      "type": "http",
      "url": "https://cal-iut-mmi.srko.fr/mcp",
      "headers": {
        "Authorization": "Bearer COLLER_LA_CLE_ICI"
      }
    }
  }
}
```

| Outil | Fichier (Windows) |
|---|---|
| Claude Code (utilisateur) | `%USERPROFILE%\.claude.json`, clé `mcpServers` |
| Claude Code (projet) | `.mcp.json` à la racine du dépôt (ne jamais le committer avec une clé) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` |

- `"type": "http"` est obligatoire (ou `streamable-http`). Sans lui, Claude Code ignore le serveur.
- Aucune espace ni retour à la ligne autour de la clé (sinon `401`).
- S'il existe déjà un bloc `mcpServers`, y ajouter seulement l'entrée `cal-iut`.

En ligne de commande Claude Code, même résultat :

```powershell
claude mcp add-json cal-iut '{"type":"http","url":"https://cal-iut-mmi.srko.fr/mcp","headers":{"Authorization":"Bearer COLLER_LA_CLE_ICI"}}'
```

Puis ouvrir le fichier et remplacer `COLLER_LA_CLE_ICI` par la clé.

**Mode d'emploi pour l'assistant.** Le dépôt contient une « compétence » qui apprend à Claude la bonne méthode
(lire, préparer, faire confirmer, appliquer ; correspondance des semaines) :
`.claude/skills/cal-iut-edt/` pour Claude Code, `.cursor/skills/cal-iut-edt/` pour Cursor.
Elle se charge toute seule quand on parle d'emploi du temps.

**Faire écrire la configuration par l'assistant.** Coller ce message dans Claude Code ou Cursor :

```
Configure le serveur MCP distant cal-iut sur cette machine, puis ouvre le fichier pour que je colle la clé.
N'invente pas de clé, ne lis pas .env, ne committe rien.
URL : https://cal-iut-mmi.srko.fr/mcp — transport HTTP (type "http"), pas stdio.
En-tête Authorization exactement : Bearer COLLER_LA_CLE_ICI
Fichier : celui de l'outil que j'utilise (Cursor : %USERPROFILE%\.cursor\mcp.json ;
Claude Code : %USERPROFILE%\.claude.json ; Claude Desktop : %APPDATA%\Claude\claude_desktop_config.json).
Fusionne avec mcpServers s'il existe, ouvre le fichier et dis-moi quelle ligne remplacer.
Si j'utilise Claude.ai dans le navigateur, dis-moi que ce n'est pas un fichier : Customize → Connectors.
```

---

## 6. Vérifier que ça marche

1. Dans Claude, demander : « Liste les séances de WRA507C ». Claude doit utiliser l'outil `inspect`.
2. En ligne de commande (remplacer `$CLE`) :

```bash
curl -s -X POST https://cal-iut-mmi.srko.fr/mcp \
  -H "Authorization: Bearer $CLE" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Résultat attendu : la liste des outils `inspect`, `plan`, `apply`. Sans en-tête ou avec une mauvaise clé : `401`.

---

## 7. Les outils disponibles

| Outil | Ce qu'il fait | Écrit ? | Rôle minimum |
|---|---|---|---|
| `inspect` | Lit le planning. Sans filtre : un index (codes des cours, des enseignants, nombre de semaines). Avec `teacher_code` ou `course_code` : les séances, le catalogue (enseignants, salles, groupes, semaines, séances non placées, disponibilités) et le journal MCP. | Non | Lecture seule |
| `plan` | Prépare des changements **sans rien écrire**. Chaque élément reçoit un statut : `ok`, `blocked` (interdit) ou `forceable` (possible en forçant). | Non | Édition |
| `apply` | Applique un plan déjà montré, avec `confirm=true`. Refuse tout le lot si un élément est `blocked`. | **Oui** | Édition |

Opérations possibles dans `plan` (champ `op`) :

| `op` | Effet | Champs |
|---|---|---|
| `place` | Placer une séance non placée | `session_id`, `week`, `day`, `slot`, `room_id` (facultatif) |
| `move` | Déplacer une séance | `session_id`, `week`, `day`, `slot`, `room_id` (facultatif) |
| `swap` | Échanger deux séances | `session_id`, `session_b` |
| `unplace` | Retirer une séance du planning | `session_id` |
| `salle` | Changer de salle | `session_id`, `room_id` |
| `seance` | Modifier une séance (enseignants, type, durée, position, salle, évaluation) | `session_id` + champs à changer |
| `custom_create` | Créer une séance hors maquette | `course_code`, `session_type`, `group_ids`, `teacher_codes`, `week`, `day`, `slot`… |
| `custom_patch` | Modifier une séance hors maquette | `session_id` + champs à changer |
| `custom_delete` | Supprimer une séance hors maquette | `session_id` |

Repères : `day` 0 = lundi … 4 = vendredi ; `slot` 0 = 8h, 1 = 9h30, 2 = 11h, 3 = 14h, 4 = 15h30, 5 = 17h.

> **Attention : numéro de semaine.** `week` est l'**index** de semaine (0, 1, 2…), pas la « Semaine N » affichée.
> Exemple : index `1` = « Semaine 3 ». La correspondance est dans `catalog.weeks` (champ `label`) d'un `inspect` filtré.
> Envoyer N ou N + 1 à la place de l'index place la séance sur la mauvaise semaine.

---

## 8. Précautions

1. **Toujours** passer par `plan`, montrer le résultat, obtenir un accord explicite, **puis** `apply`.
2. Ne jamais forcer un élément `blocked` (SAE, indisponibilité déclarée, contrainte institutionnelle).
   `forceable` ne se force qu'avec l'accord d'un humain.
3. Un `apply` s'exécute élément par élément. Si le 3e échoue, les deux premiers restent appliqués.
4. Ne jamais mettre une clé dans un chat, un commit, une capture d'écran ou un fichier partagé.
5. Une clé agit avec les droits de son compte. Prévoir une clé par usage, et révoquer celle qui ne sert plus.
6. Après un `401`, corriger la clé au lieu de réessayer en boucle : 30 refus en 10 minutes bloquent l'adresse IP 24 h
   (cf. [ANTI-ASPIRATION.md](ANTI-ASPIRATION.md)).
7. Les changements faits par MCP apparaissent dans l'appli comme ceux faits à la main (et partent vers Celcat de la même façon).

---

## 9. Pour les techniciens

- **Authentification :** uniquement l'en-tête `Authorization: Bearer …`. Le cookie de session de l'appli n'est jamais lu.
  Deux sources acceptées :
  - une clé de compte `caliut_…` (empreinte SHA-256 en base, rôle relu sur le compte à chaque appel) ;
  - le jeton machine `CAL_IUT_MCP_TOKEN` (variable d'environnement, rôle `edit`), utile pour un agent automatique.
    Facultatif si tout le monde utilise une clé de compte. Réglage : cf. [ADMIN.md](ADMIN.md).
- **Point d'entrée :** `POST /mcp` répond en JSON-RPC (`initialize`, `ping`, `tools/list`, `tools/call`).
  Les outils s'appellent `inspect`, `plan`, `apply`. Les alias `inspect_edt`, `plan_edt`, `apply_edt` sont acceptés
  (ce sont les noms exposés par le transport officiel monté sous `/mcp/`).
- **Réponses :** `plan` et `apply` renvoient un refus de rôle dans le résultat (`{"ok": false, "error": …}`), pas en erreur HTTP.
  `apply` n'écrit que si `confirm=true`, liste non vide, aucun `blocked`, et `plan_id` identique au plan s'il est fourni.
  Tout le lot s'exécute sous le verrou d'écriture du planning ; la révision avance ensuite (cf. [API.md](API.md)).
- **Journal :** chaque `apply` réussi est noté dans `data/state/mcp_journal.json` (200 dernières entrées) :
  date, `plan_id`, forçage, opérations, et l'adresse du compte pour une clé de compte. `inspect` le renvoie.
- **Débit :** trafic compté dans la catégorie « clé API » de l'anti-aspiration (300 requêtes par minute par compte,
  rafale de 150, en mode `enforce`). `/mcp` n'est jamais compressé en gzip.
- **Code :** `src/cal_iut/mcp/` (`auth.py` authentification, `tools.py` outils, `http_rpc.py` JSON-RPC,
  `server.py` transport officiel, `journal.py` journal).
