/**
 * Lissage d'une promo : on calcule, on relit, on décoche, et seul ce qui
 * reste coché part au serveur — jamais d'écriture sans confirmation.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LissageModal } from "./LissageModal";
import { confirmAsync } from "../utils/confirmDialog";

vi.mock("../utils/confirmDialog", () => ({ confirmAsync: vi.fn() }));

const mesure = (semaine: number, cours_8h: number, trous: number) => ({
  semaine,
  libelle: `Semaine ${semaine + 2}`,
  seances: 4,
  cours_8h,
  cours_9h30: 1,
  cours_17h: 0,
  trous,
  journees_isolees: 0,
  charge_max: 2,
  charges: [2, 2, 0, 0, 0],
});

const PROPOSITION = {
  parcours: "BUT3-DEV-FC",
  statut: "OPTIMAL",
  message: "2 déplacement(s) proposé(s).",
  semaines: [6],
  deplacements: [
    {
      session_id: "A", course_code: "WRA501D", enseignants: ["TPA"], de: [6, 0, 0], vers: [6, 0, 1],
      libelle_de: "lun. 12/10 8h", libelle_vers: "lun. 12/10 9h30", salle: "H.101",
    },
    {
      session_id: "B", course_code: "WRA508D", enseignants: ["TCA"], de: [6, 1, 0], vers: [6, 1, 2],
      libelle_de: "mar. 13/10 8h", libelle_vers: "mar. 13/10 11h", salle: "H.111",
    },
  ],
  avant: [mesure(6, 2, 1)],
  apres: [mesure(6, 0, 0)],
  duree_s: 12,
  verification: [],
};

function stubFetch() {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      const u = String(url);
      if (init?.method === "POST" && u.endsWith("/placements/lissage")) {
        return Promise.resolve({ ok: true, json: async () => ({ job_id: "j1", status: "running" }) });
      }
      if (init?.method === "POST" && u.includes("/appliquer")) {
        return Promise.resolve({ ok: true, json: async () => ({ appliques: ["A"], echec: null, restants: [] }) });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ job_id: "j1", status: "done", parcours: "BUT3-DEV-FC", proposition: PROPOSITION }),
      });
    }),
  );
  return appels;
}

describe("LissageModal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.mocked(confirmAsync).mockReset();
  });

  it("should apply only the moves left checked, after confirmation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const appels = stubFetch();
    vi.mocked(confirmAsync).mockResolvedValue(true);
    const onApplique = vi.fn();
    render(<LissageModal parcoursInitial="BUT3-DEV-FC" onFermer={() => {}} onApplique={onApplique} />);

    fireEvent.click(screen.getByRole("button", { name: "Calculer une proposition" }));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(screen.getByText(/2 déplacement\(s\) proposé\(s\)/)).toBeInTheDocument());

    // Avant/après lisible : 2 cours à 8h → 0.
    expect(screen.getByRole("columnheader", { name: "8h" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /WRA508D/ }));
    fireEvent.click(screen.getByRole("button", { name: "Appliquer 1 déplacement" }));

    await waitFor(() => expect(onApplique).toHaveBeenCalled());
    expect(confirmAsync).toHaveBeenCalledTimes(1);
    const application = appels.find((a) => a.url.includes("/appliquer"));
    expect(JSON.parse(String(application?.init?.body))).toEqual({ exclure: ["B"] });
  });

  it("should never write when the confirmation is refused", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const appels = stubFetch();
    vi.mocked(confirmAsync).mockResolvedValue(false);
    render(<LissageModal onFermer={() => {}} onApplique={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Calculer une proposition" }));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => screen.getByRole("button", { name: "Appliquer 2 déplacements" }));
    fireEvent.click(screen.getByRole("button", { name: "Appliquer 2 déplacements" }));

    await waitFor(() => expect(confirmAsync).toHaveBeenCalled());
    expect(appels.some((a) => a.url.includes("/appliquer"))).toBe(false);
  });
});
