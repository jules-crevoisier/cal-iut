/**
 * « À régler avant de générer » (lot 5, 16/11/2026) : la liste des points
 * relevés dans les données s'affiche dès que le semestre est choisi, et une
 * erreur empêche de lancer le calcul.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GenerationView } from "./GenerationView";

const GROUPES = [
  {
    cle: "even",
    libelle: "Semestre pair",
    semestres: ["S2", "S4", "S6"],
    parametres: { semestre_group: "even", tentatives: 6, heures: 4, weeks: null, fi_max_week: null, num_workers: 3 },
    source: { origine: "copie_livree" },
  },
];

const ALERTE = {
  severite: "alerte",
  controle: "donnees.sae_sans_dates",
  message: "15 SAE ont des heures mais aucune date.",
  quoi_faire: "Renseigner les dates dans « DATES SAE ».",
  details: ["WS201 (S2) : 7 séance(s), aucune date"],
  bloquant: false,
};
const ERREUR = {
  severite: "erreur",
  controle: "capacite.enseignant_impossible",
  message: "JBA : 120 créneaux à assurer pour 90 créneaux déclarés.",
  quoi_faire: "Élargir ses disponibilités.",
  details: [],
  bloquant: true,
};

function stubFetch(verification: () => Promise<unknown>) {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const chemin = String(url);
      appels.push({ url: chemin, init });
      if (chemin.includes("/brouillons")) {
        return Promise.resolve({ ok: true, json: async () => ({ brouillons: [], en_service: [] }) });
      }
      if (chemin.includes("/generations/verification/")) return verification();
      return Promise.resolve({
        ok: true,
        json: async () => ({ groupes: GROUPES, coeurs: 4, active: null, generations: [] }),
      });
    }),
  );
  return appels;
}

const reponse = (constats: unknown[]) => () =>
  Promise.resolve({
    ok: true,
    json: async () => ({
      semestre_group: "even",
      seances: 1941,
      bloquant: constats.some((c) => (c as { bloquant: boolean }).bloquant),
      constats,
    }),
  });

async function choisirLePair() {
  render(<GenerationView />);
  fireEvent.click(await screen.findByRole("radio", { name: /Semestre pair/ }));
}

afterEach(() => vi.unstubAllGlobals());

describe("À régler avant de générer", () => {
  it("vérifie les données du semestre choisi, pas avant", async () => {
    const appels = stubFetch(reponse([]));
    render(<GenerationView />);
    await screen.findByRole("radio", { name: /Semestre pair/ });
    expect(appels.some((a) => a.url.includes("/verification/"))).toBe(false);
    fireEvent.click(screen.getByRole("radio", { name: /Semestre pair/ }));
    expect(await screen.findByText(/rien à régler avant de générer/)).toBeTruthy();
    expect(appels.filter((a) => a.url.endsWith("/generations/verification/even"))).toHaveLength(1);
    expect((screen.getByRole("button", { name: /Générer l’emploi du temps/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("une alerte s'affiche sans empêcher de générer", async () => {
    stubFetch(reponse([ALERTE]));
    await choisirLePair();
    const bloc = await screen.findByRole("region", { name: "À vérifier avant de générer" });
    expect(within(bloc).getByText(ALERTE.message)).toBeTruthy();
    expect(within(bloc).getByText(ALERTE.quoi_faire)).toBeTruthy();
    expect(within(bloc).getByText("WS201 (S2) : 7 séance(s), aucune date")).toBeTruthy();
    expect((screen.getByRole("button", { name: /Générer l’emploi du temps/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("une erreur bloque le bouton et passe en tête de liste", async () => {
    const appels = stubFetch(reponse([ERREUR, ALERTE]));
    await choisirLePair();
    const bloc = await screen.findByRole("region", { name: "À régler avant de générer" });
    const lignes = within(bloc).getAllByText(/À régler|À vérifier/, { selector: ".pill" });
    expect(lignes.map((l) => l.textContent)).toEqual(["À régler", "À vérifier"]);
    const bouton = screen.getByRole("button", { name: /Générer l’emploi du temps/ }) as HTMLButtonElement;
    expect(bouton.disabled).toBe(true);
    expect(screen.getByText(/Réglez d’abord les points ci-dessus/)).toBeTruthy();
    fireEvent.click(bouton);
    expect(appels.some((a) => a.init?.method === "POST")).toBe(false);
  });

  it("si la vérification échoue, le lancement reste possible (le serveur recontrôle)", async () => {
    stubFetch(() => Promise.resolve({ ok: false, status: 500, statusText: "Erreur", json: async () => ({ detail: "panne" }) }));
    await choisirLePair();
    await waitFor(() =>
      expect((screen.getByRole("button", { name: /Générer l’emploi du temps/ }) as HTMLButtonElement).disabled).toBe(false),
    );
    expect(screen.queryByRole("region", { name: /avant de générer/ })).toBeNull();
  });
});
