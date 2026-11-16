/**
 * Nouveau semestre → Règles de modules (lot 6, 16/11/2026).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReglesModules, libellePeriode } from "./ReglesModules";

const MODULES = [
  { code: "WR203", nom: "Ergonomie", semestre: "S2", types: { CM: 2, TD: 8, TP: 1 } },
  { code: "WR401D", nom: "Anglais", semestre: "S4", types: { CM: 1 } },
];
const LONGUE = {
  id: "abc",
  origine: "ajoutee",
  code: "WR203",
  nom: "Ergonomie",
  type: "TD",
  creneaux: 2,
  duree: "3 h",
  motif: "Demande de l’enseignant",
};
const PERIODE = {
  id: null,
  origine: "livree",
  code: "WR401D",
  nom: "Anglais",
  type: "CM",
  rangs: [1],
  debut: "2027-03-01",
  fin: "2027-04-02",
  dates: [],
  motif: "",
};
const BASE = { semestre_group: "even", verrouille: null, modules: MODULES, seances_longues: [], periodes: [] };

function stubFetch(reponse: Record<string, unknown>) {
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

describe("libellePeriode", () => {
  it("dit la période en clair", () => {
    expect(libellePeriode(PERIODE as never)).toBe("du 1 mars 2027 au 2 avr. 2027");
    expect(libellePeriode({ ...PERIODE, fin: null } as never)).toBe("à partir du 1 mars 2027");
    expect(libellePeriode({ ...PERIODE, debut: null } as never)).toBe("jusqu’au 2 avr. 2027");
    expect(libellePeriode({ ...PERIODE, dates: ["2027-03-08"] } as never)).toBe("uniquement le 8 mars 2027");
  });
});

describe("Règles de modules", () => {
  it("ajoute des séances longues pour un type qui a au moins deux séances", async () => {
    const appels = stubFetch(BASE);
    const onModifie = vi.fn();
    render(<ReglesModules groupe="even" onModifie={onModifie} />);

    const bouton = await screen.findByRole("button", { name: "Ajouter les séances longues" });
    expect(bouton).toBeDisabled();
    const formulaire = bouton.closest("form") as HTMLFormElement;
    fireEvent.change(within(formulaire).getByLabelText("Module"), { target: { value: "WR203" } });
    const types = within(formulaire).getByLabelText("Type des séances longues");
    // Un seul TP : pas de bloc possible, il n'est pas proposé.
    expect(within(types).queryByRole("option", { name: /TP/ })).not.toBeInTheDocument();
    fireEvent.change(types, { target: { value: "TD" } });
    fireEvent.change(within(formulaire).getByLabelText("Durée"), { target: { value: "3" } });
    fireEvent.change(within(formulaire).getByLabelText("Motif des séances longues"), { target: { value: " TD longs " } });
    fireEvent.click(bouton);

    await waitFor(() => expect(onModifie).toHaveBeenCalled());
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toContain("/generations/regles/even/seances-longues");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({ code: "WR203", type: "TD", creneaux: 3, motif: "TD longs" });
  });

  it("ajoute une période avec une seule borne", async () => {
    const appels = stubFetch(BASE);
    render(<ReglesModules groupe="even" onModifie={() => undefined} />);
    const bouton = await screen.findByRole("button", { name: "Ajouter la période" });
    const formulaire = bouton.closest("form") as HTMLFormElement;
    fireEvent.change(within(formulaire).getByLabelText("Module"), { target: { value: "WR401D" } });
    fireEvent.change(within(formulaire).getByLabelText("Motif de la période"), { target: { value: "Retour de stage" } });
    expect(bouton).toBeDisabled();
    fireEvent.change(within(formulaire).getByLabelText("Pas avant le"), { target: { value: "2027-03-01" } });
    fireEvent.click(bouton);

    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toContain("/generations/regles/even/periodes");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      code: "WR401D",
      type: null,
      debut: "2027-03-01",
      fin: null,
      motif: "Retour de stage",
    });
  });

  it("retire une règle saisie, pas une règle d’origine", async () => {
    const appels = stubFetch({ ...BASE, seances_longues: [LONGUE], periodes: [PERIODE] });
    render(<ReglesModules groupe="even" onModifie={() => undefined} />);
    expect(await screen.findByText("2 règles")).toBeInTheDocument();
    expect(screen.getByText(/les TD par blocs de 3 h/)).toBeInTheDocument();
    expect(screen.getByText(/les CM n° 1, du 1 mars 2027 au 2 avr. 2027/)).toBeInTheDocument();
    expect(screen.getByText("D’origine")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Retirer la règle/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Retirer la règle WR203 TD" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    expect(appels.find((a) => a.init?.method === "DELETE")?.url).toContain("/generations/regles/even/seances-longues/abc");
  });

  it("ne propose rien à modifier quand le semestre est en service", async () => {
    stubFetch({ ...BASE, verrouille: "Le semestre impair est déjà en service.", seances_longues: [LONGUE] });
    render(<ReglesModules groupe="odd" onModifie={() => undefined} />);
    expect(await screen.findByText("Le semestre impair est déjà en service.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retirer/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ajouter/ })).not.toBeInTheDocument();
  });
});
