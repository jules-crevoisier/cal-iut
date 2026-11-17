/**
 * Référence → Réglages → années universitaires (17/11/2026).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnneesUniversitaires, periodeLisible } from "./AnneesUniversitaires";

const ORIGINE = {
  label: "2026-2027",
  origine: true,
  en_cours: true,
  rentree: "2026-08-31",
  fin_impair: "2027-01-29",
  debut_pair: "2027-02-01",
  fin: "2027-06-30",
  vacances: [{ nom: "Vacances", debut: "2026-10-26", fin: "2026-10-30" }],
  feries: [{ date: "2026-11-11", nom: "Armistice 1918" }],
  semaines: 38,
  semaines_impair: 19,
  semaines_pair: 19,
};
const PROPOSITION = {
  label: "2027-2028",
  rentree: "2027-08-30",
  fin_impair: "2028-01-28",
  debut_pair: "2028-01-31",
  fin: "2028-06-30",
  vacances: [{ nom: "Toussaint", debut: "", fin: "" }],
  feries: [{ date: "2027-11-11", nom: "Armistice 1918" }],
};
const REPONSE = { annees: [ORIGINE], en_cours: "2026-2027", verrou: null, proposition: PROPOSITION };

function stubFetch(reponse: unknown = REPONSE) {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      return Promise.resolve({ ok: true, json: async () => reponse });
    }),
  );
  return appels;
}

afterEach(() => vi.unstubAllGlobals());

describe("Années universitaires", () => {
  it("écrit une période en toutes lettres", () => {
    expect(periodeLisible("2026-10-26", "2026-10-30")).toBe("du 26 octobre 2026 au 30 octobre 2026");
    expect(periodeLisible("2026-11-11", "2026-11-11")).toBe("le 11 novembre 2026");
  });

  it("montre l’année en cours sans permettre de la modifier", async () => {
    stubFetch();
    render(<AnneesUniversitaires />);
    expect(await screen.findByText(/38 semaines de cours \(19 à l’impair, 19 au pair\)/)).toBeInTheDocument();
    expect(screen.getByText("(année en cours)")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Année 2026-2027" })).toBeNull();
  });

  it("prépare l’année suivante à partir de la proposition", async () => {
    const appels = stubFetch();
    render(<AnneesUniversitaires />);
    const formulaire = await screen.findByRole("form", { name: "Année 2027-2028", hidden: true });
    const dans = within(formulaire);
    fireEvent.change(dans.getByLabelText("Premier jour de Toussaint"), { target: { value: "2027-10-25" } });
    fireEvent.change(dans.getByLabelText("Dernier jour de Toussaint"), { target: { value: "2027-10-29" } });
    fireEvent.click(dans.getByRole("button", { name: "Ajouter un jour férié", hidden: true }));
    fireEvent.click(dans.getByRole("button", { name: "Retirer le jour férié 2", hidden: true }));
    fireEvent.click(dans.getByRole("button", { name: "Enregistrer l’année 2027-2028", hidden: true }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "PUT")).toBe(true));
    const appel = appels.find((a) => a.init?.method === "PUT");
    expect(appel?.url).toContain("/reglages/annees/2027-2028");
    expect(JSON.parse(String(appel?.init?.body))).toEqual({
      ...PROPOSITION,
      vacances: [{ nom: "Toussaint", debut: "2027-10-25", fin: "2027-10-29" }],
    });
  });

  it("permet de corriger puis de retirer une année préparée", async () => {
    const preparee = { ...ORIGINE, ...PROPOSITION, origine: false, en_cours: false, vacances: [], semaines: 36 };
    const appels = stubFetch({ annees: [ORIGINE, preparee], en_cours: "2026-2027", verrou: null, proposition: { ...PROPOSITION, label: "2028-2029" } });
    vi.stubGlobal("confirm", () => true);
    render(<AnneesUniversitaires />);
    expect(await screen.findByText("(préparée)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retirer l’année 2027-2028", hidden: true }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    expect(appels.find((a) => a.init?.method === "DELETE")?.url).toContain("/reglages/annees/2027-2028");
  });

  it("passe à l’année préparée, sauf si un planning est en service", async () => {
    const preparee = { ...ORIGINE, ...PROPOSITION, origine: false, en_cours: false, vacances: [], semaines: 36 };
    const reponse = { annees: [ORIGINE, preparee], en_cours: "2026-2027", verrou: null, proposition: PROPOSITION };
    const appels = stubFetch(reponse);
    vi.stubGlobal("confirm", () => true);
    const { unmount } = render(<AnneesUniversitaires />);
    fireEvent.click(await screen.findByRole("button", { name: "Passer à l’année 2027-2028", hidden: true }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    expect(appels.find((a) => a.init?.method === "POST")?.url).toContain("/reglages/annees/2027-2028/utiliser");
    unmount();

    stubFetch({ ...reponse, verrou: "Un planning est en service." });
    render(<AnneesUniversitaires />);
    expect(await screen.findByRole("button", { name: "Passer à l’année 2027-2028", hidden: true })).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent("Un planning est en service.");
  });
});
