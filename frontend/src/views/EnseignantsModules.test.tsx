/**
 * Nouveau semestre → Enseignants d’un module (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnseignantsModules, libelleDuo } from "./EnseignantsModules";

const ALO = { code: "ALO", nom: "Ariane LOIZON", td_tp: true };
const GLE = { code: "GLE", nom: "Gaëlle LEFEVRE", td_tp: true };
const MODULES = [
  {
    code: "WR208",
    nom: "Culture artistique",
    semestre: "S2",
    types: { CM: 2, TD: 8, TP: 4 },
    enseignants: [ALO, GLE],
    groupes_tp: ["A", "B", "C", "D"],
    groupes_td: ["AB", "CD"],
  },
  {
    code: "WR201",
    nom: "Anglais",
    semestre: "S2",
    types: { TD: 8 },
    enseignants: [{ code: "TPA", nom: "Thomas PAVIE", td_tp: true }],
    groupes_tp: [],
  },
];
const DUO = {
  id: null,
  origine: "livree",
  code: "WR208",
  nom: "Culture artistique",
  enseignants: [ALO, GLE],
  salles: [
    { id: "h201", label: "H.201" },
    { id: "h203", label: "H.203" },
  ],
  groupes: { ALO: ["A", "C"], GLE: ["B", "D"] },
  motif: "",
};
const BASE = {
  semestre_group: "even",
  verrouille: null,
  modules: MODULES,
  seances_longues: [],
  periodes: [],
  salles: DUO.salles,
  modes: [
    { mode: "alterne", libelle: "À tour de rôle, une séance chacun" },
    { mode: "par_groupes", libelle: "Par groupes entiers" },
  ],
  repartitions: [],
  ordres: [],
  duos: [],
};

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

const choisir = (nom: string, valeur: string) =>
  fireEvent.change(screen.getByLabelText(nom), { target: { value: valeur } });

afterEach(() => vi.unstubAllGlobals());

describe("Enseignants d’un module", () => {
  it("dit un duo en clair", () => {
    expect(libelleDuo(DUO as never)).toBe(
      "Ariane LOIZON (TP A, C) et Gaëlle LEFEVRE (TP B, D), en H.201 et H.203",
    );
    expect(libelleDuo({ ...DUO, groupes: {} } as never)).toBe(
      "Ariane LOIZON et Gaëlle LEFEVRE, en H.201 et H.203",
    );
  });

  it("ne propose que les modules à plusieurs enseignants", async () => {
    stubFetch(BASE);
    render(<EnseignantsModules groupe="even" onModifie={() => undefined} />);
    await screen.findByText("Enseignants d’un module");
    expect(screen.getByText("Aucune règle")).toBeInTheDocument();
    const modules = screen.getAllByLabelText("Module") as HTMLSelectElement[];
    expect(modules).toHaveLength(3);
    for (const m of modules)
      expect([...m.options].map((o) => o.value)).toEqual(["", "WR208"]);
  });

  it("ne s’affiche pas sans module à plusieurs enseignants", async () => {
    const appels = stubFetch({ ...BASE, modules: [MODULES[1]] });
    const { container } = render(<EnseignantsModules groupe="even" onModifie={() => undefined} />);
    await waitFor(() => expect(appels).toHaveLength(1));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("enregistre une répartition, avec celui qui commence", async () => {
    const appels = stubFetch(BASE);
    const onModifie = vi.fn();
    render(<EnseignantsModules groupe="even" onModifie={onModifie} />);
    await screen.findByText("Enseignants d’un module");
    const bouton = screen.getByRole("button", { name: "Ajouter la répartition" });
    expect(bouton).toBeDisabled();
    fireEvent.change(screen.getAllByLabelText("Module")[0], { target: { value: "WR208" } });
    choisir("Séances à répartir", "TP");
    choisir("Façon de répartir", "par_groupes");
    choisir("Qui commence", "GLE");
    choisir("Motif de la répartition", "Demande des enseignants");
    fireEvent.click(bouton);
    await waitFor(() => expect(onModifie).toHaveBeenCalled());
    const envoi = appels.find((a) => a.init?.method === "POST")!;
    expect(envoi.url).toContain("/generations/regles/even/repartitions");
    expect(JSON.parse(String(envoi.init?.body))).toEqual({
      code: "WR208",
      type: "TP",
      mode: "par_groupes",
      ordre: ["GLE", "ALO"],
      motif: "Demande des enseignants",
    });
  });

  it("enregistre un ordre entre deux enseignants différents", async () => {
    const appels = stubFetch(BASE);
    render(<EnseignantsModules groupe="even" onModifie={() => undefined} />);
    await screen.findByText("Enseignants d’un module");
    fireEvent.change(screen.getAllByLabelText("Module")[1], { target: { value: "WR208" } });
    choisir("D’abord", "ALO");
    const ensuite = screen.getByLabelText("Ensuite") as HTMLSelectElement;
    expect([...ensuite.options].map((o) => o.value)).toEqual(["", "GLE"]);
    choisir("Ensuite", "GLE");
    choisir("Motif de l’ordre", "Les bases d’abord");
    fireEvent.click(screen.getByRole("button", { name: "Ajouter l’ordre" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "POST")!;
    expect(envoi.url).toContain("/generations/regles/even/ordres");
    expect(JSON.parse(String(envoi.init?.body))).toEqual({
      code: "WR208",
      ordre: ["ALO", "GLE"],
      motif: "Les bases d’abord",
    });
  });

  it("enregistre un duo, ses salles et les groupes de chacun", async () => {
    const appels = stubFetch(BASE);
    render(<EnseignantsModules groupe="even" onModifie={() => undefined} />);
    await screen.findByText("Enseignants d’un module");
    fireEvent.change(screen.getAllByLabelText("Module")[2], { target: { value: "WR208" } });
    choisir("Premier enseignant", "ALO");
    choisir("Salle du premier enseignant", "h201");
    choisir("Second enseignant", "GLE");
    choisir("Salle du second enseignant", "h203");
    choisir("Enseignant du TP A", "ALO");
    choisir("Enseignant du TP B", "GLE");
    choisir("Motif du duo", "Atelier commun");
    fireEvent.click(screen.getByRole("button", { name: "Ajouter le duo" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "POST")!;
    expect(envoi.url).toContain("/generations/regles/even/duos");
    expect(JSON.parse(String(envoi.init?.body))).toEqual({
      code: "WR208",
      enseignants: ["ALO", "GLE"],
      salles: ["h201", "h203"],
      groupes: { ALO: ["A"], GLE: ["B"] },
      type: "TP",
      de: null,
      a: null,
      motif: "Atelier commun",
    });
  });

  it("enregistre un duo de TD sans salle, pour une partie des séances", async () => {
    const appels = stubFetch(BASE);
    render(<EnseignantsModules groupe="even" onModifie={() => undefined} />);
    await screen.findByText("Enseignants d’un module");
    fireEvent.change(screen.getAllByLabelText("Module")[2], { target: { value: "WR208" } });
    choisir("Type de séance du duo", "TD");
    choisir("Premier enseignant", "ALO");
    choisir("Second enseignant", "GLE");
    choisir("Enseignant du TD AB", "ALO");
    choisir("Enseignant du TD CD", "GLE");
    choisir("De la séance n° (facultatif)", "7");
    choisir("Motif du duo", "TD en parallèle");
    fireEvent.click(screen.getByRole("button", { name: "Ajouter le duo" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "POST")!;
    expect(JSON.parse(String(envoi.init?.body))).toEqual({
      code: "WR208",
      enseignants: ["ALO", "GLE"],
      salles: [],
      groupes: { ALO: ["AB"], GLE: ["CD"] },
      type: "TD",
      de: 7,
      a: null,
      motif: "TD en parallèle",
    });
  });

  it("liste les règles d’origine sans bouton, et retire les autres", async () => {
    const ordre = { id: "o1", origine: "ajoutee", code: "WR208", nom: "Culture artistique", ordre: [ALO, GLE], motif: "m" };
    const appels = stubFetch({ ...BASE, duos: [DUO], ordres: [ordre] });
    render(<EnseignantsModules groupe="even" onModifie={() => undefined} />);
    await screen.findByText("2 règles");
    expect(screen.getByText("D’origine")).toBeInTheDocument();
    expect(screen.getByText(/d’abord Ariane LOIZON, puis Gaëlle LEFEVRE/)).toBeInTheDocument();
    // Les groupes déjà pris par le duo d’origine ne sont plus proposés.
    fireEvent.change(screen.getAllByLabelText("Module")[2], { target: { value: "WR208" } });
    choisir("Premier enseignant", "ALO");
    choisir("Second enseignant", "GLE");
    expect(screen.queryByLabelText("Enseignant du TP A")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Retirer la règle d’ordre de WR208/ }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    expect(appels.find((a) => a.init?.method === "DELETE")!.url).toContain("/generations/regles/even/ordres/o1");
  });

  it("n’offre aucune saisie quand le semestre est en service", async () => {
    stubFetch({ ...BASE, verrouille: "Le semestre impair est déjà en service.", duos: [DUO] });
    render(<EnseignantsModules groupe="odd" onModifie={() => undefined} />);
    await screen.findByText("Le semestre impair est déjà en service.");
    expect(screen.queryByRole("button", { name: "Ajouter le duo" })).toBeNull();
    expect(screen.queryByLabelText("Module")).toBeNull();
  });
});
