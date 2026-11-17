/**
 * Référence → Réglages → semaines des alternants et événements à date fixe (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReglagesReponse } from "../api/client";
import { ContexteDroits } from "../contexts/Droits";
import type { AppPayload } from "../types/app";
import { PresencesAlternants } from "./PresencesAlternants";
import { ReglagesReference } from "./ReglagesReference";

const PERIODE = { annee: "BUT2", debut: "2099-03-01", fin: "2099-03-05", jours: 5, cle: "BUT2|2099-03-01", origine: "livree" };
const DONNEES = {
  creneaux: ["8h-9h30", "9h30-11h", "11h-12h30", "14h-15h30", "15h30-17h", "17h-18h30"],
  salles_reservees: [],
  indisponibilites: [],
  parcours: ["BUT1", "BUT2-DEV-FI"],
  evenements_fixes: [
    { cle: "k1", origine: "livree", parcours: "BUT1", date: "2099-09-01", slots: [0, 1], motif: "Rentrée", demande_par: "" },
  ],
  presences_alternants: [
    PERIODE,
    { ...PERIODE, debut: "2020-01-06", fin: "2020-01-10", cle: "BUT2|2020-01-06" },
    { ...PERIODE, annee: "BUT3", debut: "2099-04-05", fin: "2099-04-09", cle: "abc", origine: "ajoutee" },
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

describe("Semaines des alternants à l’IUT", () => {
  it("liste les périodes à venir par année et en ajoute une", async () => {
    const appels = stubFetch();
    const onChange = vi.fn();
    render(<PresencesAlternants donnees={DONNEES} onChange={onChange} />);
    expect(screen.getByText(/Alternants de BUT2 : 1 période à venir/)).toBeInTheDocument();
    expect(screen.getByText(/Afficher aussi les/)).toHaveTextContent("1 déjà passée");
    const ajouter = screen.getByRole("button", { name: "Ajouter la période" });
    expect(ajouter).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Alternants de"), { target: { value: "BUT3" } });
    fireEvent.change(screen.getByLabelText("Premier jour à l’IUT"), { target: { value: "2099-06-07" } });
    fireEvent.change(screen.getByLabelText("Dernier jour à l’IUT"), { target: { value: "2099-06-11" } });
    fireEvent.click(ajouter);
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const appel = appels.find((a) => a.init?.method === "POST");
    expect(appel?.url).toContain("/reglages/presences-alternants");
    expect(JSON.parse(String(appel?.init?.body))).toEqual({ annee: "BUT3", debut: "2099-06-07", fin: "2099-06-11" });
  });

  it("retire une période après confirmation", async () => {
    const appels = stubFetch();
    vi.stubGlobal("confirm", () => true);
    const onChange = vi.fn();
    render(<PresencesAlternants donnees={DONNEES} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Retirer la période BUT3/ }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const url = appels.find((a) => a.init?.method === "DELETE")?.url ?? "";
    expect(url).toContain("cle=abc");
    expect(url).toContain("origine=ajoutee");
  });
});

describe("Événements à date fixe", () => {
  it("s’affichent dans les réglages et s’ajoutent pour une promotion", async () => {
    const appels = stubFetch();
    render(
      <ContexteDroits.Provider value={{ role: "admin", revision: 1, apresEnregistrement: vi.fn() }}>
        <ReglagesReference payload={{ rooms: [], teacherLabels: {}, courses: [] } as unknown as AppPayload} />
      </ContexteDroits.Provider>,
    );
    const bloc = await screen.findByRole("region", { name: "Événements à date fixe" });
    expect(bloc).toHaveTextContent("Rentrée");
    const selects = bloc.querySelectorAll("select");
    fireEvent.change(selects[0], { target: { value: "*" } });
    fireEvent.change(bloc.querySelector('input[type="date"]') as HTMLInputElement, { target: { value: "2099-10-02" } });
    fireEvent.click(bloc.querySelectorAll('input[type="checkbox"]')[0]);
    const motif = bloc.querySelector('input[type="text"], textarea') as HTMLInputElement;
    fireEvent.change(motif, { target: { value: "Forum" } });
    fireEvent.click(bloc.querySelector('button[type="submit"]') as HTMLButtonElement);
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    const appel = appels.find((a) => a.init?.method === "POST");
    expect(appel?.url).toContain("/reglages/evenements-fixes");
    expect(JSON.parse(String(appel?.init?.body))).toMatchObject({ parcours: "*", date: "2099-10-02", motif: "Forum" });
  });
});
