/**
 * Nouveau semestre → Dates des SAE : placement par le calcul et périodes
 * d'encadrement (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DatesSae } from "./DatesSae";

const SANS_DATE = {
  code: "WS201",
  nom: "Concevoir un produit",
  semestre: "S2",
  parcours: "BUT1",
  seances: 7,
  dates_officielles: [],
  dates_saisies: [],
  placee_par_le_calcul: false,
  placement_saisi: false,
  enseignants: [
    { code: "KBR", nom: "Kyllian BRESSON" },
    { code: "ALO", nom: "Ariane LOIZON" },
  ],
  phases: [],
};
const LIVREE = {
  id: null,
  origine: "livree",
  teacher_code: "ALO",
  nom: "Ariane LOIZON",
  debut: "2027-03-08",
  fin: "2027-03-12",
  sauf: ["2027-03-10"],
  motif: "Fin de projet",
};
const SAISIE = { ...LIVREE, id: "p1", origine: "ajoutee", teacher_code: "KBR", nom: "Kyllian BRESSON", sauf: [], motif: "" };
const DATEE = {
  ...SANS_DATE,
  code: "WS202",
  dates_saisies: ["2027-03-08", "2027-03-09", "2027-03-10", "2027-03-11", "2027-03-12"],
  phases: [LIVREE, SAISIE],
};

function stubFetch(sae: unknown[], verrouille: string | null = null) {
  const appels: { url: string; init?: RequestInit }[] = [];
  const reponse = { semestre_group: "even", verrouille, sae };
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

describe("Dates des SAE : calcul et encadrement", () => {
  it("confie au calcul une SAE sans date, avec un motif", async () => {
    const appels = stubFetch([SANS_DATE]);
    render(<DatesSae groupe="even" onModifie={() => undefined} />);
    fireEvent.click(await screen.findByText("Placement par le calcul"));
    const bouton = screen.getByRole("button", { name: "Faire placer cette SAE par le calcul" });
    expect(bouton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("WS201, motif du placement par le calcul"), {
      target: { value: "Pas de journées banalisées" },
    });
    fireEvent.click(bouton);
    await waitFor(() => expect(appels.some((a) => a.init?.method === "PUT")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "PUT")!;
    expect(envoi.url).toContain("/generations/sae/even/WS201/placement");
    expect(JSON.parse(String(envoi.init?.body))).toEqual({ par_le_calcul: true, motif: "Pas de journées banalisées" });
  });

  it("permet de défaire un placement choisi à l’écran, pas celui d’origine", async () => {
    stubFetch([
      { ...SANS_DATE, placee_par_le_calcul: true, placement_saisi: true },
      { ...SANS_DATE, code: "WSA501D", placee_par_le_calcul: true },
    ]);
    render(<DatesSae groupe="even" onModifie={() => undefined} />);
    await screen.findAllByText("Placement par le calcul");
    expect(screen.getAllByRole("button", { name: "Ne plus la faire placer par le calcul" })).toHaveLength(1);
    expect(screen.getByText(/Réglage d’origine : le calcul place ses séances/)).toBeInTheDocument();
  });

  it("liste les périodes d’encadrement et en ajoute une", async () => {
    const appels = stubFetch([DATEE]);
    render(<DatesSae groupe="even" onModifie={() => undefined} />);
    await screen.findByText(/Qui encadre, et quand/);
    expect(screen.getByText(/2 périodes/)).toBeInTheDocument();
    expect(screen.getByText("D’origine")).toBeInTheDocument();
    expect(screen.getByText(/sauf 1 jour/)).toBeInTheDocument();
    expect(screen.queryByText("Placement par le calcul")).toBeNull();

    fireEvent.change(screen.getByLabelText("WS202, enseignant de la période"), { target: { value: "KBR" } });
    fireEvent.change(screen.getByLabelText("WS202, période du"), { target: { value: "2027-03-08" } });
    fireEvent.change(screen.getByLabelText("WS202, période au"), { target: { value: "2027-03-09" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter la période" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "POST")!;
    expect(envoi.url).toContain("/generations/sae/even/WS202/phases");
    expect(JSON.parse(String(envoi.init?.body))).toEqual({
      teacher_code: "KBR",
      debut: "2027-03-08",
      fin: "2027-03-09",
      motif: "",
    });

    fireEvent.click(screen.getByRole("button", { name: "Retirer la période de Kyllian BRESSON sur WS202" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    expect(appels.find((a) => a.init?.method === "DELETE")!.url).toContain("/generations/sae/even/WS202/phases/p1");
  });

  it("montre les périodes sans rien proposer quand le semestre est en service", async () => {
    stubFetch([DATEE, SANS_DATE], "Le semestre est déjà en service.");
    render(<DatesSae groupe="even" onModifie={() => undefined} />);
    await screen.findByText(/Qui encadre, et quand/);
    expect(screen.queryByRole("button", { name: "Ajouter la période" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Retirer la période/ })).toBeNull();
    expect(screen.queryByText("Placement par le calcul")).toBeNull();
  });
});
