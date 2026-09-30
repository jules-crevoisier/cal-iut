/**
 * « Nouvel intervenant » dans la Vue Enseignant (30/09/2026) : le bouton de
 * l'annuaire (administrateurs seulement), l'ouverture de la fiche annoncée
 * « Intervenant créé », la mention « ajouté dans l'appli » et « Supprimer »
 * sans séance.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import { catalogTeacher, emptyPayload, placedRow, testRoute } from "../test/payloadFixture";
import { confirmAsync } from "../utils/confirmDialog";
import { marquerIntervenantCree, oublierIntervenantCree } from "../utils/intervenantCree";
import { EnseignantView } from "./EnseignantView";

vi.mock("../utils/confirmDialog", () => ({ confirmAsync: vi.fn() }));

function avecDroits(role: RoleCompte | null, apresEnregistrement = vi.fn()) {
  return ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 1, apresEnregistrement }}>{children}</ContexteDroits.Provider>
  );
}

function reponse(status: number, corps: unknown) {
  return Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => corps });
}

const base = emptyPayload({
  teacherLabels: { KBR: "Lefèvre Kevin", ZMA: "Zoé Martin" },
  teachers: [catalogTeacher("KBR", "Lefèvre Kevin")],
  intervenantsAppli: {
    ZMA: { nom: "Zoé Martin", cree_le: "2026-09-30T08:15:00+00:00", cree_par: "admin@iut.test", nb_seances: 0 },
  },
});

describe("EnseignantView — Nouvel intervenant", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.mocked(confirmAsync).mockReset();
    oublierIntervenantCree();
  });

  it("le bouton de l'annuaire est réservé aux administrateurs", () => {
    const { unmount } = render(<EnseignantView payload={base} route={testRoute({ vue: "prof" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("edit"),
    });
    expect(screen.queryByRole("button", { name: "Nouvel intervenant" })).not.toBeInTheDocument();
    unmount();
    render(<EnseignantView payload={base} route={testRoute({ vue: "prof" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("admin"),
    });
    fireEvent.click(screen.getByRole("button", { name: "Nouvel intervenant" }));
    expect(screen.getByRole("dialog", { name: "Nouvel intervenant" })).toBeInTheDocument();
    expect(screen.getByText(/Réservé aux administrateurs/)).toBeInTheDocument();
  });

  it("après création : ouvre sa fiche et annonce « Intervenant créé »", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const corps = JSON.parse(String(init?.body ?? "{}"));
        if (url.endsWith("/verifier")) {
          return reponse(200, { ...corps, email: null, code_celcat: null, erreurs: [], avertissements: [], suggestion_code: null, peut_creer: true });
        }
        return reponse(201, { code: "PNO", nom: "Paul Nouveau", email: null, code_celcat: null, cree_le: "", avertissements_confirmes: [], message: "Intervenant créé.", revision: 5 });
      }),
    );
    const setRoute = vi.fn();
    const apres = vi.fn();
    render(<EnseignantView payload={base} route={testRoute({ vue: "prof" })} setRoute={setRoute} />, {
      wrapper: avecDroits("admin", apres),
    });
    fireEvent.click(screen.getByRole("button", { name: "Nouvel intervenant" }));
    fireEvent.change(screen.getByLabelText("Nom complet"), { target: { value: "Paul Nouveau" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "pno" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));
    await waitFor(() => expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "PNO" }));
    expect(apres).toHaveBeenCalled();
  });

  it("fiche tout juste créée : ni « introuvable » pendant le rechargement, puis l'annonce", () => {
    marquerIntervenantCree("PNO");
    const route = testRoute({ vue: "prof", prof: "PNO" });
    const { rerender } = render(<EnseignantView payload={base} route={route} setRoute={vi.fn()} />, {
      wrapper: avecDroits("admin"),
    });
    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Intervenant créé — ouverture de sa fiche");
    const recharge = emptyPayload({
      ...base,
      teacherLabels: { ...base.teacherLabels, PNO: "Paul Nouveau" },
      intervenantsAppli: { ...base.intervenantsAppli, PNO: { nom: "Paul Nouveau", cree_le: "2026-09-30T09:00:00+00:00", cree_par: "admin@iut.test", nb_seances: 0 } },
    });
    rerender(<EnseignantView payload={recharge} route={route} setRoute={vi.fn()} />);
    expect(screen.getByText("Intervenant créé : Paul Nouveau (PNO).")).toBeInTheDocument();
  });

  it("mention « ajouté dans l'appli » : l'auteur pour un admin, « Supprimer » sans séance", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(true);
    const fetchMock = vi.fn(() => reponse(200, { famille: "enseignant", cle: "ZMA", valeurs: { nom: "Zoé Martin" }, message: "Zoé Martin supprimé.", revision: 7 }));
    vi.stubGlobal("fetch", fetchMock);
    const setRoute = vi.fn();
    const apres = vi.fn();
    render(<EnseignantView payload={base} route={testRoute({ vue: "prof", prof: "ZMA" })} setRoute={setRoute} />, {
      wrapper: avecDroits("admin", apres),
    });
    expect(screen.getByText(/ajouté dans l’appli par admin@iut\.test le 30\/09/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(apres).toHaveBeenCalled());
    expect(confirmAsync).toHaveBeenCalledWith(expect.stringContaining("Zoé Martin (ZMA)"), expect.objectContaining({ variant: "danger" }));
    expect(fetchMock).toHaveBeenCalledWith("/reference/enseignants/ZMA", expect.objectContaining({ method: "DELETE" }));
    expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "" });
  });

  it("sans « Supprimer » pour un non-admin ou dès qu'il a une séance ; l'auteur reste aux admins", () => {
    const { unmount } = render(<EnseignantView payload={base} route={testRoute({ vue: "prof", prof: "ZMA" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("edit"),
    });
    expect(screen.getByText("ajouté dans l’appli le 30/09")).toBeInTheDocument();
    expect(screen.queryByText(/admin@iut\.test/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supprimer" })).not.toBeInTheDocument();
    unmount();
    const avecSeance = emptyPayload({ ...base, rows: [placedRow({ id: "1", te: ["ZMA"] })] });
    render(<EnseignantView payload={avecSeance} route={testRoute({ vue: "prof", prof: "ZMA" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("admin"),
    });
    expect(screen.getByText(/ajouté dans l’appli par/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supprimer" })).not.toBeInTheDocument();
  });

  it("dans l'annuaire, il apparaît comme les autres (contrainte « aucune »)", () => {
    render(<EnseignantView payload={base} route={testRoute({ vue: "prof" })} setRoute={vi.fn()} />, {
      wrapper: avecDroits("admin"),
    });
    const ligne = screen.getByRole("button", { name: "Zoé Martin" }).closest("tr")!;
    expect(ligne.querySelector(".col-etat")).toHaveTextContent("—");
    expect(ligne.querySelector(".annuaire-code")).toHaveTextContent("ZMA");
  });
});
