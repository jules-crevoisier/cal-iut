/**
 * Pannes masquées (audit du 29/09/2026, P1-13) : une coupure réseau
 * affichait l'écran de connexion à quelqu'un de bien connecté, ou « Aucun
 * planning résolu » alors que le planning existait. Désormais : bandeau
 * « Serveur injoignable » avec « Réessayer », le dernier état reste affiché ;
 * seul un vrai 401 ramène à l'écran de connexion.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { reinitialiserLiaison } from "./api/client";
import { emptyPayload } from "./test/payloadFixture";

type Regle = (chemin: string) => Response | Promise<Response> | "panne" | undefined;

const MOI_ADMIN = { id: 1, email: "admin@x.test", role: "admin", status: "active" };

function json(corps: unknown, status = 200): Response {
  return new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
}

function defaut(chemin: string): Response {
  if (chemin === "/auth/me") return json(MOI_ADMIN);
  if (chemin === "/app-state") return json(emptyPayload());
  if (chemin === "/timetable") return json({ placements: [], status: "ok" });
  if (chemin === "/meta") return json({ groups: [], rooms: [], parcours: [], semestres: [], years: [] });
  if (chemin === "/api/v1/version") return json({ revision: 1, modifie_le: "x" });
  if (chemin === "/health") return json({ status: "ok", version: "1.0.0" });
  if (chemin === "/controles/doublons") return json({ doublons: [] });
  return json({});
}

let regle: Regle = () => undefined;

function installerFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const chemin = new URL(String(url), "http://localhost").pathname;
      const r = regle(chemin);
      if (r === "panne") return Promise.reject(new TypeError("Failed to fetch"));
      return Promise.resolve(r ?? defaut(chemin));
    }),
  );
}

function chemins(): string[] {
  return vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost").pathname);
}

describe("App — pannes du serveur", () => {
  beforeEach(() => {
    reinitialiserLiaison();
    localStorage.setItem("cal-iut:preferences:v1", JSON.stringify({ couleursParMatiere: false, repondu: true }));
    window.history.replaceState(null, "", "/#vue=reference");
    regle = () => undefined;
    installerFetch();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    reinitialiserLiaison();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("does NOT show the login screen when /auth/me cannot be reached — it shows the outage banner", async () => {
    regle = (c) => (c === "/auth/me" ? "panne" : undefined);
    render(<App />);
    expect(await screen.findByText(/Serveur injoignable — nouvelle tentative/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/mot de passe/i)).not.toBeInTheDocument();

    // Le serveur revient : « Réessayer » relance la question et ouvre l'application.
    regle = () => undefined;
    fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    await waitFor(() => expect(screen.queryByText(/Serveur injoignable/)).not.toBeInTheDocument());
    await waitFor(() => expect(chemins()).toContain("/app-state"));
  });

  it("shows the login screen on a real 401", async () => {
    regle = (c) => (c === "/auth/me" ? json({ detail: "Authentification requise." }, 401) : undefined);
    render(<App />);
    expect(await screen.findByLabelText(/mot de passe/i)).toBeInTheDocument();
    expect(screen.queryByText(/Serveur injoignable/)).not.toBeInTheDocument();
  });

  it("does not present an unreachable server as “no planning”", async () => {
    regle = (c) => (c === "/auth/me" ? undefined : "panne");
    render(<App />);
    expect(await screen.findByText(/Serveur injoignable — nouvelle tentative/)).toBeInTheDocument();
    expect(screen.queryByText("Aucun planning résolu.")).not.toBeInTheDocument();
    expect(screen.getByText(/Le planning n'a pas pu être chargé/)).toBeInTheDocument();
  });

  it("says why the planning is missing when /app-state alone fails, without hammering the server", async () => {
    regle = (c) => (c === "/app-state" ? "panne" : undefined);
    render(<App />);
    expect(await screen.findByText(/Le planning n'a pas pu être chargé/)).toBeInTheDocument();
    expect(screen.queryByText("Aucun planning résolu.")).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 100));
    expect(chemins().filter((c) => c === "/app-state").length).toBeLessThanOrEqual(3);
  });

  it("still says “no planning” when the server answers 404", async () => {
    regle = (c) => (c === "/app-state" ? json({ detail: "Aucun planning résolu" }, 404) : undefined);
    render(<App />);
    expect(await screen.findByText("Aucun planning résolu.")).toBeInTheDocument();
    expect(screen.queryByText(/Serveur injoignable/)).not.toBeInTheDocument();
  });

  it("keeps the last planning on screen when a later reload fails", async () => {
    render(<App />);
    // Vue Référence chargée (le libellé vient de `PageHeader` + payload).
    await waitFor(() => expect(chemins()).toContain("/app-state"));
    await waitFor(() => expect(screen.queryByText("Chargement du planning…")).not.toBeInTheDocument());

    regle = () => "panne";
    // Un sondage de révision qui échoue suffit à déclencher le bandeau.
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(await screen.findByText(/Serveur injoignable — nouvelle tentative/)).toBeInTheDocument();
    expect(screen.queryByText("Aucun planning résolu.")).not.toBeInTheDocument();
    expect(screen.queryByText(/Le planning n'a pas pu être chargé/)).not.toBeInTheDocument();
  });

  it("brings back the login screen when the session expires while working", async () => {
    render(<App />);
    await waitFor(() => expect(chemins()).toContain("/app-state"));
    regle = (c) => (c === "/api/v1/version" ? json({ detail: "Authentification requise." }, 401) : undefined);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(await screen.findByLabelText(/mot de passe/i)).toBeInTheDocument();
  });

  it("tells admins when the server runs without its saved planning (/health 503 degraded)", async () => {
    regle = (c) =>
      c === "/health"
        ? json({ status: "degraded", version: "1.0.0", detail: "Configuration illisible." }, 503)
        : undefined;
    render(<App />);
    expect(await screen.findByText(/Le serveur n'a pas chargé le planning enregistré/)).toBeInTheDocument();
    expect(screen.getByText(/Configuration illisible\./)).toBeInTheDocument();
    expect(screen.queryByText(/Serveur injoignable/)).not.toBeInTheDocument();
  });

  it("does not ask /health for a non-admin account", async () => {
    regle = (c) => (c === "/auth/me" ? json({ ...MOI_ADMIN, role: "edit" }) : undefined);
    render(<App />);
    await waitFor(() => expect(chemins()).toContain("/app-state"));
    await new Promise((r) => setTimeout(r, 30));
    expect(chemins()).not.toContain("/health");
  });
});
