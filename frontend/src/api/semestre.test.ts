/**
 * Sélecteur semestre impair / pair (16/11/2026) : le semestre choisi part
 * dans l'en-tête `X-Semestre-Groupe` de toutes les requêtes ; sans choix,
 * aucun en-tête, et le serveur sert le semestre en cours.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAppState, getSemestreChoisi, setSemestreChoisi } from "./client";

function stubFetch() {
  const entetes: Record<string, string>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init?: RequestInit) => {
      entetes.push({ ...(init?.headers as Record<string, string>) });
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    }),
  );
  return entetes;
}

describe("semestre affiché", () => {
  afterEach(() => {
    setSemestreChoisi(null);
    vi.unstubAllGlobals();
  });

  it("n'envoie aucun en-tête tant qu'aucun semestre n'est choisi", async () => {
    const entetes = stubFetch();

    await fetchAppState();

    expect(entetes[0]).not.toHaveProperty("X-Semestre-Groupe");
  });

  it("demande le semestre choisi et le garde sur ce navigateur", async () => {
    const entetes = stubFetch();
    setSemestreChoisi("even");

    await fetchAppState();

    expect(entetes[0]["X-Semestre-Groupe"]).toBe("even");
    expect(getSemestreChoisi()).toBe("even");
    expect(window.localStorage.getItem("cal-iut:semestre-groupe")).toBe("even");
  });

  it("oublie le choix quand on revient au semestre en cours", () => {
    setSemestreChoisi("even");
    setSemestreChoisi(null);

    expect(window.localStorage.getItem("cal-iut:semestre-groupe")).toBeNull();
  });
});
