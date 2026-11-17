/**
 * Nouveau semestre → Plafonds hebdomadaires (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlafondsHebdo, heures } from "./PlafondsHebdo";

const ORIGINE = { promo: 23, alternants: 23, enseignant: 26 };
const BASE = {
  semestre_group: "even",
  verrouille: null,
  plafonds: ORIGINE,
  origine: ORIGINE,
  personnalise: false,
  mini: 12,
  maxi: 30,
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

afterEach(() => vi.unstubAllGlobals());

describe("Plafonds hebdomadaires", () => {
  it("convertit les créneaux en heures", () => {
    expect(heures(23)).toBe("34 h 30");
    expect(heures(26)).toBe("39 h");
  });

  it("montre les valeurs d’origine et enregistre un nouveau plafond", async () => {
    const appels = stubFetch(BASE);
    const onModifie = vi.fn();
    render(<PlafondsHebdo groupe="even" onModifie={onModifie} />);
    expect(
      await screen.findByText(/Étudiants 34 h 30, alternants 34 h 30, enseignant 39 h \(valeurs d’origine\)/),
    ).toBeInTheDocument();
    const bouton = screen.getByRole("button", { name: "Enregistrer ces plafonds" });
    expect(bouton).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Revenir aux plafonds d’origine" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Plafond étudiants"), { target: { value: "40" } });
    expect(bouton).toBeDisabled(); // hors bornes
    fireEvent.change(screen.getByLabelText("Plafond étudiants"), { target: { value: "22" } });
    expect(screen.getByText(/33 h \(origine : 23\)/)).toBeInTheDocument();
    fireEvent.click(bouton);
    await waitFor(() => expect(onModifie).toHaveBeenCalled());
    const envoi = appels.find((a) => a.init?.method === "PUT")!;
    expect(envoi.url).toContain("/generations/plafonds/even");
    expect(JSON.parse(String(envoi.init?.body))).toEqual({ promo: 22, alternants: 23, enseignant: 26 });
  });

  it("propose de revenir à l’origine, et rien quand le semestre est en service", async () => {
    const appels = stubFetch({ ...BASE, plafonds: { ...ORIGINE, promo: 22 }, personnalise: true });
    const { unmount } = render(<PlafondsHebdo groupe="even" onModifie={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: "Revenir aux plafonds d’origine" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    unmount();

    stubFetch({ ...BASE, verrouille: "Le semestre impair est déjà en service." });
    render(<PlafondsHebdo groupe="odd" onModifie={() => undefined} />);
    await screen.findByText("Le semestre impair est déjà en service.");
    expect(screen.queryByLabelText("Plafond étudiants")).toBeNull();
  });
});
