/**
 * Nouveau semestre → Cours hors maquette (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CoursHorsMaquette, volumeLisible } from "./CoursHorsMaquette";

const REPONSE = {
  semestre_group: "even",
  verrouille: null as string | null,
  semestres: { S2: ["BUT1"], S4: ["BUT2-CREACOM-FC", "BUT2-DEV-FI"] },
  enseignants: [{ code: "VMA", nom: "MARIOT", prenom: "VALERIE", libelle: "Valerie MARIOT" }],
  cours: [
    { id: "abc", origine: "ajoutee", code: "WX2ATEL", nom: "Atelier", semestre: "S2", parcours: "BUT1", teacher_code: "VMA", cm: 1, td: 2, tp: 0 },
    { id: null, origine: "livree", code: "WX2BU", nom: "BU", semestre: "S2", parcours: "BUT1", teacher_code: "VMA", cm: 0, td: 3, tp: 0 },
  ],
  seances_maxi: 60,
};

function stubFetch(reponse = REPONSE) {
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

describe("Cours hors maquette", () => {
  it("écrit le volume en clair", () => {
    expect(volumeLisible({ cm: 1, td: 2, tp: 0 })).toBe("1 CM, 2 TD");
    expect(volumeLisible({ cm: 0, td: 0, tp: 0 })).toBe("");
  });

  it("liste les modules et n’offre le retrait que pour ceux saisis à l’écran", async () => {
    const appels = stubFetch();
    vi.stubGlobal("confirm", () => true);
    const onModifie = vi.fn();
    render(<CoursHorsMaquette groupe="even" onModifie={onModifie} />);
    expect(await screen.findByText(/2 modules : WX2ATEL, WX2BU/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retirer le module WX2BU" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retirer le module WX2ATEL" }));
    await waitFor(() => expect(onModifie).toHaveBeenCalled());
    expect(appels.find((a) => a.init?.method === "DELETE")?.url).toContain("/generations/cours-hors-maquette/even/abc");
  });

  it("ajoute un module, la promotion étant choisie d’office quand il n’y en a qu’une", async () => {
    const appels = stubFetch();
    render(<CoursHorsMaquette groupe="even" onModifie={vi.fn()} />);
    const ajouter = await screen.findByRole("button", { name: "Ajouter ce module" });
    expect(ajouter).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Code du module"), { target: { value: "wx2photo" } });
    fireEvent.change(screen.getByLabelText("Intitulé"), { target: { value: "Atelier photo" } });
    fireEvent.change(screen.getByLabelText("Semestre"), { target: { value: "S2" } });
    expect(screen.getByLabelText("Promotion")).toHaveValue("BUT1");
    fireEvent.change(screen.getByLabelText("Enseignant"), { target: { value: "VMA" } });
    expect(ajouter).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Séances de TD"), { target: { value: "2" } });
    fireEvent.click(ajouter);
    await waitFor(() => expect(appels.some((a) => a.init?.method === "POST")).toBe(true));
    expect(JSON.parse(String(appels.find((a) => a.init?.method === "POST")?.init?.body))).toEqual({
      code: "WX2PHOTO",
      nom: "Atelier photo",
      semestre: "S2",
      parcours: "BUT1",
      teacher_code: "VMA",
      teacher_nom: "MARIOT",
      teacher_prenom: "VALERIE",
      cm: 0,
      td: 2,
      tp: 0,
    });
  });

  it("n’offre ni ajout ni retrait quand le semestre est en service", async () => {
    stubFetch({ ...REPONSE, verrouille: "Le semestre pair est déjà en service." });
    render(<CoursHorsMaquette groupe="even" onModifie={vi.fn()} />);
    expect(await screen.findByText("Le semestre pair est déjà en service.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ajouter ce module" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Retirer le module/ })).toBeNull();
  });
});
