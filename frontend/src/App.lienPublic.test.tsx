/**
 * Lien public (`#mode=prof|groupe|promo|salles&t=...`) : l'application ne
 * doit appeler QUE les lectures que le serveur ouvre au lien perso
 * (`_LIEN_PERSO_PREFIXES`, `api/main.py`). Un appel à une route
 * d'administration (`/diff`, `/feedback/analysis`, `/controles/doublons`...)
 * répondrait 401 côté serveur depuis l'audit de septembre 2026 (P0-2).
 */
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { emptyPayload } from "./test/payloadFixture";

const LECTURES_PUBLIQUES = ["/meta", "/app-state", "/timetable", "/ics/", "/api/v1/version"];

function reponse(url: string) {
  const chemin = new URL(url, "http://localhost").pathname;
  let corps: unknown = {};
  if (chemin === "/app-state") corps = emptyPayload();
  else if (chemin === "/timetable") corps = { placements: [], status: "ok" };
  else if (chemin === "/meta") corps = { groups: [], rooms: [], parcours: [], semestres: [], years: [] };
  else if (chemin === "/auth/me") return { ok: false, status: 401, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => corps };
}

describe("App en lien public", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => Promise.resolve(reponse(String(url)))),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it.each([
    "/#mode=prof&prof=KBR&t=KBR",
    "/#mode=groupe&groupe=but1-td-ab&t=but1-td-ab",
    "/#mode=promo&t=promo",
    "/#mode=salles&t=salles",
  ])("should only call public read endpoints for %s", async (hash) => {
    window.history.replaceState(null, "", hash);
    render(<App />);
    await waitFor(() => {
      const chemins = vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost").pathname);
      expect(chemins).toContain("/app-state");
    });
    // Laisse partir les appels déclenchés après le premier rendu.
    await new Promise((r) => setTimeout(r, 50));
    const chemins = vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost").pathname);
    // `/auth/me` compris : un lien public n'a jamais de session, la question
    // partait en 401 à chaque ouverture (erreur rouge dans la console).
    const horsListe = chemins.filter((c) => !LECTURES_PUBLIQUES.some((p) => c.startsWith(p)));
    expect(horsListe).toEqual([]);
  });
});
