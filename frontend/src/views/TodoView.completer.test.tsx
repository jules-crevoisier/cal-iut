/**
 * « À traiter » → « Données à compléter » (29/09/2026) : une tuile avec son
 * compteur, une section groupée par famille, un champ en ligne sur chaque
 * donnée que ce compte peut compléter, sinon qui le peut et où. Les séances
 * sans salle ont déjà leur section : une ligne de renvoi seulement.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Manque } from "../api/client";
import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import { emptyPayload } from "../test/payloadFixture";
import { TodoView } from "./TodoView";

function manque(p: Partial<Manque> & Pick<Manque, "famille" | "cle" | "champ">): Manque {
  return {
    id: `${p.famille}:${p.cle}:${p.champ}`,
    libelle: p.cle,
    champ_libelle: "Adresse mail",
    gravite: "cosmetique",
    usage: "1 séance placée",
    nb_seances: 1,
    role_requis: "edit",
    ou_completer: "",
    ecran: {},
    ...p,
  };
}

const MANQUES: Manque[] = [
  manque({ famille: "enseignant", cle: "KBR", libelle: "Kyllian Bresson", champ: "email", gravite: "bloque_envoi_liens" }),
  manque({
    famille: "salle", cle: "h018", libelle: "H.018", champ: "code_celcat", champ_libelle: "Correspondance Celcat",
    gravite: "bloque_celcat", role_requis: "admin",
  }),
  manque({
    famille: "groupe", cle: "BUT MMI S5 TD EF", champ: "id_celcat", champ_libelle: "Identifiant Celcat",
    gravite: "bloque_celcat", role_requis: null,
    ou_completer: "data/config/celcat_groupes.yaml : identifiant à relever dans Celcat — déploiement.",
  }),
  manque({ famille: "seance", cle: "s1", champ: "salle", champ_libelle: "Salle", gravite: "bloque_celcat", ecran: { vue: "promo", sem: 1, jour: 0 } }),
];

function stubFetch() {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    const u = String(url);
    const ok = (corps: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => corps });
    if (u.startsWith("/reference/manques")) return ok({ revision: 1, modifie_le: "", total: 4, par_gravite: {}, par_famille: {}, manques: MANQUES });
    if (u.startsWith("/reference/")) return ok({ famille: "enseignant", cle: "KBR", valeurs: {}, message: "ok", revision: 2 });
    if (u.startsWith("/controles/doublons/hebdo")) return ok({ dernier: null });
    if (u.startsWith("/controles/doublons")) return ok({ doublons: [] });
    return ok({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function rendre(role: RoleCompte, setRoute = vi.fn(), apresEnregistrement = vi.fn()) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 1, apresEnregistrement }}>{children}</ContexteDroits.Provider>
  );
  render(<TodoView payload={emptyPayload()} setRoute={setRoute} />, { wrapper });
  return { setRoute, apresEnregistrement };
}

function section(): HTMLElement {
  return screen.getByRole("heading", { name: "Données à compléter" }).closest("section") as HTMLElement;
}

describe("TodoView — Données à compléter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("compte les données de référence dans une tuile et les groupe par famille", async () => {
    stubFetch();
    rendre("edit");
    const tuile = await screen.findByRole("button", { name: /À compléter/ });
    await waitFor(() => expect(within(tuile).getByText("3")).toBeInTheDocument());

    const corps = section();
    expect(within(corps).getByLabelText("3 données")).toBeInTheDocument();
    expect(within(corps).getByText("Enseignants")).toBeInTheDocument();
    expect(within(corps).getByText("Salles")).toBeInTheDocument();
    expect(within(corps).getByText("Groupes (Celcat)")).toBeInTheDocument();
    expect(within(corps).getByText("bloque l'envoi du lien")).toBeInTheDocument();
    // La séance sans salle : une ligne de renvoi, pas une ligne de plus.
    expect(within(corps).getByText(/1 séance placée sans salle/)).toBeInTheDocument();
  });

  it("complète un mail en ligne (rôle edit) et prévient l'appli", async () => {
    const fetchMock = stubFetch();
    const { apresEnregistrement } = rendre("edit");
    const corps = section();
    fireEvent.click(await within(corps).findByRole("button", { name: "Ajouter — Adresse mail de Kyllian Bresson" }));
    const champ = within(corps).getByRole("textbox", { name: "Adresse mail de Kyllian Bresson" });
    fireEvent.change(champ, { target: { value: "kyllian.bresson@univ-reims.fr" } });
    fireEvent.click(within(corps).getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(within(corps).getByText("Enregistré")).toBeInTheDocument());
    const appel = fetchMock.mock.calls.find(([u]) => String(u) === "/reference/enseignants/KBR/contact");
    expect(appel?.[1]?.method).toBe("PUT");
    expect(apresEnregistrement).toHaveBeenCalled();
  });

  it("réserve la correspondance Celcat aux admins et dit où compléter un identifiant Celcat", async () => {
    stubFetch();
    rendre("edit");
    const corps = section();
    await within(corps).findByText("H.018");
    const ligneSalle = within(corps).getByText("H.018").closest("li")!;
    expect(within(ligneSalle).getByText("Réservé aux administrateurs.")).toBeInTheDocument();
    expect(within(ligneSalle).queryByRole("button", { name: /Ajouter/ })).not.toBeInTheDocument();
    const ligneGroupe = within(corps).getByText("BUT MMI S5 TD EF").closest("li")!;
    expect(within(ligneGroupe).getByText(/celcat_groupes\.yaml/)).toBeInTheDocument();
  });

  it("un admin complète la salle en ligne ou ouvre l'écran Celcat", async () => {
    stubFetch();
    const { setRoute } = rendre("admin");
    const corps = section();
    await within(corps).findByText("H.018");
    const ligneSalle = within(corps).getByText("H.018").closest("li")!;
    expect(within(ligneSalle).getByRole("button", { name: "Ajouter — Correspondance Celcat de H.018" })).toBeInTheDocument();
    fireEvent.click(within(ligneSalle).getByRole("button", { name: /Écran Celcat/ }));
    expect(setRoute).toHaveBeenCalledWith({ vue: "celcat" });
  });

  it("lecture seule : les manques restent listés, sans aucun bouton pour compléter", async () => {
    stubFetch();
    rendre("read_only");
    const corps = section();
    await within(corps).findByText("Kyllian Bresson");
    expect(within(corps).queryByRole("button", { name: /^Ajouter/ })).not.toBeInTheDocument();
    expect(within(corps).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(corps).getByText("H.018")).toBeInTheDocument();
  });
});
