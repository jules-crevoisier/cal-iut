/**
 * Nouveau semestre → Dates du semestre (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PeriodeDesCours } from "./PeriodeDesCours";

const PAIR = {
  semestre_group: "even",
  verrouille: null,
  debut: "2027-02-01",
  fin: "2027-06-30",
  personnalise: false,
  fin_alternants: null,
  origine: { debut: "2027-02-01", fin: "2027-06-30", fin_alternants: null },
  semaines: 19,
  semaines_alternants: null,
  vacances: [{ debut: "2027-02-22", fin: "2027-02-26" }],
  autre: { libelle: "Semestre impair", debut: "2026-08-31", fin: "2027-01-29", chevauche: false },
};

function stubFetch(reponse: Record<string, unknown>, apres?: Record<string, unknown>) {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      return Promise.resolve({ ok: true, json: async () => (init?.method && apres ? apres : reponse) });
    }),
  );
  return appels;
}

afterEach(() => vi.unstubAllGlobals());

describe("Dates du semestre", () => {
  it("règle le dernier jour de cours des alternants", async () => {
    const apres = { ...PAIR, fin: "2027-06-11", fin_alternants: "2027-06-25", personnalise: true, semaines: 16 };
    const appels = stubFetch(PAIR, apres);
    render(<PeriodeDesCours groupe="even" onModifie={() => undefined} />);
    fireEvent.change(await screen.findByLabelText("Dernier jour de cours"), { target: { value: "2027-06-11" } });
    fireEvent.change(screen.getByLabelText("Dernier jour des alternants"), { target: { value: "2027-06-25" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer ces dates" }));
    expect(await screen.findByText(/alternants jusqu’au vendredi 25 juin 2027/)).toBeInTheDocument();
    const envoi = appels.find((a) => a.init?.method === "PUT");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      debut: "2027-02-01",
      fin: "2027-06-11",
      fin_alternants: "2027-06-25",
    });
  });

  it("montre les dates proposées, la fin de l’autre semestre et les vacances", async () => {
    stubFetch(PAIR);
    render(<PeriodeDesCours groupe="even" onModifie={() => undefined} />);
    expect(
      await screen.findByText(/Du lundi 1 février 2027 au mercredi 30 juin 2027, 19 semaines de cours/),
    ).toBeInTheDocument();
    expect(screen.getByText("Dates proposées")).toBeInTheDocument();
    expect(screen.getByText(/Semestre impair : cours du 31 août 2026 au 29 janv. 2027/)).toBeInTheDocument();
    expect(screen.getByText(/Vacances pendant ce semestre : du 22 févr. 2027 au 26 févr. 2027/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enregistrer ces dates" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Revenir aux dates proposées" })).not.toBeInTheDocument();
  });

  it("enregistre de nouvelles dates et signale un chevauchement", async () => {
    const apres = {
      ...PAIR,
      debut: "2027-01-04",
      personnalise: true,
      semaines: 23,
      autre: { ...PAIR.autre, chevauche: true },
    };
    const appels = stubFetch(PAIR, apres);
    const onModifie = vi.fn();
    render(<PeriodeDesCours groupe="even" onModifie={onModifie} />);
    fireEvent.change(await screen.findByLabelText("Premier jour de cours"), { target: { value: "2027-01-04" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer ces dates" }));

    await waitFor(() => expect(onModifie).toHaveBeenCalled());
    const envoi = appels.find((a) => a.init?.method === "PUT");
    expect(envoi?.url).toContain("/generations/periode/even");
    expect(JSON.parse(String(envoi?.init?.body))).toEqual({
      debut: "2027-01-04",
      fin: "2027-06-30",
      fin_alternants: null,
    });
    expect(screen.getByText(/Ces dates chevauchent le semestre impair/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Revenir aux dates proposées" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
  });

  it("ne propose rien à modifier quand le semestre est en service", async () => {
    stubFetch({ ...PAIR, verrouille: "Le semestre impair est déjà en service." });
    render(<PeriodeDesCours groupe="odd" onModifie={() => undefined} />);
    expect(await screen.findByText("Le semestre impair est déjà en service.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Premier jour de cours")).not.toBeInTheDocument();
  });
});
