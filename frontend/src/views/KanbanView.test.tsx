/**
 * Kanban « Tâches » (22/09/2026) : colonnes + compteurs, déplacement par
 * bouton (→ change de colonne, appelle PATCH), contrôles masqués en lecture
 * seule, validation du formulaire de création.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Tache } from "../api/client";
import { emptyPayload } from "../test/payloadFixture";
import { KanbanView } from "./KanbanView";

function tache(overrides: Partial<Tache> & Pick<Tache, "id" | "titre">): Tache {
  return {
    description: null,
    colonne: "a_faire",
    ordre: 0,
    enseignant_code: null,
    concerne: null,
    categorie: "edt",
    priorite: "normale",
    date_debut: null,
    date_fin: null,
    cree_par: "prof@example.test",
    cree_le: "2026-09-22T08:00:00+00:00",
    maj_le: "2026-09-22T08:00:00+00:00",
    fait_le: null,
    ...overrides,
  };
}

const payload = emptyPayload({ teacherLabels: { KBR: "Kyllian Bresson" } });

function stubFetch(taches: Tache[] = []) {
  const appels: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const chemin = String(url);
      if (method === "GET" && chemin.startsWith("/taches")) {
        return Promise.resolve({ ok: true, json: async () => taches });
      }
      if (method === "POST" && chemin.startsWith("/taches")) {
        const body = JSON.parse(String(init?.body ?? "{}"));
        appels.push({ method, url: chemin, body });
        return Promise.resolve({
          ok: true,
          json: async () => tache({ id: 999, titre: body.titre ?? "", ...body }),
        });
      }
      const patchMatch = chemin.match(/^\/taches\/(\d+)$/);
      if (method === "PATCH" && patchMatch) {
        const body = JSON.parse(String(init?.body ?? "{}"));
        appels.push({ method, url: chemin, body });
        const base = taches.find((t) => t.id === Number(patchMatch[1]));
        return Promise.resolve({ ok: true, json: async () => ({ ...(base ?? tache({ id: Number(patchMatch[1]), titre: "" })), ...body }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }),
  );
  return appels;
}

describe("KanbanView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("renders the three columns with their counts", async () => {
    stubFetch([tache({ id: 1, titre: "Prévenir Kyllian", colonne: "a_faire" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Prévenir Kyllian")).toBeInTheDocument());
    expect(screen.getByText("À faire")).toBeInTheDocument();
    expect(screen.getByText("En cours")).toBeInTheDocument();
    expect(screen.getByText("Fait")).toBeInTheDocument();
    // Compteurs : 1 dans « À faire », 0 dans les deux autres.
    const colonneAFaire = screen.getByLabelText("Colonne À faire");
    expect(colonneAFaire).toHaveTextContent("1");
  });

  it("moves a card to the next column with the → button, calling PATCH", async () => {
    const appels = stubFetch([tache({ id: 1, titre: "Déplacer le TD de KBR", colonne: "a_faire" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Déplacer le TD de KBR")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Déplacer « Déplacer le TD de KBR » vers la colonne suivante" }));

    await waitFor(() => expect(appels.some((a) => a.method === "PATCH")).toBe(true));
    const patch = appels.find((a) => a.method === "PATCH");
    expect(patch?.url).toBe("/taches/1");
    expect((patch?.body as { colonne?: string })?.colonne).toBe("en_cours");
  });

  it("hides create/move/edit controls for a read_only role", async () => {
    stubFetch([tache({ id: 1, titre: "Carte visible" })]);
    render(<KanbanView payload={payload} role="read_only" setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Carte visible")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Nouvelle tâche" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vers la colonne suivante/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Modifier «/ })).not.toBeInTheDocument();
  });

  it("rejects an empty titre in the create form without calling the API", async () => {
    const appels = stubFetch([]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getAllByText("Aucune tâche.").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Nouvelle tâche" }));
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));

    expect(await screen.findByText("Le titre est obligatoire.")).toBeInTheDocument();
    expect(appels.some((a) => a.method === "POST")).toBe(false);
  });

  it("should filter cards by who they concern", async () => {
    // Kyllian Bresson, 25/09/2026 : « il y a des modifications qui vous
    // concernent et d'autres qui me concernent uniquement ».
    stubFetch([
      tache({ id: 1, titre: "Mapper WSA507D", concerne: "Jules" }),
      tache({ id: 2, titre: "Prevenir les BUT2", concerne: "Kyllian" }),
      tache({ id: 3, titre: "A trier" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Mapper WSA507D")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Pour qui"), { target: { value: "Kyllian" } });
    expect(screen.queryByText("Mapper WSA507D")).not.toBeInTheDocument();
    expect(screen.getByText("Prevenir les BUT2")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pour qui"), { target: { value: "__sans__" } });
    expect(screen.getByText("A trier")).toBeInTheDocument();
    expect(screen.queryByText("Prevenir les BUT2")).not.toBeInTheDocument();
  });

  // Deux onglets EDT / Plateforme (Jules, dicté 25/09/2026 : « deux petits
  // boutons qui seraient des onglets : entre les affaires par rapport à
  // l'emploi du temps [...] et les affaires à propos de la plateforme »).

  it("shows two tabs with role=tab/aria-selected and their counts, filtering the board", async () => {
    stubFetch([
      tache({ id: 1, titre: "Deplacer le TD", categorie: "edt" }),
      tache({ id: 2, titre: "Bug export Celcat", categorie: "plateforme" }),
      tache({ id: 3, titre: "Salle a corriger", categorie: "plateforme" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Deplacer le TD")).toBeInTheDocument());

    const tablist = screen.getByRole("tablist", { name: "Catégorie de tâches" });
    expect(tablist).toBeInTheDocument();
    const ongletEdt = screen.getByRole("tab", { name: /Emploi du temps/ });
    const ongletPlateforme = screen.getByRole("tab", { name: /Plateforme/ });
    expect(ongletEdt).toHaveAttribute("aria-selected", "true");
    expect(ongletPlateforme).toHaveAttribute("aria-selected", "false");
    expect(ongletEdt).toHaveTextContent("1");
    expect(ongletPlateforme).toHaveTextContent("2");

    // Onglet EDT actif par défaut : seule la carte EDT est visible.
    expect(screen.getByText("Deplacer le TD")).toBeInTheDocument();
    expect(screen.queryByText("Bug export Celcat")).not.toBeInTheDocument();

    fireEvent.click(ongletPlateforme);
    expect(screen.queryByText("Deplacer le TD")).not.toBeInTheDocument();
    expect(screen.getByText("Bug export Celcat")).toBeInTheDocument();
    expect(screen.getByText("Salle a corriger")).toBeInTheDocument();
    expect(ongletPlateforme).toHaveAttribute("aria-selected", "true");
    expect(ongletEdt).toHaveAttribute("aria-selected", "false");
  });

  it("shows an Urgent text marker and sorts urgent cards first in their column", async () => {
    stubFetch([
      tache({ id: 1, titre: "Tache normale", ordre: 0, priorite: "normale" }),
      tache({ id: 2, titre: "Tache urgente", ordre: 1, priorite: "urgente" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Tache urgente")).toBeInTheDocument());

    expect(screen.getByText("Urgent")).toBeInTheDocument();

    const titres = screen.getAllByText(/^Tache (normale|urgente)$/).map((el) => el.textContent);
    expect(titres).toEqual(["Tache urgente", "Tache normale"]);
  });

  it("sends categorie and priorite from the create form", async () => {
    const appels = stubFetch([]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByText("Aucune tâche.").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Nouvelle tâche" }));
    fireEvent.change(screen.getByPlaceholderText("ex. Prévenir Kyllian, absent jeudi"), {
      target: { value: "Bug de la vue Salle" },
    });
    fireEvent.change(screen.getByLabelText("Catégorie"), { target: { value: "plateforme" } });
    fireEvent.click(screen.getByLabelText("Urgent"));
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));

    await waitFor(() => expect(appels.some((a) => a.method === "POST")).toBe(true));
    const post = appels.find((a) => a.method === "POST");
    expect((post?.body as { categorie?: string; priorite?: string })?.categorie).toBe("plateforme");
    expect((post?.body as { categorie?: string; priorite?: string })?.priorite).toBe("urgente");
  });

  it("restores the active tab from storage after a reload", async () => {
    window.localStorage.setItem("cal-iut:kanban:onglet:v1", "plateforme");
    stubFetch([
      tache({ id: 1, titre: "Carte EDT", categorie: "edt" }),
      tache({ id: 2, titre: "Carte plateforme", categorie: "plateforme" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Carte plateforme")).toBeInTheDocument());
    expect(screen.queryByText("Carte EDT")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Plateforme/ })).toHaveAttribute("aria-selected", "true");
  });

  it("should copy every detail of a card to the clipboard", async () => {
    // Jules, 28/09/2026 : « un petit bouton copier qui copie toutes les
    // infos d'une tâche ».
    const copies: string[] = [];
    Object.assign(navigator, {
      clipboard: { writeText: (texte: string) => { copies.push(texte); return Promise.resolve(); } },
    });
    stubFetch([
      tache({ id: 1, titre: "Deplacer les TD de KBR", concerne: "Jules", enseignant_code: "KBR", priorite: "urgente" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Deplacer les TD de KBR")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Copier toutes les informations/ }));

    await waitFor(() => expect(copies).toHaveLength(1));
    expect(copies[0]).toContain("[Urgent] Deplacer les TD de KBR");
    expect(copies[0]).toContain("Kyllian Bresson");
    expect(copies[0]).toContain("pour Jules");
    await waitFor(() => expect(screen.getByText("Copié")).toBeInTheDocument());
  });

  // Refonte du 29/09/2026 : création rapide, raccourcis, filtres.

  it("creates a card from the quick-add field with Enter, in that column and the open tab", async () => {
    const appels = stubFetch([]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByText("Aucune tâche.").length).toBeGreaterThan(0));

    const champ = screen.getByLabelText("Ajouter une tâche dans En cours");
    fireEvent.change(champ, { target: { value: "Relancer la scolarité" } });
    fireEvent.submit(champ.closest("form")!);

    await waitFor(() => expect(screen.getByText("Relancer la scolarité")).toBeInTheDocument());
    const post = appels.find((a) => a.method === "POST");
    expect(post?.body).toMatchObject({ titre: "Relancer la scolarité", colonne: "en_cours", categorie: "edt" });
    expect(champ).toHaveValue("");
  });

  it("focuses the quick-add field with the N key", async () => {
    stubFetch([]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByText("Aucune tâche.").length).toBeGreaterThan(0));
    fireEvent.keyDown(document.body, { key: "n" });
    expect(screen.getByLabelText("Ajouter une tâche dans À faire")).toHaveFocus();
  });

  // Numéro de tâche visible (Jules, 09/10/2026 : « mettre les hashtags des
  // tâches sur l'interface »), le même que dans le rapport copié.
  it("shows the task number on each card and finds a card by #number", async () => {
    stubFetch([
      tache({ id: 7, titre: "Valérie Mariot dans Celcat" }),
      tache({ id: 17, titre: "Vacances hachurées" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Valérie Mariot dans Celcat")).toBeInTheDocument());
    expect(screen.getByLabelText("Tâche numéro 7")).toHaveTextContent("#7");
    expect(screen.getByLabelText("Tâche numéro 17")).toHaveTextContent("#17");

    fireEvent.change(screen.getByLabelText("Filtrer les tâches"), { target: { value: "#7" } });
    expect(screen.getByText("Valérie Mariot dans Celcat")).toBeInTheDocument();
    expect(screen.queryByText("Vacances hachurées")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filtrer les tâches"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Modifier « Vacances hachurées »" }));
    expect(screen.getByRole("heading", { name: "Modifier la tâche #17" })).toBeInTheDocument();
  });

  it("filters cards by text and remembers who they are for", async () => {
    stubFetch([
      tache({ id: 1, titre: "Mapper WSA507D", concerne: "Jules" }),
      tache({ id: 2, titre: "Prevenir les BUT2", concerne: "Kyllian" }),
    ]);
    const { unmount } = render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Mapper WSA507D")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Filtrer les tâches"), { target: { value: "wsa" } });
    expect(screen.queryByText("Prevenir les BUT2")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pour qui"), { target: { value: "Kyllian" } });
    unmount();
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Prevenir les BUT2")).toBeInTheDocument());
    expect(screen.getByLabelText("Pour qui")).toHaveValue("Kyllian");
    expect(screen.queryByText("Mapper WSA507D")).not.toBeInTheDocument();
  });

  it("opens the edit form when the card title is clicked", async () => {
    stubFetch([tache({ id: 1, titre: "Carte a modifier" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Carte a modifier")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Modifier « Carte a modifier »" }));
    expect(screen.getByRole("dialog", { name: /^Modifier la tâche #\d+$/ })).toBeInTheDocument();
  });
});

