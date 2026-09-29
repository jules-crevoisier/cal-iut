/**
 * Un refus (401/403) sur `/app-state` ne se retente jamais tout seul
 * (anti-aspiration, 29/09/2026). Avant, il tombait dans l'état « échec »,
 * retenté toutes les 15 s même derrière l'écran de connexion : un onglet
 * dont la session avait expiré envoyait un 401 toutes les 15 s sans fin —
 * de quoi faire bannir l'IP d'un vrai utilisateur par le bannissement sur
 * refus répétés du serveur (≥ 30 refus en 10 min).
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { reinitialiserLiaison } from "./api/client";

const MOI = { id: 1, email: "edit@x.test", role: "edit", status: "active" };

function json(corps: unknown, status = 200): Response {
  return new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
}

let refus = 401;

function installerFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const chemin = new URL(String(url), "http://localhost").pathname;
      if (chemin === "/auth/me") return Promise.resolve(json(MOI));
      if (chemin === "/app-state") return Promise.resolve(json({ detail: "Refusé." }, refus));
      if (chemin === "/api/v1/version") return Promise.resolve(json({ revision: 1, modifie_le: "x" }));
      if (chemin === "/health") return Promise.resolve(json({ status: "ok", version: "1.0.0" }));
      if (chemin === "/timetable") return Promise.resolve(json({ placements: [], status: "ok" }));
      if (chemin === "/controles/doublons") return Promise.resolve(json({ doublons: [] }));
      if (chemin === "/meta") return Promise.resolve(json({ groups: [], rooms: [], parcours: [], semestres: [], years: [] }));
      return Promise.resolve(json({}));
    }),
  );
}

function appelsAppState(): number {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => new URL(String(url), "http://localhost").pathname === "/app-state").length;
}

async function laisserPasser(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

describe("App — un refus d'accès n'est pas retenté en boucle", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reinitialiserLiaison();
    localStorage.setItem("cal-iut:preferences:v1", JSON.stringify({ couleursParMatiere: false, repondu: true }));
    installerFetch();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    reinitialiserLiaison();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("session expirée entre /auth/me et /app-state : écran de connexion, plus aucun /app-state", async () => {
    refus = 401;
    window.history.replaceState(null, "", "/#vue=reference");
    render(<App />);
    expect(await screen.findByLabelText(/mot de passe/i)).toBeInTheDocument();
    const avant = appelsAppState();
    expect(avant).toBe(1);
    // Dix minutes d'onglet ouvert sur l'écran de connexion.
    for (let i = 0; i < 40; i += 1) await laisserPasser(15_000);
    expect(appelsAppState()).toBe(avant);
  });

  it("lien public refusé (403) : le dit, sans relancer la requête", async () => {
    refus = 403;
    window.history.replaceState(null, "", "/#mode=prof&prof=KBR&t=KBR");
    render(<App />);
    expect(await screen.findByText("Accès au planning refusé.")).toBeInTheDocument();
    expect(screen.queryByText(/Nouvelle tentative automatique/)).not.toBeInTheDocument();
    const avant = appelsAppState();
    for (let i = 0; i < 40; i += 1) await laisserPasser(15_000);
    expect(appelsAppState()).toBe(avant);
  });
});
