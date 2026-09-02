/**
 * Routage par fragment d'URL (`#vue=prof&prof=KBR&mode=prof`) — même schéma
 * que la page HTML/JS historique (`export/templates/timetable.html`), pour
 * que les liens personnels générés côté serveur (annuaire, mailto) restent
 * valides quelle que soit l'interface qui les ouvre.
 *
 * Le fragment n'est JAMAIS envoyé au serveur : un lien `mode=prof` fonctionne
 * identiquement que la page soit servie par `cal-iut serve` ou ouverte
 * localement — propriété volontairement conservée du portage HTML.
 */

import { useCallback, useEffect, useState } from "react";

export type RouteView =
  | "semaine"
  | "groupe"
  | "prof"
  | "promo"
  | "reference"
  | "contraintes"
  | "apf"
  | "aplacer"
  | "salle"
  | "cours"
  | "comptes"
  | "celcat"
  | "mcp";

/** Écrans du système de comptes (31/08/2026) — pré-authentification,
 * distincts des `RouteView` (qui supposent une session active) : lus AVANT
 * de savoir si quelqu'un est connecté. `confirme` est la cible du lien
 * envoyé par mail (`GET /auth/confirm-email`, redirection serveur) ;
 * `reinitialiser` celle du lien de mot de passe oublié — les deux portent
 * un jeton dans le fragment, jamais envoyé au serveur autrement que via le
 * paramètre `token` de leur propre requête POST. */
export type RouteCompte = "" | "inscription" | "mot-de-passe-oublie" | "confirme" | "reinitialiser";

export type RoutePanel = "" | "aplacer";

export interface Route {
  vue: RouteView | "";
  prof: string;
  groupe: string;
  salle: string;
  cours: string;
  panel: RoutePanel;
  sem: number | null;
  /** Jour (0 = lundi) — utilisé par la Vue Promo, qui affiche un jour à la
   *  fois : sans lui, un lien « telle séance, tel créneau » ouvre le bon
   *  écran mais pas le bon jour. */
  jour: number | null;
  /** "promo" (retour utilisateur 31/08/2026 : « un lien en plus ouvert à
   * tout le monde [...] accès à la vue promo ») — contrairement à
   * "prof"/"groupe", ne cible aucune entité : la Vue Promo entière, en
   * lecture seule. Même mécanisme public que les deux autres (cf.
   * `api/auth.py::verify_personal_link_param` — seule la présence de `t`
   * compte, jamais son contenu). */
  mode: "prof" | "groupe" | "promo" | "";
  /** Code du lien personnel (prof ou groupe) — public depuis le
   * 28/08/2026 (`api/auth.py`), seul moyen pour un lien personnel de
   * contourner le mot de passe partagé. Jamais envoyé au serveur par LE
   * FRAGMENT lui-même (comme le reste du routage), mais lu une fois au
   * démarrage (App.tsx) pour être rejoué en paramètre de requête sur
   * chaque appel API (`api/client.ts::setAccessToken`). */
  t: string;
  /** Écran de compte à afficher (inscription/reset/confirmation) — lu
   * indépendamment de `vue`, avant de savoir si une session existe. */
  compte: RouteCompte;
  /** Résultat de `GET /auth/confirm-email` (redirection serveur,
   * `#compte=confirme&statut=ok|erreur`) — jamais posé par le frontend
   * lui-même. */
  statut: "" | "ok" | "erreur";
  /** Jeton de réinitialisation de mot de passe (`#compte=reinitialiser
   * &token=...`, lien envoyé par mail) — à usage unique côté serveur. */
  token: string;
}

const EMPTY_ROUTE: Route = {
  vue: "",
  prof: "",
  groupe: "",
  salle: "",
  cours: "",
  panel: "",
  sem: null,
  jour: null,
  mode: "",
  t: "",
  compte: "",
  statut: "",
  token: "",
};

const ENTITY_RESET: Pick<Route, "prof" | "groupe" | "salle" | "cours" | "panel" | "compte" | "statut" | "token"> = {
  prof: "",
  groupe: "",
  salle: "",
  cours: "",
  panel: "",
  compte: "",
  statut: "",
  token: "",
};

function asPanel(value: string | null): RoutePanel {
  return value === "aplacer" ? "aplacer" : "";
}

function canonicalize(route: Route): Route {
  if (route.vue === "aplacer") {
    return { ...route, vue: "promo", panel: "aplacer" };
  }
  return route;
}

function readHash(): Route {
  const raw = (window.location.hash || "").replace(/^#/, "");
  const params = new URLSearchParams(raw);
  const vue = (params.get("vue") as RouteView) || "";
  return canonicalize({
    vue,
    prof: params.get("prof") || "",
    groupe: params.get("groupe") || "",
    salle: params.get("salle") || "",
    cours: params.get("cours") || "",
    panel: asPanel(params.get("panel")),
    sem: params.get("sem") ? Number(params.get("sem")) : null,
    jour: params.get("jour") !== null ? Number(params.get("jour")) : null,
    mode: (params.get("mode") as Route["mode"]) || "",
    t: params.get("t") || "",
    compte: (params.get("compte") as RouteCompte) || "",
    statut: (params.get("statut") as Route["statut"]) || "",
    token: params.get("token") || "",
  });
}

function toHash(route: Partial<Route>): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(route)) {
    if (v !== "" && v !== null && v !== undefined) params.set(k, String(v));
  }
  return "#" + params.toString();
}

/** Construit un lien ABSOLU (partageable tel quel — mail, copier-coller). */
export function buildLink(patch: Partial<Route>): string {
  return window.location.origin + window.location.pathname + toHash(patch);
}

export function useHashRoute(): {
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
} {
  const [route, setRouteState] = useState<Route>(() => (typeof window === "undefined" ? EMPTY_ROUTE : readHash()));

  useEffect(() => {
    const onHashChange = () => setRouteState(readHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setRoute = useCallback((patch: Partial<Route>) => {
    setRouteState((prev) => {
      const base =
        patch.vue !== undefined && patch.vue !== prev.vue ? { ...prev, ...ENTITY_RESET, ...patch } : { ...prev, ...patch };
      const next = canonicalize(base);
      const hash = toHash(next);
      if (hash !== window.location.hash) {
        window.history.replaceState(null, "", hash);
      }
      return next;
    });
  }, []);

  return { route, setRoute };
}
