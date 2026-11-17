/**
 * Référence → Réglages → salles et effectifs (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReglagesReponse } from "../api/client";
import { EffectifsReglables, SallesDesModules, SallesReglables, parParcours } from "./SallesEtEffectifs";

const H005 = {
  id: "h005",
  label: "H.005",
  capacite: 15,
  type: "tp_standard",
  placement_auto: true,
  type_fixe: false,
  ajoutee: false,
  origine: { capacite: 15, type: "tp_standard" },
  modifiee: false,
};
const TD = { id: "but1-td-ab", label: "TD AB", parcours: "BUT1", kind: "td", effectif: 30, origine: 30, modifie: false };
const DONNEES = {
  creneaux: [],
  salles_reservees: [],
  indisponibilites: [],
  salles: [H005, { ...H005, id: "h001", label: "H.001", type: "reserve", type_fixe: true }],
  types_de_salle: ["standard", "tp_standard", "amphi"],
  effectifs: [
    { ...TD, id: "but1-tp-a", label: "TP A", kind: "tp", effectif: 15, origine: 15 },
    TD,
    { ...TD, id: "but1-promo", label: "Promo BUT1", kind: "promo", effectif: 125, origine: 120, modifie: true },
  ],
} as unknown as ReglagesReponse;

function stubFetch() {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      return Promise.resolve({ ok: true, json: async () => DONNEES });
    }),
  );
  return appels;
}

afterEach(() => vi.unstubAllGlobals());

describe("Salles réglables", () => {
  it("enregistre la capacité, le type et le placement automatique d’une salle", async () => {
    const appels = stubFetch();
    const onChange = vi.fn();
    render(<SallesReglables donnees={DONNEES} onChange={onChange} />);
    const enregistrer = screen.getAllByRole("button", { name: "Enregistrer" })[0];
    expect(enregistrer).toBeDisabled();
    expect(screen.getByLabelText("Type de H.001")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Capacité de H.005"), { target: { value: "18" } });
    fireEvent.change(screen.getByLabelText("Type de H.005"), { target: { value: "standard" } });
    fireEvent.click(screen.getByLabelText("Placement automatique en H.005"));
    fireEvent.click(enregistrer);
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const appel = appels.find((a) => a.init?.method === "PUT");
    expect(appel?.url).toContain("/reglages/salles/h005");
    expect(JSON.parse(String(appel?.init?.body))).toEqual({ capacite: 18, type: "standard", placement_auto: false });
  });

  it("refuse une capacité hors bornes et propose le retour à l’origine", async () => {
    const appels = stubFetch();
    const onChange = vi.fn();
    render(
      <SallesReglables
        donnees={{ ...DONNEES, salles: [{ ...H005, capacite: 20, modifiee: true }] } as ReglagesReponse}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Capacité de H.005"), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Revenir à l’origine" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(appels.find((a) => a.init?.method === "DELETE")?.url).toContain("/reglages/salles/h005");
  });
});

describe("Effectifs des groupes", () => {
  it("range les groupes par parcours, la promotion d’abord", () => {
    expect(parParcours(DONNEES.effectifs ?? []).map(([p, gs]) => [p, gs.map((g) => g.kind)])).toEqual([
      ["BUT1", ["promo", "td", "tp"]],
    ]);
  });

  it("enregistre un effectif et propose le retour à l’origine", async () => {
    const appels = stubFetch();
    const onChange = vi.fn();
    render(<EffectifsReglables donnees={DONNEES} onChange={onChange} />);
    expect(screen.getByText("(modifié)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Effectif de BUT1 TD AB"), { target: { value: "33" } });
    const ligne = screen.getByLabelText("Effectif de BUT1 TD AB").closest("tr") as HTMLElement;
    fireEvent.click(ligne.querySelector("button") as HTMLButtonElement);
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const appel = appels.find((a) => a.init?.method === "PUT");
    expect(appel?.url).toContain("/reglages/effectifs/but1-td-ab");
    expect(JSON.parse(String(appel?.init?.body))).toEqual({ effectif: 33 });
    fireEvent.click(screen.getByRole("button", { name: "Revenir à l’origine" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
  });
});

describe("Type de salle d’un module", () => {
  const MODULES = [{ valeur: "WR104", libelle: "WR104 · Culture numérique" }];

  it("ajoute une règle pour les séances cochées", async () => {
    const appels = stubFetch();
    const onChange = vi.fn();
    render(<SallesDesModules modules={MODULES} donnees={DONNEES} onChange={onChange} />);
    const ajouter = screen.getByRole("button", { name: "Ajouter la règle" });
    expect(ajouter).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Module"), { target: { value: "WR104" } });
    fireEvent.change(screen.getByLabelText("Type de salle préféré"), { target: { value: "amphi" } });
    fireEvent.click(screen.getByLabelText("TP"));
    fireEvent.click(ajouter);
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const appel = appels.find((a) => a.init?.method === "POST");
    expect(appel?.url).toContain("/reglages/regles-salles");
    expect(JSON.parse(String(appel?.init?.body))).toEqual({
      course_code: "WR104",
      session_types: ["TD"],
      type_prefere: "amphi",
      type_repli: "",
    });
  });

  it("liste les règles saisies et permet de les retirer", async () => {
    const appels = stubFetch();
    const onChange = vi.fn();
    const regle = {
      id: "abc",
      course_code: "WR104",
      session_types: ["TD", "TP"],
      type_prefere: "tp_standard",
      type_repli: "standard",
      demande_par: "",
    };
    render(
      <SallesDesModules
        modules={MODULES}
        donnees={{ ...DONNEES, regles_salles: [regle] } as ReglagesReponse}
        onChange={onChange}
      />,
    );
    expect(screen.getByText(/TD et TP : Salle de TP, sinon Salle banalisée/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retirer la règle de WR104 TD TP" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(appels.find((a) => a.init?.method === "DELETE")?.url).toContain("/reglages/regles-salles/abc");
  });
});
