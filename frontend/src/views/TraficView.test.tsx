/**
 * Écran « Trafic » (anti-aspiration, 29/09/2026) — état du mode, tuiles,
 * plus gros clients, modale « Bloquer… », liste des blocages.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Blocage, TraficResponse } from "../api/client";
import { TraficView } from "./TraficView";

const BUDGETS = [
  { categorie: "public", nombre: 120, periode_s: 60, rafale: 120, description: "Lien public" },
  { categorie: "appli", nombre: 600, periode_s: 60, rafale: 300, description: "Compte" },
];

function trafic(partiel: Partial<TraficResponse> = {}): TraficResponse {
  return {
    mode: "observe",
    variable: "CAL_IUT_ANTI_ASPIRATION",
    comptage_actif: true,
    fenetre: "1h",
    genere_le: "2026-09-29T10:00:00+00:00",
    budgets: BUDGETS,
    bannissement: { seuil: 30, fenetre_s: 600, duree_s: 3600 },
    exemptes: [],
    resume: { requetes: 1520, clients: 2, depassements: 45, refus_403: 0, ip_bloquees: 0 },
    clients: [
      {
        ip: "203.0.113.66",
        requetes: 1500,
        requetes_15min: 380,
        requetes_1h: 1500,
        requetes_24h: 30000,
        part_publique: 1,
        depassements: 45,
        refus_403: 0,
        user_agent: "python-requests/2.31",
        user_agents_distincts: 1,
        chemins: [{ chemin: "/app-state", nb: 1500 }],
        categorie: "public",
        compte_id: null,
        compte_email: null,
        liens_distincts: 40,
        dernier_passage: new Date().toISOString(),
        blocage_id: null,
      },
      {
        ip: "198.51.100.4",
        requetes: 20,
        requetes_15min: 5,
        requetes_1h: 20,
        requetes_24h: 90,
        part_publique: 0,
        depassements: 0,
        refus_403: 0,
        user_agent: "Mozilla/5.0 Firefox/130.0",
        user_agents_distincts: 1,
        chemins: [{ chemin: "/placements/S1", nb: 12 }],
        categorie: "appli",
        compte_id: 3,
        compte_email: "admin@example.test",
        liens_distincts: 0,
        dernier_passage: new Date().toISOString(),
        blocage_id: null,
      },
    ],
    ...partiel,
  };
}

const BLOCAGE: Blocage = {
  id: "b1",
  type: "cidr",
  valeur: "192.0.2.0/24",
  motif: "hébergeur",
  auteur: "admin@example.test",
  cree_le: "2026-09-29T09:00:00+00:00",
  expire_le: null,
  automatique: false,
};

interface Etat {
  trafic: TraficResponse;
  blocages: Blocage[];
  post?: (corps: Record<string, unknown>) => { status: number; body: unknown };
}

function stubFetch(etat: Etat) {
  const appels: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      const u = String(url);
      const repondre = (status: number, body: unknown) =>
        Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => body });
      if (init?.method === "POST" && u.includes("/admin/blocages")) {
        const corps = JSON.parse(String(init.body)) as Record<string, unknown>;
        const r = etat.post
          ? etat.post(corps)
          : { status: 201, body: { ...BLOCAGE, id: "b2", type: corps.type, valeur: corps.valeur, motif: corps.motif, expire_le: null } };
        if (r.status === 201) etat.blocages = [...etat.blocages, r.body as Blocage];
        return repondre(r.status, r.body);
      }
      if (init?.method === "DELETE") {
        etat.blocages = etat.blocages.filter((b) => !u.endsWith(`/${b.id}`));
        return repondre(200, { ok: true });
      }
      if (u.includes("/admin/blocages")) return repondre(200, { mode: etat.trafic.mode, blocages: etat.blocages });
      return repondre(200, etat.trafic);
    }),
  );
  return appels;
}

describe("TraficView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("mode désactivé : le dit, donne la variable, ne montre aucun chiffre", async () => {
    stubFetch({ trafic: trafic({ mode: "off", comptage_actif: false, clients: [] }), blocages: [BLOCAGE] });
    render(<TraficView />);

    const etat = await screen.findByText("Désactivé");
    expect(etat).toHaveClass("pill", "dot");
    expect(screen.getByText(/CAL_IUT_ANTI_ASPIRATION=observe/)).toBeInTheDocument();
    expect(screen.getByText(/Comptage désactivé : le serveur ne compte rien/)).toBeInTheDocument();
    const tuiles = screen.getByRole("region", { name: "Sommaire du trafic" });
    expect(within(tuiles).getAllByText("—")).toHaveLength(3);
    // La liste de blocage se prépare quand même.
    expect(screen.getByText("préparés : s'appliqueront à l'activation")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /192\.0\.2\.0\/24/ })).toBeInTheDocument();
  });

  it("observation : tuiles et plus gros clients", async () => {
    stubFetch({ trafic: trafic(), blocages: [] });
    render(<TraficView />);

    expect(await screen.findByText("Observation")).toBeInTheDocument();
    const tuiles = screen.getByRole("region", { name: "Sommaire du trafic" });
    expect(within(tuiles).getByText("1 520")).toBeInTheDocument();
    expect(within(tuiles).getByText("au-delà du budget : auraient été refusées")).toBeInTheDocument();

    const ligne = screen.getByRole("row", { name: /203\.0\.113\.66/ });
    expect(within(ligne).getByText("380")).toBeInTheDocument();
    expect(within(ligne).getByText("30 000")).toBeInTheDocument();
    expect(within(ligne).getByText("100 %")).toBeInTheDocument();
    expect(within(ligne).getByText("python-requests/2.31")).toBeInTheDocument();
    expect(within(ligne).getByText(/40 liens différents/)).toBeInTheDocument();
    // Un compte connecté apparaît sous son adresse.
    expect(screen.getByRole("row", { name: /admin@example\.test/ })).toBeInTheDocument();
    expect(screen.getByText(/Lien public 120\/min/)).toBeInTheDocument();
  });

  it("filtre les clients par User-Agent", async () => {
    stubFetch({ trafic: trafic(), blocages: [] });
    render(<TraficView />);
    await screen.findByText("Observation");

    fireEvent.change(screen.getByRole("searchbox", { name: "Filtrer les clients" }), { target: { value: "python" } });
    expect(screen.getByRole("row", { name: /203\.0\.113\.66/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /198\.51\.100\.4/ })).not.toBeInTheDocument();
  });

  it("change de fenêtre de temps", async () => {
    const appels = stubFetch({ trafic: trafic(), blocages: [] });
    render(<TraficView />);
    await screen.findByText("Observation");

    fireEvent.click(screen.getByRole("tab", { name: "24 h" }));
    await waitFor(() => expect(appels.some((a) => a.url.includes("fenetre=24h"))).toBe(true));
  });

  it("bloque une IP depuis sa ligne, avec durée et motif", async () => {
    const etat: Etat = { trafic: trafic(), blocages: [] };
    const appels = stubFetch(etat);
    render(<TraficView />);
    await screen.findByText("Observation");

    fireEvent.click(screen.getByRole("button", { name: "Bloquer 203.0.113.66…" }));
    const modale = screen.getByRole("dialog", { name: "Bloquer" });
    expect(within(modale).getByDisplayValue("203.0.113.66")).toBeInTheDocument();
    fireEvent.click(within(modale).getByRole("radio", { name: "7 jours" }));
    fireEvent.change(within(modale).getByLabelText("Motif"), { target: { value: "aspire /app-state" } });
    fireEvent.click(within(modale).getByRole("button", { name: "Bloquer" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const post = appels.find((a) => a.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      type: "ip",
      valeur: "203.0.113.66",
      motif: "aspire /app-state",
      duree: "7j",
      forcer: false,
    });
    expect(await screen.findByText(/203\.0\.113\.66 bloquée/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Débloquer 203.0.113.66" })).toBeInTheDocument();
  });

  it("passer au User-Agent reprend celui de la ligne", async () => {
    const etat: Etat = { trafic: trafic(), blocages: [] };
    stubFetch(etat);
    render(<TraficView />);
    await screen.findByText("Observation");

    fireEvent.click(screen.getByRole("button", { name: "Bloquer 203.0.113.66…" }));
    const modale = screen.getByRole("dialog", { name: "Bloquer" });
    fireEvent.change(within(modale).getByLabelText("Quoi"), { target: { value: "user_agent" } });
    expect(within(modale).getByDisplayValue("python-requests/2.31")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("se bloquer soi-même demande une confirmation explicite", async () => {
    let tentatives = 0;
    const etat: Etat = {
      trafic: trafic(),
      blocages: [],
      post: (corps) => {
        tentatives += 1;
        if (!corps.forcer) return { status: 409, body: { message: "Ce blocage vous viserait vous-même." } };
        return { status: 201, body: { ...BLOCAGE, id: "b3", type: "ip", valeur: String(corps.valeur) } };
      },
    };
    stubFetch(etat);
    render(<TraficView />);
    await screen.findByText("Observation");

    fireEvent.click(screen.getByRole("button", { name: "Bloquer une adresse…" }));
    const modale = screen.getByRole("dialog", { name: "Bloquer" });
    fireEvent.change(within(modale).getByLabelText("Adresse"), { target: { value: "198.51.100.4" } });
    fireEvent.click(within(modale).getByRole("button", { name: "Bloquer" }));
    expect(await within(modale).findByText("Ce blocage vous viserait vous-même.")).toBeInTheDocument();
    fireEvent.click(within(modale).getByRole("button", { name: "Bloquer quand même" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(tentatives).toBe(2);
  });

  it("débloque", async () => {
    const etat: Etat = { trafic: trafic(), blocages: [BLOCAGE] };
    stubFetch(etat);
    render(<TraficView />);
    await screen.findByText("Observation");

    fireEvent.click(screen.getByRole("button", { name: "Débloquer 192.0.2.0/24" }));
    expect(await screen.findByText(/192\.0\.2\.0\/24 débloquée/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Aucun blocage.")).toBeInTheDocument());
  });

  it("une IP déjà bloquée n'a plus de bouton « Bloquer… »", async () => {
    const t = trafic({ mode: "enforce" });
    t.clients[0].blocage_id = "b9";
    stubFetch({ trafic: t, blocages: [] });
    render(<TraficView />);

    expect(await screen.findByText("Blocage actif")).toBeInTheDocument();
    expect(screen.getByText(/bannie 1 h/)).toBeInTheDocument();
    const ligne = screen.getByRole("row", { name: /203\.0\.113\.66/ });
    expect(within(ligne).getByText("bloqué")).toBeInTheDocument();
    expect(within(ligne).queryByRole("button")).not.toBeInTheDocument();
  });

  it("affiche l'erreur de chargement et permet de réessayer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 403, statusText: "", json: async () => ({ detail: "Permissions insuffisantes pour cette action." }) })),
    );
    render(<TraficView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Permissions insuffisantes");
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeInTheDocument();
  });
});
