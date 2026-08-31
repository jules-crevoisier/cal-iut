# MCP cal-iut — brancher Claude sur l’emploi du temps

Le serveur MCP est `POST https://cal-iut-mmi.srko.fr/mcp`.
Outils : `inspect` (lire), `plan` (dry-run), `apply` (écrire, après confirm).

L’auth MCP est un **Bearer**, jamais le cookie de session du site.

1. **Clé de compte** (recommandé) : dans cal-iut, menu **Clé Claude / MCP**,
   générer une clé `caliut_…`. Le brut s’affiche **une fois**. Copiez-le.
   Le rôle du compte s’applique : `read_only` → `inspect` seulement ;
   `edit` / `admin` → `inspect` + `plan` + `apply`. Compte désactivé ou
   clé révoquée → 401.
2. **Jeton machine** (optionnel) : `CAL_IUT_MCP_TOKEN` dans Dokploy /
   Compose, rôle `edit`. Utile pour un agent CI, pas pour les humains.

Ne mets jamais une clé dans un chat, un commit, ou un screenshot.

Dokploy n’a plus besoin du jeton env si tout le monde utilise une clé
de compte. S’il est encore là : `CAL_IUT_MCP_TOKEN: ${CAL_IUT_MCP_TOKEN}`
dans le Compose backend. Sans Bearer valide → **401**.

---

## Claude.ai (claude.com)

Pas de fichier de config : tout se fait dans l’UI.

1. Va sur [claude.ai](https://claude.ai) (compte Pro / Max / Team).
2. **Customize → Connectors** (Team/Enterprise : *Organization settings → Connectors*).
3. **Add custom connector**.
4. Nom : `cal-iut`. URL : `https://cal-iut-mmi.srko.fr/mcp`.
5. Auth : **None** (pas OAuth) + **Request headers** (bêta, pas toujours visible) :
   - Header : `authorization`
   - Valeur **exacte** : `Bearer ` + ta clé (le mot `Bearer`, un espace, la clé).
     Claude n’ajoute pas `Bearer` tout seul. Coller seulement la clé → 401.
6. **Add**. Dans un nouveau chat : `+` → Connectors → activer `cal-iut`.
   Approuve les outils (`inspect` / `plan` / `apply`) quand Claude les propose.

Si tu n’as pas la section *Request headers*, l’orga n’a pas encore le bêta
`static_headers`. Utilise alors **Claude Code** (fichier ci-dessous) ou
demande l’accès headers à Anthropic.

Pour changer la clé : révoque l’ancienne dans cal-iut, génère-en une
nouvelle, puis supprime et recrée le connecteur (l’UI ne réédite pas
le header une fois sauvé).

---

## Claude Code / Cursor (fichier local)

C’est ici qu’un agent peut **créer le JSON et ouvrir le fichier** pour que
tu colles ta clé. Ne commite jamais ce fichier s’il contient le secret.

| Produit | Fichier Windows |
|--------|------------------|
| Claude Code (user) | `%USERPROFILE%\.claude.json` → clé `mcpServers` |
| Claude Code (projet) | `cal-iut\.mcp.json` (à gitignorer s’il a un secret) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` |

Bloc à fusionner (laisse le placeholder, **n’invente pas** de clé) :

```json
{
  "mcpServers": {
    "cal-iut": {
      "type": "http",
      "url": "https://cal-iut-mmi.srko.fr/mcp",
      "headers": {
        "Authorization": "Bearer COLLER_LE_JETON_ICI"
      }
    }
  }
}
```

`type` est obligatoire (`http` ou `streamable-http`). Sans `type`, Claude
Code croit à du stdio et ignore le serveur.

Pas d’espace ni de retour à la ligne autour de la clé (sinon 401).

En CLI Claude Code, équivalent :

```powershell
claude mcp add-json cal-iut '{"type":"http","url":"https://cal-iut-mmi.srko.fr/mcp","headers":{"Authorization":"Bearer COLLER_LE_JETON_ICI"}}'
```

Puis ouvre le fichier et remplace le placeholder.

---

## Prompt à coller dans Cursor / Claude Code

Copie tout le bloc. L’agent écrit la config, **ouvre le fichier**, et
s’arrête pour que tu colles ta clé (générée dans cal-iut → Clé Claude / MCP).

```
Configure le MCP distant cal-iut sur cette machine, puis ouvre le fichier
pour que je colle le jeton. N’invente pas de jeton, ne lis pas .env,
ne commit rien.

URL : https://cal-iut-mmi.srko.fr/mcp
Transport HTTP (type: "http" ou "streamable-http"), pas stdio.
Header Authorization exactement : Bearer COLLER_LE_JETON_ICI
(le mot Bearer, un espace, le placeholder — je remplacerai le placeholder).

Fichiers, dans cet ordre (le premier qui correspond au produit que
j’utilise ; fusionne mcpServers s’il existe déjà) :
1. Cursor : %USERPROFILE%\.cursor\mcp.json
2. Claude Code user : %USERPROFILE%\.claude.json (clé mcpServers)
3. Claude Desktop : %APPDATA%\Claude\claude_desktop_config.json

Écris / merge le JSON, puis OUVRE ce fichier dans l’éditeur tout de suite
et dis-moi quelle ligne remplacer. Si le produit est Claude.ai (navigateur),
dis-moi que ce n’est pas un fichier : Customize → Connectors → Add custom
connector, URL ci-dessus, header authorization = Bearer + jeton.
```

---

## Vérifier

Sans header → **401**. Avec `Bearer` + une clé valide (compte ou env) →
**200** sur `initialize`. `tools/list` montre `inspect`, `plan`, `apply`.

Dans Claude : « Liste les séances WRA507C » doit passer par `inspect`.
Ne jamais `apply` sans avoir montré un `plan` et obtenu un confirm explicite.

| Rôle compte | MCP |
|-------------|-----|
| `read_only` | `inspect` seulement (`plan` / `apply` → erreur) |
| `edit` / `admin` | `inspect` + `plan` + `apply` |
| compte non `active` ou clé révoquée | 401 |
