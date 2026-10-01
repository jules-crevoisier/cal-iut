/**
 * « Enseignants & vacataires » (01/10/2026) — une seule source : le type
 * et le nom de `payload.teacherIdentites` se retrouvent dans l'annuaire de
 * la Vue Enseignant (avec un filtre par type), dans « Liens & partage » et
 * dans le bandeau de la fiche ; le téléphone, lui, n'y paraît que pour un
 * compte qui peut modifier. « Nouvel intervenant » accepte téléphone et
 * type.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NouvelIntervenantModal } from "../components/NouvelIntervenantModal";
import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import { oublierAnnuaireEnseignants } from "../hooks/useAnnuaireEnseignants";
import { catalogTeacher, emptyPayload, placedRow, testRoute } from "../test/payloadFixture";
import { AnnuaireEnseignants } from "./Annuaires";
import { EnseignantView } from "./EnseignantView";
import { ReferenceView } from "./ReferenceView";

const payload = emptyPayload({
  teacherLabels: { KBR: "Kyllian Bresson", MNI: "Marc Nino", APE: "Anne-Laure Perrone" },
  teacherIdentites: {
    KBR: { prenom: "Kyllian", nom: "BRESSON", type: "enseignant" },
    MNI: { prenom: "Marc", nom: "NINO", type: "vacataire" },
    APE: { prenom: "Anne-Laure", nom: "PERRONE", type: null },
  },
  teachers: [catalogTeacher("KBR", "Kyllian Bresson")],
  rows: [placedRow({ id: "1", te: ["KBR"] }), placedRow({ id: "2", te: ["MNI"] })],
});

function avecDroits(role: RoleCompte | null) {
  return ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 7, apresEnregistrement: vi.fn() }}>{children}</ContexteDroits.Provider>
  );
}

function reponse(status: number, corps: unknown) {
  return Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => corps });
}

afterEach(() => {
  vi.unstubAllGlobals();
  oublierAnnuaireEnseignants();
});

describe("Une seule source pour le type", () => {
  it("annuaire de la Vue Enseignant : pastille du type, filtre par type", () => {
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />);
    const ligneMni = screen.getByRole("button", { name: "Marc Nino" }).closest("tr")!;
    expect(within(ligneMni).getByText("Vacataire")).toBeInTheDocument();
    const type = screen.getByRole("combobox", { name: "Type" });
    fireEvent.change(type, { target: { value: "vacataire" } });
    expect(screen.queryByRole("button", { name: "Kyllian Bresson" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Marc Nino" })).toBeInTheDocument();
    fireEvent.change(type, { target: { value: "a-preciser" } });
    expect(screen.getByRole("button", { name: "Anne-Laure Perrone" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Marc Nino" })).not.toBeInTheDocument();
    fireEvent.change(type, { target: { value: "enseignant" } });
    expect(screen.getByRole("button", { name: "Kyllian Bresson" })).toBeInTheDocument();
  });

  it("« Liens & partage » : même libellé, même type", () => {
    render(<ReferenceView payload={payload} setRoute={vi.fn()} route={{ vue: "reference", onglet: "liens" }} />, {
      wrapper: avecDroits("edit"),
    });
    const ligne = screen.getByText("Marc Nino").closest("tr")!;
    expect(within(ligne).getByText("Vacataire")).toBeInTheDocument();
    expect(within(screen.getByText("Kyllian Bresson").closest("tr")!).getByText("Enseignant")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filtrer l'annuaire"), { target: { value: "vacataire" } });
    expect(screen.queryByText("Kyllian Bresson")).not.toBeInTheDocument();
  });

  it("sans `teacherIdentites` (serveur plus ancien) : prénom / nom déduits, type inconnu", () => {
    const ancien = emptyPayload({ teacherLabels: { TCA: "Thomas CASTELLENGO" } });
    render(<AnnuaireEnseignants payload={ancien} displayWeek={0} onOuvrir={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Thomas CASTELLENGO" })).toBeInTheDocument();
    expect(screen.queryByText("Vacataire")).not.toBeInTheDocument();
  });
});

describe("Fiche enseignant : type et téléphone dans le bandeau", () => {
  function stubAnnuaire() {
    const fetchMock = vi.fn((url: string) =>
      String(url) === "/reference/enseignants"
        ? reponse(200, {
            revision: 7,
            peut_modifier: true,
            admin: false,
            telephone_visible: true,
            compteurs: {},
            lignes: [{ code: "MNI", telephone: "+33612345678", telephone_affiche: "06 12 34 56 78" }],
          })
        : reponse(200, {}),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("compte « edit » : type et téléphone (lien tel:)", async () => {
    stubAnnuaire();
    render(<EnseignantView payload={payload} route={testRoute({ vue: "prof", prof: "MNI" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("edit"),
    });
    expect(screen.getByText("Vacataire")).toBeInTheDocument();
    const tel = await screen.findByText("06 12 34 56 78");
    expect(tel.closest("a")).toHaveAttribute("href", "tel:+33612345678");
  });

  it("lecture seule : le type, sans téléphone ni requête", async () => {
    const fetchMock = stubAnnuaire();
    render(<EnseignantView payload={payload} route={testRoute({ vue: "prof", prof: "MNI" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("read_only"),
    });
    expect(screen.getByText("Vacataire")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("06 12 34 56 78")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u) === "/reference/enseignants")).toBe(false);
  });
});

describe("Nouvel intervenant : téléphone et type", () => {
  it("refuse un téléphone invalide, envoie téléphone et type", async () => {
    const corpsEnvoyes: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const corps = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        corpsEnvoyes.push({ url, ...corps });
        if (String(url).endsWith("/verifier")) {
          return reponse(200, { ...corps, email: null, code_celcat: null, erreurs: [], avertissements: [], suggestion_code: null, peut_creer: true });
        }
        return reponse(201, { code: "ZMA", nom: "Zoé Martin", email: null, code_celcat: null, cree_le: "", avertissements_confirmes: [], message: "Intervenant créé.", revision: 5 });
      }),
    );
    const onCreated = vi.fn();
    render(<NouvelIntervenantModal onCreated={onCreated} onCancel={vi.fn()} onVoirFiche={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Nom complet"), { target: { value: "Zoé Martin" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "zma" } });
    const tel = screen.getByLabelText("Téléphone (facultatif)");
    fireEvent.change(tel, { target: { value: "06 12" } });
    fireEvent.blur(tel);
    expect(screen.getByText(/Numéro invalide/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));
    expect(onCreated).not.toHaveBeenCalled();
    fireEvent.change(tel, { target: { value: "06 12 34 56 78" } });
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "vacataire" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    const creation = corpsEnvoyes.find((c) => c.url === "/reference/enseignants");
    expect(creation).toMatchObject({ telephone: "06 12 34 56 78", type: "vacataire", code: "ZMA" });
  });
});
