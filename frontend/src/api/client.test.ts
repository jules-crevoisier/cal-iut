/**
 * Dédoublonnage des lectures en vol (29/09/2026, « limiter les connexions au
 * serveur ») : au démarrage et après chaque action, plusieurs effets
 * redemandaient `/app-state` (≈ 590 Ko) en même temps. Deux GET identiques
 * simultanés doivent partager UNE requête réseau — et seulement pendant
 * qu'elle est en vol : ce n'est pas un cache (celui-là reste le navigateur,
 * via l'ETag du serveur).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAppState, fetchVersion, movePlacement, nombreLecturesEnVol, setAccessToken } from "./client";

function reponseJson(corps: unknown): Response {
  return new Response(JSON.stringify(corps), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("api/client — lectures en vol partagées", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shares one network request between two identical GETs in flight", async () => {
    let repondre: (r: Response) => void = () => {};
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => (repondre = resolve)));

    const premier = fetchAppState();
    const second = fetchAppState();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(nombreLecturesEnVol()).toBe(1);

    repondre(reponseJson({ rows: [] }));
    const [a, b] = await Promise.all([premier, second]);
    expect(a).toEqual({ rows: [] });
    expect(b).toBe(a);
    expect(nombreLecturesEnVol()).toBe(0);
  });

  it("goes back to the network once the previous answer has arrived (not a cache)", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reponseJson({ revision: 1, modifie_le: "x" })));

    await fetchVersion();
    await fetchVersion();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never merges two different URLs, nor a GET with a personal-link token and one without", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reponseJson({})));

    const sansJeton = fetchAppState();
    setAccessToken("KBR");
    const avecJeton = fetchAppState();
    const autre = fetchVersion();
    await Promise.all([sansJeton, avecJeton, autre]);

    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual(["/app-state", "/app-state?t=KBR", "/api/v1/version?t=KBR"]);
  });

  it("never merges writes: two identical PATCHes are two requests", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reponseJson({ session_id: "s1" })));

    await Promise.all([
      movePlacement("s1", { week: 1, day: 0, slot: 0 }),
      movePlacement("s1", { week: 1, day: 0, slot: 0 }),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("releases the slot when the request fails, and both callers see the error", async () => {
    fetchMock.mockReturnValueOnce(
      Promise.resolve(new Response(JSON.stringify({ detail: "Authentification requise." }), { status: 401 })),
    );

    const premier = fetchAppState();
    const second = fetchAppState();
    await expect(premier).rejects.toThrow("Authentification requise.");
    await expect(second).rejects.toThrow("Authentification requise.");
    expect(nombreLecturesEnVol()).toBe(0);
  });

  it("lets the browser revalidate with the ETag: no `cache` option is ever forced", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reponseJson({})));

    await fetchAppState();
    const init = fetchMock.mock.calls[0][1] as RequestInit | undefined;
    expect(init?.cache).toBeUndefined();
  });
});
