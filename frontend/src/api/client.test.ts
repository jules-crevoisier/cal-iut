/**
 * Dédoublonnage des lectures en vol (29/09/2026, « limiter les connexions au
 * serveur ») : au démarrage et après chaque action, plusieurs effets
 * redemandaient `/app-state` (≈ 590 Ko) en même temps. Deux GET identiques
 * simultanés doivent partager UNE requête réseau — et seulement pendant
 * qu'elle est en vol : ce n'est pas un cache (celui-là reste le navigateur,
 * via l'ETag du serveur).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DELAI_LECTURE_MS,
  ErreurApi,
  ecouterLiaison,
  estPanne,
  estSessionAbsente,
  fetchAppState,
  fetchMoi,
  fetchSante,
  fetchVersion,
  movePlacement,
  nombreLecturesEnVol,
  reinitialiserLiaison,
  setAccessToken,
} from "./client";
import type { EvenementLiaison } from "./client";

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

/**
 * Pannes masquées (audit du 29/09/2026, P1-13) : une coupure réseau affichait
 * l'écran de connexion (`fetchMoi` rendait `null` pour toute erreur) ou
 * « aucun planning ». Trois familles désormais distinctes : session absente
 * (401), panne (pas de réponse exploitable), refus (le serveur dit pourquoi).
 */
describe("api/client — session absente, panne ou refus", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let evenements: EvenementLiaison[];

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(null);
    reinitialiserLiaison();
    evenements = [];
    ecouterLiaison((e) => evenements.push(e));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    reinitialiserLiaison();
  });

  it("fetchMoi: a 401 means “not signed in” (null), announced as such", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "Authentification requise." }), { status: 401 }));
    await expect(fetchMoi()).resolves.toBeNull();
    expect(evenements).toEqual(["session-absente"]);
  });

  it("fetchMoi: a network failure is NOT “not signed in” — it throws a panne", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const erreur = await fetchMoi().catch((e: unknown) => e);
    expect(erreur).toBeInstanceOf(ErreurApi);
    expect(estPanne(erreur)).toBe(true);
    expect(estSessionAbsente(erreur)).toBe(false);
    expect(evenements).toEqual(["panne"]);
  });

  it("a gateway 502 or a crash (text body) is a panne", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>Bad Gateway</html>", { status: 502 }));
    fetchMock.mockResolvedValueOnce(new Response("Internal Server Error", { status: 500 }));
    expect(estPanne(await fetchAppState().catch((e: unknown) => e))).toBe(true);
    expect(estPanne(await fetchVersion().catch((e: unknown) => e))).toBe(true);
  });

  it("a 5xx carrying an application message is a refusal, with that message", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ message: "Envoi de mail indisponible." }), { status: 503 }));
    const erreur = await fetchAppState().catch((e: unknown) => e);
    expect(estPanne(erreur)).toBe(false);
    expect((erreur as ErreurApi).genre).toBe("refus");
    expect((erreur as Error).message).toBe("Envoi de mail indisponible.");
  });

  it("a 404 (no planning yet) is a refusal, not a panne", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "Aucun planning résolu" }), { status: 404 }));
    const erreur = await fetchAppState().catch((e: unknown) => e);
    expect((erreur as ErreurApi).genre).toBe("refus");
    expect((erreur as ErreurApi).status).toBe(404);
    expect(evenements).toEqual([]);
  });

  it("announces the recovery once, at the first answer after a panne", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    fetchMock.mockImplementation(() => Promise.resolve(reponseJson({ revision: 1, modifie_le: "x" })));
    await fetchVersion().catch(() => null);
    await fetchVersion();
    await fetchVersion();
    expect(evenements).toEqual(["panne", "retablie"]);
  });

  it("gives up a read after the timeout, as a panne, and frees the slot", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const lecture = fetchAppState().catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(DELAI_LECTURE_MS + 10);
    const erreur = await lecture;
    expect(estPanne(erreur)).toBe(true);
    expect((erreur as Error).message).toMatch(/délai dépassé/);
    expect(nombreLecturesEnVol()).toBe(0);
  });

  it("never puts a timeout on a write (long operations such as sending the teachers' mails)", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(reponseJson({ session_id: "s1" })));
    await movePlacement("s1", { week: 1, day: 0, slot: 0 });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBeUndefined();
  });

  it("fetchSante: a 503 `degraded` is the server's answer, not a panne", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: "degraded", version: "1.0.0", detail: "Config illisible." }), { status: 503 }),
    );
    await expect(fetchSante()).resolves.toEqual({ status: "degraded", detail: "Config illisible." });
    expect(evenements).toEqual([]);
  });
});
