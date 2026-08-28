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
  | "aplacer";

export interface Route {
  vue: RouteView | "";
  prof: string;
  groupe: string;
  sem: number | null;
  mode: "prof" | "groupe" | "";
}

const EMPTY_ROUTE: Route = { vue: "", prof: "", groupe: "", sem: null, mode: "" };

function readHash(): Route {
  const raw = (window.location.hash || "").replace(/^#/, "");
  const params = new URLSearchParams(raw);
  return {
    vue: (params.get("vue") as RouteView) || "",
    prof: params.get("prof") || "",
    groupe: params.get("groupe") || "",
    sem: params.get("sem") ? Number(params.get("sem")) : null,
    mode: (params.get("mode") as Route["mode"]) || "",
  };
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
      const next = { ...prev, ...patch };
      const hash = toHash(next);
      if (hash !== window.location.hash) {
        window.history.replaceState(null, "", hash);
      }
      return next;
    });
  }, []);

  return { route, setRoute };
}
