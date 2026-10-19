/**
 * Signalement du 19/10/2026 : en local, « Serveur injoignable » s'affichait
 * sur Tâches, Comptes, Sauvegardes, Trafic : le proxy Vite ne relayait pas
 * ces routes et renvoyait index.html.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const config = readFileSync("vite.config.ts", "utf-8");

describe("proxy de dev Vite", () => {
  it.each([
    "/admin", "/taches", "/controles", "/sauvegardes",
    "/notifications", "/mail", "/rooms", "/calendrier", "/ics",
  ])("relaie %s vers l'API", (prefixe) => {
    expect(config).toContain(`"${prefixe}": "http://127.0.0.1:8000"`);
  });
});
