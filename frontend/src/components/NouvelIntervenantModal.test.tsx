/**
 * « Nouvel intervenant » (30/09/2026) : la modale valide la forme en direct,
 * affiche les garde-fous du serveur (cas réel : « Anne Grenet » sous AGR avec
 * le code Celcat 3233), ne confirme jamais à l'aveugle, et rend la main à
 * l'écran une fois l'intervenant créé.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AvertissementIntervenant, VerificationIntervenant } from "../api/client";
import { erreursDeSaisie, normaliserCode, NouvelIntervenantModal } from "./NouvelIntervenantModal";

function reponse(status: number, corps: unknown) {
  return Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => corps });
}

const AGR_CELCAT: AvertissementIntervenant = {
  type: "code_dans_celcat",
  titre: "AGR est Gram AMBROISE dans Celcat",
  message: "celcat.yaml associe déjà AGR à Gram AMBROISE (identifiant Celcat 38321)…",
  code_existant: "AGR",
  nom_existant: "Gram AMBROISE",
  fiche: false,
  bloquant: false,
};
const CELCAT_PRIS: AvertissementIntervenant = {
  type: "code_celcat_pris",
  titre: "3233 est déjà AGT (GRENET ANNE)",
  message: "Ce code Celcat est déjà celui de AGT (GRENET ANNE) — c'est peut-être la même personne ?",
  code_existant: "AGT",
  nom_existant: "GRENET ANNE",
  fiche: true,
  bloquant: true,
};
const NOM_PROCHE: AvertissementIntervenant = {
  type: "nom_proche",
  titre: "Cette personne existe peut-être déjà sous le code AGT",
  message: "Anne GRENET (AGT) est déjà dans l'appli.",
  code_existant: "AGT",
  nom_existant: "Anne GRENET",
  fiche: true,
  bloquant: false,
};

function verification(corps: { nom?: string; code?: string; code_celcat?: string }, avertissements: AvertissementIntervenant[]): VerificationIntervenant {
  return {
    code: corps.code ?? "",
    nom: corps.nom ?? "",
    email: null,
    code_celcat: corps.code_celcat || null,
    erreurs: [],
    avertissements,
    suggestion_code: "AGN",
    peut_creer: !avertissements.some((a) => a.bloquant),
  };
}

function saisir(nom: string, code: string, celcat = "") {
  fireEvent.change(screen.getByLabelText("Nom complet"), { target: { value: nom } });
  fireEvent.change(screen.getByLabelText("Code"), { target: { value: code } });
  if (celcat) fireEvent.change(screen.getByLabelText("Code Celcat (facultatif)"), { target: { value: celcat } });
}

describe("NouvelIntervenantModal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("valide la forme en direct, sans appeler la création", () => {
    expect(normaliserCode(" agé ")).toBe("AGE");
    expect(erreursDeSaisie({ nom: "", code: "A1", codeCelcat: "abc", email: "x@" })).toEqual({
      nom: expect.stringContaining("obligatoire"),
      code: expect.stringContaining("2 à 4 lettres"),
      code_celcat: expect.stringContaining("Un nombre"),
      email: expect.stringContaining("Adresse mail invalide"),
    });
    const fetchMock = vi.fn(() => reponse(200, verification({}, [])));
    vi.stubGlobal("fetch", fetchMock);
    render(<NouvelIntervenantModal onCreated={vi.fn()} onCancel={vi.fn()} onVoirFiche={vi.fn()} />);
    fireEvent.submit(screen.getByRole("dialog"));
    expect(screen.getByLabelText("Nom complet")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Le code est obligatoire/)).toBeInTheDocument();
    const code = screen.getByLabelText("Code");
    fireEvent.change(code, { target: { value: "ab1" } });
    expect(code).toHaveValue("AB1");
    expect(screen.getByText(/sans chiffre ni accent/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([url]) => String(url).endsWith("/verifier"))).toBe(true);
  });

  it("cas réel Anne Grenet AGR 3233 : avertissements, lien vers AGT, pas de création à l'aveugle", async () => {
    const creations: unknown[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const corps = JSON.parse(String(init?.body ?? "{}"));
      if (url.endsWith("/verifier")) {
        const liste = corps.code_celcat ? [AGR_CELCAT, CELCAT_PRIS, NOM_PROCHE] : [AGR_CELCAT, NOM_PROCHE];
        return reponse(200, verification(corps, liste));
      }
      creations.push(corps);
      return reponse(201, { code: "AGR", nom: "Anne Grenet", email: null, code_celcat: null, cree_le: "2026-09-30T10:00:00+00:00", avertissements_confirmes: [AGR_CELCAT, NOM_PROCHE], message: "Intervenant créé.", revision: 9 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onCreated = vi.fn();
    const onVoirFiche = vi.fn();
    render(<NouvelIntervenantModal onCreated={onCreated} onCancel={vi.fn()} onVoirFiche={onVoirFiche} />);
    saisir("Anne Grenet", "agr", "3233");

    await waitFor(() => expect(screen.getByText("3233 est déjà AGT (GRENET ANNE)")).toBeInTheDocument());
    expect(screen.getByText("AGR est Gram AMBROISE dans Celcat")).toBeInTheDocument();
    expect(screen.getByText("Cette personne existe peut-être déjà sous le code AGT")).toBeInTheDocument();
    expect(screen.getByText("À corriger avant de créer")).toBeInTheDocument();
    // Doublon de code Celcat : ni « Créer », ni « Créer quand même ».
    expect(screen.getByRole("button", { name: "Créer" })).toBeDisabled();

    fireEvent.click(screen.getAllByRole("button", { name: "Voir sa fiche (AGT)" })[0]);
    expect(onVoirFiche).toHaveBeenCalledWith("AGT");

    fireEvent.click(screen.getByRole("button", { name: "Retirer le code Celcat" }));
    expect(screen.getByLabelText("Code Celcat (facultatif)")).toHaveValue("");
    await waitFor(() => expect(screen.queryByText("3233 est déjà AGT (GRENET ANNE)")).not.toBeInTheDocument());
    expect(screen.getByText("À vérifier avant de créer")).toBeInTheDocument();
    const creerQuandMeme = screen.getByRole("button", { name: "Créer quand même" });
    expect(creerQuandMeme).toBeEnabled();
    fireEvent.click(creerQuandMeme);

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(creations).toEqual([{ nom: "Anne Grenet", code: "AGR", code_celcat: "", email: "", telephone: "", type: "", confirmer: true }]);
  });

  it("sans avertissement : « Créer », sans confirmation", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const corps = JSON.parse(String(init?.body ?? "{}"));
      if (url.endsWith("/verifier")) return reponse(200, verification(corps, []));
      return reponse(201, { ...corps, code: "ZMA", cree_le: "", avertissements_confirmes: [], message: "Intervenant créé.", revision: 3 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onCreated = vi.fn();
    render(<NouvelIntervenantModal onCreated={onCreated} onCancel={vi.fn()} onVoirFiche={vi.fn()} />);
    saisir("Zoé Martin", "zma");
    fireEvent.change(screen.getByLabelText("Mail (facultatif)"), { target: { value: "zoe@univ.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ code: "ZMA" })));
    const creation = fetchMock.mock.calls.find(([url]) => url === "/reference/enseignants");
    expect(JSON.parse(String(creation?.[1]?.body))).toMatchObject({ code: "ZMA", confirmer: false, email: "zoe@univ.test" });
  });

  it("un refus à avertissements (vérification pas encore arrivée) les affiche et demande confirmation", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/verifier")) return new Promise(() => undefined); // jamais arrivée
      return reponse(409, { detail: { message: "À vérifier…", avertissements: [NOM_PROCHE], suggestion_code: null } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onCreated = vi.fn();
    render(<NouvelIntervenantModal onCreated={onCreated} onCancel={vi.fn()} onVoirFiche={vi.fn()} />);
    saisir("Anne Grenet", "AGN");
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));
    await waitFor(() => expect(screen.getByText(NOM_PROCHE.titre)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Créer quand même" })).toBeEnabled();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("Échap ferme la modale", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    const onCancel = vi.fn();
    render(<NouvelIntervenantModal onCreated={vi.fn()} onCancel={onCancel} onVoirFiche={vi.fn()} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });
});
