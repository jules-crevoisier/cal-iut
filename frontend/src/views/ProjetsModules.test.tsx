/**
 * Nouveau semestre → Projets de modules (19/11/2026).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjetsModules } from "./ProjetsModules";

const MODULES = [
  { code: "WS401D", nom: "SAE", semestre: "S4", types: { CM: 2, TD: 7 } },
  { code: "WR407D", nom: "Back", semestre: "S4", types: { TD: 7 } },
];
const BASE = { semestre_group: "even", verrouille: null, modules: MODULES, seances_longues: [], periodes: [], projets: [] };

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

describe("Projets de modules", () => {
  it("envoie les étapes dans l’ordre avec les jours par semaine", async () => {
    const appels = stubFetch(BASE);
    render(<ProjetsModules groupe="even" onModifie={() => undefined} />);
    const bouton = await screen.findByRole("button", { name: "Ajouter le projet" });
    expect(bouton).toBeDisabled();
    const formulaire = bouton.closest("form") as HTMLFormElement;
    fireEvent.change(within(formulaire).getByLabelText("Nom du projet"), { target: { value: "Projet S4" } });
    const modules = within(formulaire).getAllByLabelText("Module");
    fireEvent.change(modules[0], { target: { value: "WS401D" } });
    fireEvent.change(modules[1], { target: { value: "WR407D" } });
    fireEvent.change(within(formulaire).getAllByLabelText("Type")[0], { target: { value: "TD" } });
    fireEvent.change(within(formulaire).getAllByLabelText("À la séance n°")[0], { target: { value: "4" } });
    fireEvent.change(within(formulaire).getByLabelText("Jours par semaine"), { target: { value: "2" } });
    fireEvent.change(within(formulaire).getByLabelText("Motif du projet"), { target: { value: "Demande" } });
    fireEvent.click(bouton);

    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toContain("/generations/regles/even/projets");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      nom: "Projet S4",
      etapes: [
        { code: "WS401D", type: "TD", de: null, a: 4 },
        { code: "WR407D", type: null, de: null, a: null },
      ],
      jours_par_semaine: 2,
      motif: "Demande",
    });
  });
});
