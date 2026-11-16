/**
 * Nouveau semestre → Dates des SAE (lot 6, 16/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DatesSae, joursOuvres, periodes } from "./DatesSae";

const WS201 = {
  code: "WS201",
  nom: "Concevoir un produit",
  semestre: "S2",
  parcours: "BUT1",
  seances: 7,
  dates_officielles: [],
  dates_saisies: [],
  placee_par_le_calcul: false,
};
const WS401 = { ...WS201, code: "WS401", semestre: "S4", dates_officielles: ["2027-04-05", "2027-04-06"] };

function stubFetch(reponse: Record<string, unknown>) {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      if (init?.method === "PUT") {
        const dates = JSON.parse(String(init.body)).dates as string[];
        return Promise.resolve({
          ok: true,
          json: async () => ({ ...reponse, sae: [{ ...WS201, dates_saisies: dates }, WS401] }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => reponse });
    }),
  );
  return appels;
}

afterEach(() => vi.unstubAllGlobals());

describe("joursOuvres et periodes", () => {
  it("ne garde que du lundi au vendredi", () => {
    // Du jeudi 4 au mardi 9 mars 2027 : le week-end saute.
    expect(joursOuvres("2027-03-04", "2027-03-09")).toEqual(["2027-03-04", "2027-03-05", "2027-03-08", "2027-03-09"]);
    expect(joursOuvres("2027-03-06", "2027-03-07")).toEqual([]);
    expect(joursOuvres("2027-03-08", "")).toEqual(["2027-03-08"]);
  });

  it("regroupe les jours qui se suivent, week-end compris", () => {
    expect(periodes(["2027-03-09", "2027-03-05", "2027-03-08", "2027-03-15"])).toEqual([
      ["2027-03-05", "2027-03-08", "2027-03-09"],
      ["2027-03-15"],
    ]);
  });
});

describe("Dates des SAE", () => {
  it("signale les SAE sans date et envoie la période saisie", async () => {
    const appels = stubFetch({ semestre_group: "even", verrouille: null, sae: [WS201, WS401] });
    const modifie = vi.fn();
    render(<DatesSae groupe="even" onModifie={modifie} />);
    expect(await screen.findByText("1 sur 2 sans date")).toBeTruthy();
    expect(screen.getByText("Aucune date")).toBeTruthy();
    // Les dates du fichier de l'établissement : affichées, sans bouton de retrait.
    expect(screen.getByText(/5 avr\. – 6 avr\. 2027/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Retirer .* de WS401/ })).toBeNull();

    fireEvent.change(screen.getByLabelText("WS201, du"), { target: { value: "2027-03-04" } });
    fireEvent.change(screen.getByLabelText("WS201, au"), { target: { value: "2027-03-09" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter 4 jours" }));

    await waitFor(() => expect(screen.getByText(/4 mars – 9 mars 2027/)).toBeTruthy());
    const envoi = appels.find((a) => a.init?.method === "PUT");
    expect(envoi?.url).toBe("/generations/sae/even/WS201");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      dates: ["2027-03-04", "2027-03-05", "2027-03-08", "2027-03-09"],
    });
    expect(modifie).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/toutes datées/)).toBeTruthy();

    // Retirer la période saisie.
    fireEvent.click(screen.getByRole("button", { name: /Retirer 4 mars – 9 mars 2027 de WS201/ }));
    await waitFor(() => expect(screen.getByText("Aucune date")).toBeTruthy());
    expect(JSON.parse(String(appels.filter((a) => a.init?.method === "PUT")[1].init?.body))).toEqual({ dates: [] });
  });

  it("un semestre déjà en service se lit sans se modifier", async () => {
    stubFetch({
      semestre_group: "odd",
      verrouille: "Le semestre impair est déjà en service.",
      sae: [{ ...WS201, dates_saisies: ["2027-03-08"] }],
    });
    render(<DatesSae groupe="odd" onModifie={() => undefined} />);
    expect(await screen.findByText("Le semestre impair est déjà en service.")).toBeTruthy();
    expect(screen.queryByLabelText("WS201, du")).toBeNull();
    expect(screen.queryByRole("button", { name: /Retirer/ })).toBeNull();
  });
});
