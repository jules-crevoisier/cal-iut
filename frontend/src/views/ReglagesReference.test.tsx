/**
 * Référence → Réglages (lot 6, 16/11/2026) : ajouter et retirer une salle
 * réservée ou une indisponibilité datée sans passer par un fichier du dépôt.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContexteDroits } from "../contexts/Droits";
import type { AppPayload } from "../types/app";
import { creneauxLisibles, ReglagesReference } from "./ReglagesReference";

const CRENEAUX = ["8h-9h30", "9h30-11h", "11h-12h30", "14h-15h30", "15h30-17h", "17h-18h30"];

const LIVREE = {
  cle: "h018|2099-09-11|12",
  origine: "livree",
  salle: "h018",
  salle_libelle: "Amphi H.018",
  date: "2099-09-11",
  slots: [1, 2],
  motif: "Besoin de la Direction",
  demande_par: "",
};
const PASSEE = { ...LIVREE, cle: "h018|2020-01-10|0", date: "2020-01-10", slots: [0], motif: "Ancienne" };
const AJOUTEE = { ...LIVREE, cle: "abc123", origine: "ajoutee", date: "2099-10-02", slots: [3, 4, 5], motif: "Jury" };

const REPONSE = { creneaux: CRENEAUX, salles_reservees: [PASSEE, LIVREE], indisponibilites: [] };

const PAYLOAD = {
  rooms: [{ id: "h018", label: "Amphi H.018" }],
  teacherLabels: { FLI: "Florent Libbrecht" },
} as unknown as AppPayload;

function stubFetch() {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      if (init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({ ...REPONSE, salles_reservees: [PASSEE, LIVREE, AJOUTEE] }),
        });
      }
      if (init?.method === "DELETE") {
        return Promise.resolve({ ok: true, json: async () => ({ ...REPONSE, salles_reservees: [PASSEE] }) });
      }
      return Promise.resolve({ ok: true, json: async () => REPONSE });
    }),
  );
  return appels;
}

function afficher() {
  const apres = vi.fn();
  render(
    <ContexteDroits.Provider value={{ role: "admin", revision: 1, apresEnregistrement: apres }}>
      <ReglagesReference payload={PAYLOAD} />
    </ContexteDroits.Provider>,
  );
  return apres;
}

afterEach(() => vi.unstubAllGlobals());

describe("creneauxLisibles", () => {
  it("regroupe les créneaux qui se suivent", () => {
    expect(creneauxLisibles([1, 2], CRENEAUX)).toBe("9h30-12h30");
    expect(creneauxLisibles([2, 3], CRENEAUX)).toBe("11h-12h30, 14h-15h30");
    expect(creneauxLisibles([0, 4, 5], CRENEAUX)).toBe("8h-9h30, 15h30-18h30");
    expect(creneauxLisibles([0, 1, 2, 3, 4, 5], CRENEAUX)).toBe("Toute la journée");
  });
});

describe("Référence → Réglages", () => {
  it("liste les réservations à venir, les passées sur demande", async () => {
    stubFetch();
    afficher();
    const bloc = await screen.findByRole("region", { name: "Salles réservées" });
    expect(within(bloc).getByText("Besoin de la Direction")).toBeTruthy();
    expect(within(bloc).getByText("9h30-12h30")).toBeTruthy();
    expect(within(bloc).queryByText("Ancienne")).toBeNull();
    fireEvent.click(within(bloc).getByRole("checkbox", { name: /déjà passée/ }));
    expect(within(bloc).getByText("Ancienne")).toBeTruthy();
  });

  it("n'ajoute qu'une saisie complète, puis l'envoie", async () => {
    const appels = stubFetch();
    const apres = afficher();
    const bloc = await screen.findByRole("region", { name: "Salles réservées" });
    const ajouter = within(bloc).getByRole("button", { name: "Ajouter" }) as HTMLButtonElement;
    expect(ajouter.disabled).toBe(true);

    fireEvent.change(within(bloc).getByLabelText("Salle"), { target: { value: "h018" } });
    fireEvent.change(within(bloc).getByLabelText("Date"), { target: { value: "2099-10-02" } });
    fireEvent.change(within(bloc).getByLabelText("Motif"), { target: { value: " Jury " } });
    expect(ajouter.disabled).toBe(true);
    fireEvent.click(within(bloc).getByRole("checkbox", { name: "14h-15h30" }));
    fireEvent.click(within(bloc).getByRole("checkbox", { name: "15h30-17h" }));
    expect(ajouter.disabled).toBe(false);
    fireEvent.click(ajouter);

    await waitFor(() => expect(within(bloc).getByText("Jury")).toBeTruthy());
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toBe("/reglages/salles-reservees");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      salle: "h018",
      date: "2099-10-02",
      slots: [3, 4],
      motif: "Jury",
    });
    expect(screen.getByRole("status").textContent).toContain("dès maintenant");
    expect(apres).toHaveBeenCalled();
  });

  it("retire une réservation après confirmation, y compris une réservation livrée", async () => {
    const appels = stubFetch();
    const confirmer = vi.fn(() => false);
    vi.stubGlobal("confirm", confirmer);
    afficher();
    const bloc = await screen.findByRole("region", { name: "Salles réservées" });
    fireEvent.click(within(bloc).getByRole("button", { name: "Retirer" }));
    expect(appels.some((a) => a.init?.method === "DELETE")).toBe(false);

    confirmer.mockReturnValue(true);
    fireEvent.click(within(bloc).getByRole("button", { name: "Retirer" }));
    await waitFor(() => expect(within(bloc).getByText("Aucune entrée à venir.")).toBeTruthy());
    const retrait = appels.find((a) => a.init?.method === "DELETE");
    expect(retrait?.url).toBe("/reglages/salles-reservees?cle=h018%7C2099-09-11%7C12&origine=livree");
  });
});
