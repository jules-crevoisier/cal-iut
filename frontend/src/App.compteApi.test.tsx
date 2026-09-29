/**
 * Compte « Accès API » (29/09/2026, cf. `api/accounts.py::ROLE_API`) : après
 * connexion, AUCUN écran de données — une page unique « Accès API » (ses
 * clés, la doc de l'API), une navigation réduite à elle, ni recherche
 * (Ctrl K), ni Accueil, ni semaine dans la barre du haut. Et aucun appel aux
 * données : le serveur les refuserait (403), et des refus en boucle ne
 * servent à rien.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { reinitialiserLiaison } from "./api/client";

const MOI = { id: 7, email: "ecran.hall@x.test", role: "api", status: "active" };
const CLES = [
  { id: 3, prefix: "caliut_Q2xh", nom: "Écran du hall", created_at: "2026-09-20T08:00:00+00:00", last_used_at: "2026-09-29T07:55:00+00:00" },
];

function json(corps: unknown, status = 200): Response {
  return new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
}

function chemins(): string[] {
  return vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost").pathname);
}

describe("App — compte « Accès API »", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    reinitialiserLiaison();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const chemin = new URL(String(url), "http://localhost").pathname;
        if (chemin === "/auth/me") return Promise.resolve(json(MOI));
        if (chemin === "/auth/mcp-keys" && init?.method === "POST") {
          return Promise.resolve(
            json({ id: 4, token: "caliut_brut-une-seule-fois", prefix: "caliut_brut", nom: "Script", created_at: "2026-09-29T09:00:00+00:00", last_used_at: null }),
          );
        }
        if (chemin === "/auth/mcp-keys") return Promise.resolve(json({ keys: CLES }));
        return Promise.resolve(json({ detail: "Compte « Accès API »" }, 403));
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    reinitialiserLiaison();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("ouvre la page « Accès API », quelle que soit la vue demandée", async () => {
    window.history.replaceState(null, "", "/#vue=semaine");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Accès API" })).toBeInTheDocument();
    expect(await screen.findByText("Écran du hall")).toBeInTheDocument();
    expect(screen.getByText("caliut_Q2xh")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /générer une clé/i })).toBeInTheDocument();
    const doc = screen.getByRole("link", { name: /documentation de l’api/i });
    expect(doc).toHaveAttribute("href", "/api/v1/docs");
    const exemple = document.querySelector(".cles-exemple pre")?.textContent ?? "";
    expect(exemple).toContain('curl -H "Authorization: Bearer $CLE" http://localhost:3000/api/v1/version');
    expect(exemple).toContain('curl -H "Authorization: Bearer $CLE" http://localhost:3000/api/v1/export');
  });

  it("navigation réduite à cet écran, sans recherche ni semaine", async () => {
    render(<App />);
    await screen.findByText("Écran du hall");
    const nav = screen.getByRole("navigation", { name: /vues/i });
    const boutons = within(nav)
      .getAllByRole("button")
      .filter((b) => b.classList.contains("navbtn"));
    expect(boutons.map((b) => b.textContent)).toEqual(["Accès API"]);
    expect(within(nav).queryByText("Accueil")).not.toBeInTheDocument();
    expect(within(nav).queryByText(/Rechercher/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rechercher" })).not.toBeInTheDocument();
    expect(screen.queryByText(/cette semaine|Semaine \d/)).not.toBeInTheDocument();
    // Ctrl K n'ouvre rien.
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Le menu du compte : rôle, thème, déconnexion — pas d'entrée « Clé API ».
    fireEvent.click(screen.getByRole("button", { name: /compte ecran\.hall@x\.test/i }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("radiogroup", { name: "Thème" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /déconnexion/i })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: /clé api/i })).not.toBeInTheDocument();
    expect(screen.getByText("Accès API", { selector: "small" })).toBeInTheDocument();
  });

  it("ne demande aucune donnée du planning, même avec le temps", async () => {
    render(<App />);
    await screen.findByText("Écran du hall");
    for (let i = 0; i < 12; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(30_000);
      });
    }
    const appeles = new Set(chemins());
    expect([...appeles].sort()).toEqual(["/auth/mcp-keys", "/auth/me"]);
  });

  it("génère une clé nommée, affichée une seule fois, avec l'en-tête à coller", async () => {
    render(<App />);
    await screen.findByText("Écran du hall");
    fireEvent.change(screen.getByLabelText(/nom de la nouvelle clé/i), { target: { value: "Script" } });
    fireEvent.click(screen.getByRole("button", { name: /générer une clé/i }));
    expect(await screen.findByText("caliut_brut-une-seule-fois")).toBeInTheDocument();
    const post = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ nom: "Script" });
    expect(screen.getByRole("button", { name: "Copier l’en-tête" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copier les exemples" })).toBeInTheDocument();
    // Pas de connecteur MCP : ces clés ne l'ouvrent pas.
    expect(screen.queryByRole("button", { name: "Copier le bloc" })).not.toBeInTheDocument();
    expect(screen.queryByText(/serveur MCP/)).not.toBeInTheDocument();
  });
});
