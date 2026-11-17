/**
 * Référence → Réglages → Semaine type des enseignants (17/11/2026).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContexteDroits } from "../contexts/Droits";
import type { AppPayload } from "../types/app";
import { ReglagesReference, semaineEnVigueur } from "./ReglagesReference";

const CRENEAUX = ["8h-9h30", "9h30-11h", "11h-12h30", "14h-15h30", "15h30-17h", "17h-18h30"];
const KBR = {
  teacher_code: "KBR",
  origine: [[0, 0], [1, 0]],
  fixes: [],
  bloques: [],
  liberes: [],
  motif: "",
  demande_par: "",
};
const KNG = { ...KBR, teacher_code: "KNG", origine: [[4, 5]], fixes: [[4, 5]], bloques: [[2, 0]], motif: "Réunion" };
const REPONSE = {
  creneaux: CRENEAUX,
  jours: ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"],
  salles_reservees: [],
  indisponibilites: [],
  semaines_types: [KBR, KNG],
};
const PAYLOAD = {
  rooms: [],
  teacherLabels: { KBR: "Kyllian Bresson", KNG: "Kévin Ngo", TPA: "Thomas Pavie" },
} as unknown as AppPayload;

function stubFetch() {
  const appels: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      appels.push({ url: String(url), init });
      return Promise.resolve({ ok: true, json: async () => REPONSE });
    }),
  );
  return appels;
}

async function afficher(code: string) {
  render(
    <ContexteDroits.Provider value={{ role: "admin", revision: 1, apresEnregistrement: vi.fn() }}>
      <ReglagesReference payload={PAYLOAD} />
    </ContexteDroits.Provider>,
  );
  fireEvent.change(await screen.findByLabelText("Enseignant de la semaine type"), { target: { value: code } });
}

afterEach(() => vi.unstubAllGlobals());

describe("Semaine type des enseignants", () => {
  it("calcule la semaine en vigueur", () => {
    expect([...semaineEnVigueur({ ...KBR, liberes: [[0, 0]], bloques: [[4, 3]] } as never)].sort()).toEqual([
      "1-0",
      "4-3",
    ]);
    expect(semaineEnVigueur(undefined).size).toBe(0);
  });

  it("montre la semaine d’origine et enregistre la semaine voulue, avec un motif", async () => {
    const appels = stubFetch();
    await afficher("KBR");
    expect(screen.getByLabelText("Lundi 8h-9h30 indisponible")).toBeChecked();
    expect(screen.getByLabelText("Mercredi 8h-9h30 indisponible")).not.toBeChecked();
    expect(screen.getByText(/2 créneaux indisponibles par semaine/)).toBeInTheDocument();
    const bouton = screen.getByRole("button", { name: "Enregistrer la semaine" });
    expect(bouton).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Lundi 8h-9h30 indisponible"));
    fireEvent.click(screen.getByLabelText("Vendredi 17h-18h30 indisponible"));
    expect(bouton).toBeDisabled(); // pas encore de motif
    fireEvent.change(screen.getByLabelText("Motif de la semaine type"), { target: { value: "Demande du 17/11" } });
    fireEvent.click(bouton);
    await waitFor(() => expect(appels.some((a) => a.init?.method === "PUT")).toBe(true));
    const envoi = appels.find((a) => a.init?.method === "PUT")!;
    expect(envoi.url).toContain("/reglages/semaines-types/KBR");
    const corps = JSON.parse(String(envoi.init?.body));
    expect(corps.motif).toBe("Demande du 17/11");
    expect(corps.indisponibles.map((c: number[]) => c.join("-")).sort()).toEqual(["1-0", "4-5"]);
  });

  it("grise les créneaux hors de la liste déclarée et propose de revenir à l’origine", async () => {
    const appels = stubFetch();
    await afficher("KNG");
    expect(screen.getByText(/Semaine modifiée ici pour : Kévin Ngo \(KNG\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Vendredi 17h-18h30 indisponible")).toBeDisabled();
    expect(screen.getByLabelText("Mercredi 8h-9h30 indisponible")).toBeChecked();
    expect(screen.getByLabelText("Motif de la semaine type")).toHaveValue("Réunion");
    fireEvent.click(screen.getByRole("button", { name: "Revenir à la semaine d’origine" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    expect(appels.find((a) => a.init?.method === "DELETE")!.url).toContain("/reglages/semaines-types/KNG");
  });

  it("part d’une semaine vide pour un enseignant sans contrainte connue", async () => {
    stubFetch();
    await afficher("TPA");
    expect(screen.getByText(/Disponible toute la semaine/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revenir à la semaine d’origine" })).toBeNull();
  });
});
