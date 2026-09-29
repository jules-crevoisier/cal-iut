/**
 * Compléter un mail manquant depuis l'annuaire des enseignants (29/09/2026,
 * « il faut pouvoir ajouter l'info et l'enregistrer ») : la pastille
 * « manquant » devient « Ajouter », qui ouvre un champ en ligne — Entrée
 * enregistre, Échap annule, l'erreur reste sous le champ, le succès est
 * annoncé. En lecture seule, le manque reste affiché, sans bouton.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import { emptyPayload, placedRow } from "../test/payloadFixture";
import { AnnuaireEnseignants } from "./Annuaires";

const payload = emptyPayload({
  teacherLabels: { AAA: "Abel Anne", BBB: "Brun Béa" },
  teacherEmails: { AAA: "anne@iut.test" },
  rows: [placedRow({ id: "1", te: ["BBB"], s: 0 })],
});

function avecDroits(role: RoleCompte | null, apresEnregistrement = vi.fn()) {
  return ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 1, apresEnregistrement }}>{children}</ContexteDroits.Provider>
  );
}

function reponse(status: number, corps: unknown) {
  return Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => corps });
}

const BOUTON = { name: "Ajouter — Adresse mail de Brun Béa" };

describe("AnnuaireEnseignants — compléter un mail manquant", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("enregistre l'adresse au clavier (Entrée), en minuscules, puis annonce le succès", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      reponse(200, { famille: "enseignant", cle: "BBB", valeurs: { email: "bea.brun@iut.test" }, message: "ok", revision: 2 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const apres = vi.fn();
    const onOuvrir = vi.fn();
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={onOuvrir} />, { wrapper: avecDroits("edit", apres) });

    fireEvent.click(screen.getByRole("button", BOUTON));
    const champ = screen.getByRole("textbox", { name: "Adresse mail de Brun Béa" });
    expect(champ).toHaveFocus();
    // Cliquer dans le champ n'ouvre pas la fiche (le champ vit dans la ligne).
    fireEvent.click(champ);
    expect(onOuvrir).not.toHaveBeenCalled();

    fireEvent.change(champ, { target: { value: " Bea.Brun@IUT.test " } });
    fireEvent.submit(champ.closest("form")!);

    await waitFor(() => expect(screen.getByText("Enregistré")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/reference/enseignants/BBB/contact");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "bea.brun@iut.test" });
    expect(apres).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Enregistré\. Adresse mail de Brun Béa : bea\.brun@iut\.test/)).toBeInTheDocument();
    // Retour tenu par l'annuaire : il reste même quand la ligne sort du filtre.
    expect(screen.getByText("Adresse de Brun Béa enregistrée : bea.brun@iut.test").closest("[aria-live]")).not.toBeNull();
  });

  it("refuse une adresse mal formée sans appeler le serveur", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />, { wrapper: avecDroits("edit") });
    fireEvent.click(screen.getByRole("button", BOUTON));
    const champ = screen.getByRole("textbox", { name: "Adresse mail de Brun Béa" });
    fireEvent.change(champ, { target: { value: "bea.brun" } });
    fireEvent.submit(champ.closest("form")!);
    expect(screen.getByRole("alert")).toHaveTextContent("Adresse invalide");
    expect(champ).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("garde le champ ouvert avec l'erreur du serveur (adresse déjà attribuée)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reponse(409, { detail: "L'adresse anne@iut.test est déjà celle de Abel Anne (AAA)." })));
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />, { wrapper: avecDroits("edit") });
    fireEvent.click(screen.getByRole("button", BOUTON));
    const champ = screen.getByRole("textbox", { name: "Adresse mail de Brun Béa" });
    fireEvent.change(champ, { target: { value: "anne@iut.test" } });
    fireEvent.submit(champ.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("déjà celle de Abel Anne");
    expect(screen.getByRole("textbox", { name: "Adresse mail de Brun Béa" })).toHaveValue("anne@iut.test");
    expect(screen.queryByText("Enregistré")).not.toBeInTheDocument();
  });

  it("Échap annule et rend le focus au bouton", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />, { wrapper: avecDroits("admin") });
    fireEvent.click(screen.getByRole("button", BOUTON));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Adresse mail de Brun Béa" }), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Adresse mail de Brun Béa" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", BOUTON)).toHaveFocus();
  });

  it.each([["read_only" as const], [null]])("lecture seule (%s) : le manque reste affiché, sans bouton", (role) => {
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />, { wrapper: avecDroits(role) });
    const ligne = screen.getByRole("button", { name: "Brun Béa" }).closest("tr")!;
    expect(within(ligne).getByText("manquant")).toBeInTheDocument();
    expect(screen.queryByRole("button", BOUTON)).not.toBeInTheDocument();
  });
});
