/**
 * Nouveau semestre (16/11/2026) — récupérer la maquette et la progression du
 * semestre choisi depuis MMI Prévi.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GenerationView } from "./GenerationView";

const PARAMETRES = { tentatives: 6, heures: 4, weeks: null, fi_max_week: null, num_workers: 3 };
const MMI_PREVI = {
  origine: "mmi_previ",
  recuperee_le: "2026-11-16T20:12:00+01:00",
  par: "admin@exemple.fr",
  modules: 63,
  avec_progression: 12,
};

function stubFetch(options: { configure?: boolean; echec?: string } = {}) {
  const appels: { url: string; init?: RequestInit }[] = [];
  let sourcePair: unknown = { origine: "copie_livree" };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const chemin = String(url);
      appels.push({ url: chemin, init });
      if (chemin.includes("/brouillons")) {
        return Promise.resolve({ ok: true, json: async () => ({ brouillons: [], en_service: [] }) });
      }
      if (chemin.includes("/generations/sources/mmi-previ")) {
        if (options.echec) {
          return Promise.resolve({ ok: false, status: 502, json: async () => ({ detail: options.echec }) });
        }
        if (init?.method === "DELETE") {
          sourcePair = { origine: "copie_livree" };
          return Promise.resolve({ ok: true, json: async () => ({ semestre_group: "even", source: sourcePair }) });
        }
        sourcePair = MMI_PREVI;
        return Promise.resolve({
          ok: true,
          json: async () => ({
            semestre_group: "even",
            source: MMI_PREVI,
            differences: {
              ajoutes: [{ code: "WR499", nom: "Module nouveau", semestre: "S4", parcours: "BUT2-DEV-FI" }],
              retires: [],
              modifies: [
                { code: "WR201", nom: "Module modifié", semestre: "S2", parcours: "BUT1" },
                { code: "WR202", nom: "Autre module", semestre: "S2", parcours: "BUT1" },
              ],
            },
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({
          groupes: [
            {
              cle: "odd",
              libelle: "Semestre impair",
              semestres: ["S1", "S3", "S5"],
              parametres: { ...PARAMETRES, semestre_group: "odd" },
              source: { origine: "copie_livree" },
            },
            {
              cle: "even",
              libelle: "Semestre pair",
              semestres: ["S2", "S4", "S6"],
              parametres: { ...PARAMETRES, semestre_group: "even" },
              source: sourcePair,
            },
          ],
          mmi_previ_configure: options.configure ?? true,
          coeurs: 4,
          active: null,
          generations: [],
        }),
      });
    }),
  );
  return appels;
}

describe("GenerationView — maquette depuis MMI Prévi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("récupère la maquette du semestre choisi et dit ce qui change", async () => {
    const appels = stubFetch();
    render(<GenerationView />);

    fireEvent.click(await screen.findByRole("radio", { name: /Semestre pair/ }));
    expect(screen.getByText(/Copie livrée avec l’application/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Récupérer depuis MMI Prévi" }));

    await screen.findByRole("button", { name: "Mettre à jour depuis MMI Prévi" });
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toMatch(/\/generations\/sources\/mmi-previ$/);
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({ semestre_group: "even" });

    expect(screen.getByText(/Récupérées depuis/)).toHaveTextContent("63 modules, dont 12 avec un ordre des séances défini");
    expect(screen.getByText(/Par rapport à la maquette utilisée jusqu’ici/)).toHaveTextContent(
      "1 module en plus, 0 en moins, 2 dont les volumes ou le responsable changent",
    );
    expect(screen.getByText("WR499")).toBeInTheDocument();
  });

  it("revient à la copie livrée après confirmation", async () => {
    const appels = stubFetch();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<GenerationView />);

    fireEvent.click(await screen.findByRole("radio", { name: /Semestre pair/ }));
    fireEvent.click(screen.getByRole("button", { name: "Récupérer depuis MMI Prévi" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revenir à la copie livrée" }));

    await screen.findByRole("button", { name: "Récupérer depuis MMI Prévi" });
    expect(appels.some((a) => a.init?.method === "DELETE" && a.url.endsWith("/sources/mmi-previ/even"))).toBe(true);
    expect(screen.queryByText(/Par rapport à la maquette/)).not.toBeInTheDocument();
  });

  it("sans jeton sur le serveur, le bouton est grisé et l'écran dit pourquoi", async () => {
    stubFetch({ configure: false });
    render(<GenerationView />);

    fireEvent.click(await screen.findByRole("radio", { name: /Semestre pair/ }));
    expect(screen.getByRole("button", { name: "Récupérer depuis MMI Prévi" })).toBeDisabled();
    expect(screen.getByText(/CAL_IUT_MMI_PREVI_JETON/)).toBeInTheDocument();
  });

  it("affiche le refus de MMI Prévi tel que le serveur l'explique", async () => {
    stubFetch({ echec: "MMI Prévi refuse le jeton d'accès : il est invalide, révoqué ou expiré." });
    render(<GenerationView />);

    fireEvent.click(await screen.findByRole("radio", { name: /Semestre pair/ }));
    fireEvent.click(screen.getByRole("button", { name: "Récupérer depuis MMI Prévi" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("refuse le jeton"));
    expect(screen.getByRole("button", { name: "Récupérer depuis MMI Prévi" })).toBeEnabled();
  });
});
