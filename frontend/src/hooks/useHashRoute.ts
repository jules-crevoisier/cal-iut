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
  | "cours";

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
  mode: "prof" | "groupe" | "";
  /** Code du lien personnel (prof ou groupe) — public depuis le
   * 28/08/2026 (`api/auth.py`), seul moyen pour un lien personnel de
   * contourner le mot de passe partagé. Jamais envoyé au serveur par LE
   * FRAGMENT lui-même (comme le reste du routage), mais lu une fois au
   * démarrage (App.tsx) pour être rejoué en paramètre de requête sur
   * chaque appel API (`api/client.ts::setAccessToken`). */
  t: string;
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
};

const ENTITY_RESET: Pick<Route, "prof" | "groupe" | "salle" | "cours" | "panel"> = {
  prof: "",
  groupe: "",
  salle: "",
  cours: "",
  panel: "",
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
