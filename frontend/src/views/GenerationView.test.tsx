/**
 * Nouveau semestre (16/11/2026) — lancer une génération, la suivre, lire
 * son résultat, l'arrêter.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GenerationView } from "./GenerationView";

const GROUPES = [
  {
    cle: "odd",
    libelle: "Semestre impair",
    semestres: ["S1", "S3", "S5"],
    parametres: { semestre_group: "odd", tentatives: 6, heures: 4, weeks: 24, fi_max_week: 18, num_workers: 3 },
  },
  {
    cle: "even",
    libelle: "Semestre pair",
    semestres: ["S2", "S4", "S6"],
    parametres: { semestre_group: "even", tentatives: 6, heures: 4, weeks: null, fi_max_week: null, num_workers: 3 },
  },
];

const EN_COURS = {
  id: "20261116-171750-87bc",
  statut: "en_cours",
  parametres: GROUPES[1].parametres,
  cree_le: "2026-11-16T17:17:50+00:00",
  cree_par: "admin@exemple.fr",
  etapes: [
    { cle: "preparation", libelle: "Préparer les séances", statut: "faite", detail: "1941 séances, 55 modules" },
    { cle: "calcul", libelle: "Calculer l'emploi du temps", statut: "en_cours" },
    { cle: "enregistrement", libelle: "Enregistrer le brouillon", statut: "a_faire" },
  ],
  tentatives: [{ numero: 1, graine: 2027, secondes: 1800, placees: 1890, manquantes: 12, gardee: true }],
  tentative_en_cours: { numero: 2, graine: 3040, debut: "2026-11-16T17:50:00+00:00" },
  meilleur: { numero: 1, placees: 1890, manquantes: 12 },
  resultat: null,
  run_id: null,
  erreur: null,
  annulation_demandee: false,
  vivante: true,
  journal: ["=== Calculer l'emploi du temps", "  tentative 2 (graine 3040)"],
};

const TERMINEE = {
  ...EN_COURS,
  id: "20261110-090000-aaaa",
  statut: "terminee",
  cree_le: "2026-11-10T09:00:00+00:00",
  tentative_en_cours: null,
  verification: {
    resume: { erreurs: 0, alertes: 1 },
    constats: [{ severite: "alerte", controle: "donnees.sae", message: "15 SAE sans dates." }],
  },
  resultat: {
    statut_solveur: "FEASIBLE",
    placees: 1899,
    a_placer: 1902,
    completees: 9,
    sans_salle: 0,
    non_placees: [
      { session_id: "S2-R201-TD-3-A", course_code: "R2.01", raison: "Aucun créneau libre pour l'enseignant." },
    ],
    motifs: [{ raison: "Aucun créneau libre pour l'enseignant.", nombre: 1 }],
  },
  run_id: 16,
  vivante: false,
  journal: [],
};

const RESUME_TERMINEE = {
  id: TERMINEE.id,
  statut: "terminee",
  semestre_group: "even",
  cree_le: TERMINEE.cree_le,
  cree_par: "admin@exemple.fr",
  termine_le: "2026-11-10T12:00:00+00:00",
  run_id: 16,
  placees: 1899,
  a_placer: 1902,
  non_placees: 1,
};

const BROUILLON = {
  run_id: 16,
  groupe: "even",
  libelle: "Semestre pair (S2, S4, S6)",
  cree_le: "2026-11-10T11:00:00+00:00",
  placements: 1899,
};

function stubFetch(
  options: { active?: unknown; generations?: unknown[]; brouillons?: unknown[]; enService?: unknown[] } = {},
) {
  const appels: { url: string; init?: RequestInit }[] = [];
  let active = options.active ?? null;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      const chemin = String(url);
      if (chemin.includes("/brouillons")) {
        if (init?.method === "DELETE") {
          options.brouillons = [];
          return Promise.resolve({ ok: true, json: async () => ({ supprime: 16 }) });
        }
        if (init?.method === "POST" && chemin.endsWith("/publier")) {
          options.brouillons = [];
          return Promise.resolve({
            ok: true,
            json: async () => ({ publie: 16, groupe: "even", libelle: BROUILLON.libelle, remplace: null }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({ brouillons: options.brouillons ?? [], en_service: options.enService ?? [] }),
        });
      }
      if (init?.method === "POST" && chemin.endsWith("/annuler")) {
        active = { ...EN_COURS, annulation_demandee: true };
        return Promise.resolve({ ok: true, json: async () => active });
      }
      if (init?.method === "POST") {
        active = EN_COURS;
        return Promise.resolve({ ok: true, status: 201, json: async () => EN_COURS });
      }
      if (chemin.includes(`/generations/${TERMINEE.id}`)) {
        return Promise.resolve({ ok: true, json: async () => TERMINEE });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ groupes: GROUPES, coeurs: 4, active, generations: options.generations ?? [] }),
      });
    }),
  );
  return appels;
}

describe("GenerationView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("demande le semestre avant d'autoriser le lancement, puis lance", async () => {
    const appels = stubFetch();
    render(<GenerationView />);

    const bouton = await screen.findByRole("button", { name: /Générer l’emploi du temps/ });
    expect(bouton).toBeDisabled();
    expect(screen.getByText("Aucune génération pour l’instant.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /Semestre pair/ }));
    expect(bouton).toBeEnabled();
    expect(screen.getByText(/jusqu’à/)).toHaveTextContent("4 h");
    fireEvent.click(bouton);

    await screen.findByRole("heading", { name: /Génération en cours : Semestre pair \(S2, S4, S6\)/ });
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toMatch(/\/generations$/);
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({ semestre_group: "even" });
  });

  it("montre l'avancement d'une génération en cours et permet de l'arrêter", async () => {
    const appels = stubFetch({ active: EN_COURS });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<GenerationView />);

    await screen.findByRole("heading", { name: /Génération en cours/ });
    expect(screen.getByText(/Essai 2 sur 6/)).toHaveTextContent("1 890 séances placées");
    expect(screen.getByText("1941 séances, 55 modules")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Générer/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Arrêter" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Arrêt en cours…" })).toBeDisabled());
    expect(appels.some((a) => a.url.endsWith(`/generations/${EN_COURS.id}/annuler`))).toBe(true);
  });

  it("prévient quand le serveur a redémarré pendant le calcul", async () => {
    stubFetch({ active: { ...EN_COURS, vivante: false } });
    render(<GenerationView />);

    expect(await screen.findByText(/La génération reprend toute seule/)).toBeInTheDocument();
  });

  it("affiche le résultat de la dernière génération terminée", async () => {
    stubFetch({ generations: [RESUME_TERMINEE] });
    render(<GenerationView />);

    const resultat = await screen.findByRole("region", { name: /Semestre pair \(S2, S4, S6\)/ });
    expect(within(resultat).getByText("1 899")).toBeInTheDocument();
    expect(within(resultat).getByText(/brouillon n° 16/)).toBeInTheDocument();
    expect(within(resultat).getByText("1 séance à placer à la main")).toBeInTheDocument();
    expect(within(resultat).getByText("R2.01")).toBeInTheDocument();
    expect(within(resultat).getByText("15 SAE sans dates.")).toBeInTheDocument();

    const ligne = screen.getByRole("row", { name: /10 novembre/ });
    expect(within(ligne).getByText("1 899 sur 1 902")).toBeInTheDocument();
  });

  it("propose de relire ou de supprimer un brouillon", async () => {
    const appels = stubFetch({ generations: [RESUME_TERMINEE], brouillons: [BROUILLON] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onRelire = vi.fn();
    render(<GenerationView onRelire={onRelire} />);

    const carte = await screen.findByRole("region", { name: /Brouillons/ });
    const ligne = within(carte).getByRole("row", { name: /n° 16/ });
    expect(within(ligne).getByText("1 899")).toBeInTheDocument();

    fireEvent.click(within(ligne).getByRole("button", { name: "Relire" }));
    expect(onRelire).toHaveBeenCalledWith(16);

    fireEvent.click(within(ligne).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: /Brouillons/ })).not.toBeInTheDocument());
    expect(appels.some((a) => a.init?.method === "DELETE" && a.url.endsWith("/brouillons/16"))).toBe(true);
  });

  it("publie un brouillon après confirmation et recharge le planning", async () => {
    const appels = stubFetch({ generations: [RESUME_TERMINEE], brouillons: [BROUILLON] });
    const confirmer = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onPublie = vi.fn();
    render(<GenerationView onPublie={onPublie} />);

    const carte = await screen.findByRole("region", { name: /Brouillons/ });
    fireEvent.click(within(carte).getByRole("button", { name: "Publier" }));

    await waitFor(() => expect(onPublie).toHaveBeenCalled());
    expect(confirmer.mock.calls[0][0]).toMatch(/Le semestre en cours ne change pas/);
    expect(appels.some((a) => a.init?.method === "POST" && a.url.endsWith("/brouillons/16/publier"))).toBe(true);
    expect(await screen.findByText(/en service\. Choisissez ce semestre/)).toBeInTheDocument();
  });

  it("ne propose pas de publier un brouillon du semestre en cours", async () => {
    stubFetch({
      generations: [RESUME_TERMINEE],
      brouillons: [BROUILLON],
      enService: [{ ...BROUILLON, run_id: 12, affiche: false, en_cours: true }],
    });
    render(<GenerationView />);

    const carte = await screen.findByRole("region", { name: /Brouillons/ });

    expect(within(carte).getByRole("button", { name: "Publier" })).toBeDisabled();
  });
});
