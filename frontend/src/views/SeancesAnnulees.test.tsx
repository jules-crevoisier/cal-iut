/**
 * Nouveau semestre → Séances annulées (lot 6, 16/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SeancesAnnulees } from "./SeancesAnnulees";

const MODULES = [{ code: "WR203", nom: "Ergonomie", semestre: "S2", seances: 2 }];
const SEANCES = [
  { id: "WR203-S2-TD-1-but1-td-ab", libelle: "TD 1 · TD AB", annulee: false },
  { id: "WR203-S2-TD-2-but1-td-ab", libelle: "TD 2 · TD AB", annulee: true },
];
const ANNULEE = {
  session_id: "WR203-S2-TD-2-but1-td-ab",
  libelle: "TD 2 · TD AB",
  code: "WR203",
  nom: "Ergonomie",
  motif: "Reliquat isolé",
  demande_par: "Kyllian",
  le: "2026-11-16",
  origine: "ajoutee",
  existe: true,
};

function stubFetch(reponse: Record<string, unknown>) {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      const corps = String(url).includes("/seances?") ? { seances: SEANCES } : reponse;
      return Promise.resolve({ ok: true, json: async () => corps });
    }),
  );
  return appels;
}

afterEach(() => vi.unstubAllGlobals());

describe("Séances annulées", () => {
  it("liste les annulations et envoie une nouvelle annulation avec son motif", async () => {
    const appels = stubFetch({ semestre_group: "even", verrouille: null, annulees: [ANNULEE], modules: MODULES });
    const onModifie = vi.fn();
    render(<SeancesAnnulees groupe="even" onModifie={onModifie} />);

    expect(await screen.findByText("1 séance ne sera pas placée")).toBeInTheDocument();
    expect(screen.getByText("Reliquat isolé (Kyllian)")).toBeInTheDocument();
    const bouton = screen.getByRole("button", { name: "Annuler cette séance" });
    expect(bouton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Module"), { target: { value: "WR203" } });
    const option = await screen.findByRole("option", { name: "TD 1 · TD AB" });
    expect(screen.getByRole("option", { name: "TD 2 · TD AB (annulée)" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Séance"), { target: { value: (option as HTMLOptionElement).value } });
    expect(bouton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Motif"), { target: { value: " Intervenant absent " } });
    fireEvent.click(bouton);

    await waitFor(() => expect(onModifie).toHaveBeenCalled());
    const envoi = appels.find((a) => a.init?.method === "POST");
    expect(envoi?.url).toContain("/generations/annulations/even");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      session_id: "WR203-S2-TD-1-but1-td-ab",
      motif: "Intervenant absent",
    });
  });

  it("rétablit une séance annulée", async () => {
    const appels = stubFetch({ semestre_group: "even", verrouille: null, annulees: [ANNULEE], modules: MODULES });
    render(<SeancesAnnulees groupe="even" onModifie={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: "Rétablir WR203 TD 2 · TD AB" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    expect(appels.find((a) => a.init?.method === "DELETE")?.url).toContain(
      "session_id=WR203-S2-TD-2-but1-td-ab",
    );
  });

  it("ne propose rien à modifier quand le semestre est en service", async () => {
    stubFetch({
      semestre_group: "odd",
      verrouille: "Le semestre impair est déjà en service.",
      annulees: [{ ...ANNULEE, origine: "livree", existe: false }],
      modules: MODULES,
    });
    render(<SeancesAnnulees groupe="odd" onModifie={() => undefined} />);
    expect(await screen.findByText("Le semestre impair est déjà en service.")).toBeInTheDocument();
    expect(screen.getByText("N’existe plus")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rétablir/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Annuler cette séance" })).not.toBeInTheDocument();
  });
});
