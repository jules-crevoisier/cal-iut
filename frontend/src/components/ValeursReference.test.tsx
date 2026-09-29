/**
 * Corriger une valeur présente (29/09/2026) : crayon « Modifier » (même champ
 * en ligne, prérempli), marque « modifiée dans l'appli » avec la valeur du
 * fichier, « Revenir à la valeur du fichier » (DELETE). Lecture seule : la
 * valeur et la marque, sans crayon ni retour.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import type { SurchargeReference } from "../types/app";
import { EmailEnseignant, ModifierIntituleCours, ModifierNomEnseignant } from "./ValeursReference";

const SURCHARGE: SurchargeReference = {
  valeur: "k.bresson@univ-reims.fr",
  origine: "kyllian.bresson@univ-reims.fr",
  modifie_le: "2026-09-29T10:00:00+00:00",
  modifie_par: "jules@iut.test",
};

function avecDroits(role: RoleCompte | null, apresEnregistrement = vi.fn()) {
  return ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 1, apresEnregistrement }}>{children}</ContexteDroits.Provider>
  );
}

function stub() {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve({ ok: true, status: 200, json: async () => ({ famille: "enseignant", cle: "KBR", valeurs: {}, message: "ok", revision: 2 }) }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("EmailEnseignant — corriger une adresse présente", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("« Modifier » ouvre le champ prérempli et enregistre (PUT), Échap annule", async () => {
    const fetchMock = stub();
    const apres = vi.fn();
    render(
      <EmailEnseignant code="KBR" nom="Kyllian Bresson" email="kyllian.bresson@univ-reims.fr" affichage={<span>kyllian.bresson@univ-reims.fr</span>} />,
      { wrapper: avecDroits("edit", apres) },
    );
    const crayon = screen.getByRole("button", { name: "Modifier — Adresse mail de Kyllian Bresson" });
    fireEvent.click(crayon);
    const champ = screen.getByRole("textbox", { name: "Adresse mail de Kyllian Bresson" });
    expect(champ).toHaveValue("kyllian.bresson@univ-reims.fr");
    expect(champ).toHaveFocus();
    fireEvent.keyDown(champ, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Modifier — Adresse mail de Kyllian Bresson" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Modifier — Adresse mail de Kyllian Bresson" }));
    const champ2 = screen.getByRole("textbox", { name: "Adresse mail de Kyllian Bresson" });
    fireEvent.change(champ2, { target: { value: "K.Bresson@Univ-Reims.fr" } });
    fireEvent.submit(champ2.closest("form")!);
    await waitFor(() => expect(screen.getByText("Enregistré")).toBeInTheDocument());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/reference/enseignants/KBR/contact");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "k.bresson@univ-reims.fr" });
    expect(apres).toHaveBeenCalled();
  });

  it("marque une valeur modifiée, montre la valeur du fichier et y revient (DELETE)", async () => {
    const fetchMock = stub();
    const apres = vi.fn();
    render(
      <EmailEnseignant code="KBR" nom="Kyllian Bresson" email={SURCHARGE.valeur} surcharge={SURCHARGE} affichage={<span>{SURCHARGE.valeur}</span>} />,
      { wrapper: avecDroits("edit", apres) },
    );
    const marque = screen.getByRole("button", { name: /modifiée dans l'appli\. Valeur du fichier : kyllian\.bresson@univ-reims\.fr/ });
    fireEvent.click(marque);
    expect(marque).toHaveAttribute("aria-expanded", "true");
    const bulle = screen.getByRole("group", { name: "Origine — Adresse mail de Kyllian Bresson" });
    // Épinglée au clic (ou Entrée) : le focus va sur le retour ; Échap la
    // ferme et rend le focus à la marque.
    expect(within(bulle).getByRole("button", { name: "Revenir à la valeur du fichier" })).toHaveFocus();
    fireEvent.keyDown(bulle, { key: "Escape" });
    expect(marque).toHaveFocus();
    expect(screen.queryByRole("group", { name: "Origine — Adresse mail de Kyllian Bresson" })).not.toBeInTheDocument();
    fireEvent.click(marque);
    const bulle2 = screen.getByRole("group", { name: "Origine — Adresse mail de Kyllian Bresson" });
    expect(within(bulle2).getByText("kyllian.bresson@univ-reims.fr")).toBeInTheDocument();
    expect(within(bulle2).getByText(/par jules@iut\.test/)).toBeInTheDocument();
    fireEvent.click(within(bulle2).getByRole("button", { name: "Revenir à la valeur du fichier" }));
    await waitFor(() => expect(apres).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/reference/enseignants/KBR/contact");
    expect(init?.method).toBe("DELETE");
    expect(await screen.findByText("valeur du fichier rétablie")).toBeInTheDocument();
  });

  it("lecture seule : la valeur et la marque, sans crayon ni retour", () => {
    render(
      <EmailEnseignant code="KBR" nom="Kyllian Bresson" email={SURCHARGE.valeur} surcharge={SURCHARGE} affichage={<span>{SURCHARGE.valeur}</span>} />,
      { wrapper: avecDroits("read_only") },
    );
    expect(screen.getByText(SURCHARGE.valeur)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Modifier/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /modifiée dans l'appli/ }));
    expect(screen.queryByRole("button", { name: "Revenir à la valeur du fichier" })).not.toBeInTheDocument();
  });
});

describe("Nom et intitulé", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("corrige un nom (PUT /reference/enseignants/{code})", async () => {
    const fetchMock = stub();
    render(<ModifierNomEnseignant code="APH" nom="Alexia Petit-Halajko" />, { wrapper: avecDroits("edit") });
    fireEvent.click(screen.getByRole("button", { name: "Modifier — Nom complet de APH" }));
    const champ = screen.getByRole("textbox", { name: "Nom complet de APH" });
    expect(champ).toHaveValue("Alexia Petit-Halajko");
    fireEvent.change(champ, { target: { value: "Alexia Petit Halajko" } });
    fireEvent.submit(champ.closest("form")!);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe("/reference/enseignants/APH");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ nom: "Alexia Petit Halajko" });
  });

  it("revient à l'intitulé de la maquette (DELETE /reference/cours/{code}/intitule)", async () => {
    const fetchMock = stub();
    render(
      <ModifierIntituleCours
        code="WR101"
        intitule="Culture numérique (S1)"
        surcharge={{ ...SURCHARGE, valeur: "Culture numérique (S1)", origine: "Culture numérique" }}
      />,
      { wrapper: avecDroits("edit") },
    );
    fireEvent.click(screen.getByRole("button", { name: /modifiée dans l'appli/ }));
    fireEvent.click(screen.getByRole("button", { name: "Revenir à la valeur du fichier" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe("/reference/cours/WR101/intitule");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
  });
});
