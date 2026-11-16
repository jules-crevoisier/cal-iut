/**
 * Relecture d'un brouillon (16/11/2026) : les lectures du planning vont
 * chercher le brouillon, et aucune écriture ne part vers le serveur.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ErreurApi,
  MESSAGE_RELECTURE,
  fetchAppState,
  fetchDoublons,
  fetchTimetable,
  annulerGeneration,
  creerSauvegardeMaintenant,
  lancerGeneration,
  logout,
  setBrouillonEnRelecture,
  supprimerBrouillon,
} from "./client";

function stubFetch() {
  const appels: { url: string; methode: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), methode: init?.method ?? "GET" });
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ doublons: [], placements: [] }) });
    }),
  );
  return appels;
}

describe("relecture d'un brouillon", () => {
  afterEach(() => {
    setBrouillonEnRelecture(null);
    vi.unstubAllGlobals();
  });

  it("lit le planning, les placements et les doublons du brouillon", async () => {
    const appels = stubFetch();
    setBrouillonEnRelecture(16);

    await fetchAppState();
    await fetchTimetable({ group_id: "but1-td-ab" });
    await fetchDoublons(3);

    expect(appels.map((a) => a.url)).toEqual([
      "/brouillons/16/app-state",
      "/brouillons/16/timetable?group_id=but1-td-ab",
      "/brouillons/16/controles/doublons?semaine=3",
    ]);
  });

  it("revient au planning en service une fois la relecture quittée", async () => {
    const appels = stubFetch();
    setBrouillonEnRelecture(16);
    setBrouillonEnRelecture(null);

    await fetchAppState();

    expect(appels.map((a) => a.url)).toEqual(["/app-state"]);
  });

  it("refuse toute écriture sans l'envoyer au serveur", async () => {
    const appels = stubFetch();
    setBrouillonEnRelecture(16);

    const essais = [
      () => lancerGeneration({ semestre_group: "even" }),
      () => annulerGeneration("20261116-171750-87bc"),
      () => creerSauvegardeMaintenant(),
    ];
    for (const essai of essais) {
      const promesse = essai();
      await expect(promesse).rejects.toBeInstanceOf(ErreurApi);
      await expect(essai()).rejects.toThrow(MESSAGE_RELECTURE);
    }
    expect(appels).toEqual([]);
  });

  it("laisse passer la suppression du brouillon et la déconnexion", async () => {
    const appels = stubFetch();
    setBrouillonEnRelecture(16);

    await supprimerBrouillon(16);
    await logout();

    expect(appels.map((a) => `${a.methode} ${a.url}`)).toEqual(["DELETE /brouillons/16", "POST /auth/logout"]);
  });
});
