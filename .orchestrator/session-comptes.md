# Session (comptes utilisateurs)

Fichier séparé de `.orchestrator/session.md` : ce dernier appartient à une
autre session en cours (feature/mcp-edt-agent), ne pas l'écraser.

goal: Remplacer l'auth par mot de passe partagé (CAL_IUT_PASSWORD) par de
vrais comptes utilisateur individuels, avec rôles, confirmation email, et
réinitialisation de mot de passe oublié.
out_of_scope: les liens publics profs/promo (`?t=...`) restent sans compte,
inchangés ; pas de SSO/OAuth externe pour l'instant ; pas de 2FA.
users: personnel IUT MMI Troyes (profs, admin), desktop d'abord, mobile
utilisable.
branch: feature/comptes-utilisateurs

locked:
- Le mot de passe partagé CAL_IUT_PASSWORD est RETIRÉ une fois les comptes
  en place. Les liens `?t=...` (profs/promo) restent tels quels (déjà
  voulus publics, hors périmètre).
- Inscription ouverte à n'importe quel email, confirmation par lien email
  obligatoire avant connexion possible.
- Après confirmation email, le compte est en statut PENDING : aucun accès
  au planning tant qu'un admin ne l'active pas explicitement.
- 3 paliers de droits : lecture seule / édition (déplacer, créer des
  séances) / admin (+ gérer comptes et droits d'autrui).
- crevoisier.ju@gmail.com et kyllian.bresson@univ-reims.fr sont
  auto-promus admin (à la création du compte, sans attendre une action
  d'un autre admin).
- Mot de passe oublié : lien de réinitialisation par email, à durée de
  vie limitée, à usage unique.
- Réutilise l'intégration mail existante (Resend, RESEND_API_KEY +
  CAL_IUT_PUBLIC_URL déjà configurés côté notifications enseignants).

open:
- none

architecte:
- Cookie de session par compte (HMAC, 30j), pas JWT — rôle/statut relus en
  base à chaque requête (désactivation/changement de rôle effectif
  immédiatement, pas d'attente d'expiration de cookie).
- Argon2 (argon2-cffi) pour le hash des mots de passe.
- Cutover net : CAL_IUT_PASSWORD supprimé du code en même temps que les
  comptes arrivent, pas de double mode.
- Un re-signup sur un email déjà en pending_email RENVOIE un nouveau lien
  de confirmation au lieu de refuser (403 anti-scanner mail).
- CLI (`cal-iut prod diff/push`) : nouveau compte email+mdp requis
  (CAL_IUT_EMAIL / CAL_IUT_PROD_EMAIL), celui de crevoisier.ju@gmail.com
  (admin auto) une fois créé/confirmé.
- Contrat complet livré par l'agent architecte (modèles User/EmailToken,
  8+ endpoints /auth/* + /admin/users, mapping des rôles sur les routes
  existantes) — voir sortie agent, non recopiée ici (trop long pour ce
  fichier).

acceptance:
- Un nouveau compte ne peut pas se connecter avant confirmation email.
- Un compte confirmé mais PENDING ne peut rien voir/modifier du planning
  tant qu'un admin ne l'a pas activé.
- Les 2 emails admin obtiennent le rôle admin dès la création du compte,
  sans étape manuelle.
- Un lien de réinitialisation de mot de passe expiré ou déjà utilisé est
  refusé.
- CAL_IUT_PASSWORD n'ouvre plus jamais l'accès une fois la bascule faite.
- Les liens `?t=...` profs/promo continuent de fonctionner sans compte.
