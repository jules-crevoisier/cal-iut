/**
 * Thème de l'interface : « Système » (suit le réglage du poste), « Clair »
 * (Lumière) ou « Sombre » (Nuit) — choix gardé sur l'appareil, appliqué par
 * l'attribut `data-theme` de <html> que les jetons de `app.css` lisent déjà.
 */

import { ecrireLocal, lireLocal } from "./stockageLocal";

export type Theme = "systeme" | "clair" | "sombre";

const CLE = "cal-iut:theme";

const estTheme = (v: unknown): v is Theme => v === "systeme" || v === "clair" || v === "sombre";

export function lireTheme(): Theme {
  return lireLocal<Theme>(CLE, "systeme", estTheme);
}

export function appliquerTheme(theme: Theme): void {
  const racine = document.documentElement;
  if (theme === "clair") racine.dataset.theme = "light";
  else if (theme === "sombre") racine.dataset.theme = "dark";
  else delete racine.dataset.theme;
}

export function choisirTheme(theme: Theme): void {
  ecrireLocal(CLE, theme);
  appliquerTheme(theme);
}
