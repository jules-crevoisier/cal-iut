/**
 * Images jointes aux tâches (30/09/2026) : ajout par bouton, collage
 * (Ctrl V), glisser-déposer, vignettes, aperçu (Échap, flèches), retrait
 * avec confirmation, compteur sur la carte, lecture seule.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageTache, Tache } from "../api/client";
import { nommerCapture, trierFichiers } from "../components/ImagesTache";
import { emptyPayload } from "../test/payloadFixture";
import { KanbanView } from "./KanbanView";

function image(id: number, tacheId: number, nom = `image-${id}.png`): ImageTache {
  return {
    id,
    nom,
    type: "image/png",
    taille: 1234,
    largeur: 800,
    hauteur: 600,
    cree_par: "prof@example.test",
    cree_le: "2026-09-30T08:00:00",
    url: `/taches/${tacheId}/images/${id}`,
  };
}

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
    images: [],
    ...overrides,
  };
}

function png(nom = "capture.png", type = "image/png"): File {
  return new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], nom, { type });
}

interface Appel {
  method: string;
  url: string;
  body: unknown;
}

/** Faux serveur : garde l'état des tâches et de leurs images. */
function stubServeur(initiales: Tache[]) {
  const taches = initiales.map((t) => ({ ...t, images: [...(t.images ?? [])] }));
  let prochainImage = 100;
  const appels: Appel[] = [];
  const reponse = (corps: unknown, ok = true, status = 200) =>
    Promise.resolve({ ok, status, statusText: "", json: async () => corps });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const chemin = String(url);
      appels.push({ method, url: chemin, body: init?.body });
      const envoi = chemin.match(/^\/taches\/(\d+)\/images$/);
      if (method === "POST" && envoi) {
        const t = taches.find((x) => x.id === Number(envoi[1]));
        const fichier = (init?.body as FormData).get("fichier") as File;
        if (!t) return reponse({ detail: "Tâche introuvable." }, false, 404);
        t.images.push(image(prochainImage++, t.id, fichier.name));
        return reponse({ ...t, images: [...t.images] });
      }
      const retrait = chemin.match(/^\/taches\/(\d+)\/images\/(\d+)$/);
      if (method === "DELETE" && retrait) {
        const t = taches.find((x) => x.id === Number(retrait[1]))!;
        t.images = t.images.filter((i) => i.id !== Number(retrait[2]));
        return reponse({ ...t, images: [...t.images] });
      }
      if (method === "GET" && chemin.startsWith("/taches")) {
        return reponse(taches.map((t) => ({ ...t, images: [...t.images] })));
      }
      if (method === "POST" && chemin === "/taches") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        const creee = tache({ id: 999, titre: body.titre ?? "", ...body, images: [] });
        taches.push({ ...creee, images: [] });
        return reponse(creee);
      }
      const patch = chemin.match(/^\/taches\/(\d+)$/);
      if (method === "PATCH" && patch) {
        const t = taches.find((x) => x.id === Number(patch[1]))!;
        Object.assign(t, JSON.parse(String(init?.body ?? "{}")));
        return reponse({ ...t, images: [...t.images] });
      }
      return reponse({});
    }),
  );
  return appels;
}

const payload = emptyPayload({ teacherLabels: {} });

async function ouvrirModification(titre: string) {
  await waitFor(() => expect(screen.getByText(titre)).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: `Modifier « ${titre} »` }));
  return screen.getByRole("dialog", { name: /^Modifier la tâche #\d+$/ });
}

function envoisImages(appels: Appel[]) {
  return appels.filter((a) => a.method === "POST" && /\/images$/.test(a.url));
}

describe("KanbanView — images des tâches", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("adds an image with the « Ajouter une image » button and shows its thumbnail and card counter", async () => {
    const appels = stubServeur([tache({ id: 1, titre: "Salle sans vidéoprojecteur" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Salle sans vidéoprojecteur");

    expect(within(modale).getByRole("button", { name: "Ajouter une image" })).toBeInTheDocument();
    const choix = modale.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(choix.accept).toBe("image/png,image/jpeg,image/webp,image/gif");
    fireEvent.change(choix, { target: { files: [png("tableau.png")] } });

    await waitFor(() => expect(within(modale).getByRole("button", { name: "Agrandir « tableau.png »" })).toBeInTheDocument());
    const [envoi] = envoisImages(appels);
    expect(envoi.url).toBe("/taches/1/images");
    expect(((envoi.body as FormData).get("fichier") as File).name).toBe("tableau.png");
    // Enregistrée aussitôt : le compteur de la carte suit, modale ouverte.
    expect(screen.getByRole("button", { name: "Voir l’image de « Salle sans vidéoprojecteur »" })).toHaveTextContent("1");
    expect(within(modale).getByText("1/10")).toBeInTheDocument();
  });

  it("uploads a screenshot pasted with Ctrl V, renamed with the date", async () => {
    const appels = stubServeur([tache({ id: 1, titre: "Bug d'affichage" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Bug d'affichage");

    fireEvent.paste(document, { clipboardData: { files: [png("image.png")], getData: () => "" } });

    await waitFor(() => expect(envoisImages(appels)).toHaveLength(1));
    const nom = ((envoisImages(appels)[0].body as FormData).get("fichier") as File).name;
    expect(nom).toMatch(/^capture-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}\.png$/);
    await waitFor(() => expect(within(modale).getByRole("button", { name: `Agrandir « ${nom} »` })).toBeInTheDocument());
  });

  it("keeps pasted text as text inside a field", async () => {
    const appels = stubServeur([tache({ id: 1, titre: "Carte" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Carte");
    const titre = within(modale).getByDisplayValue("Carte");

    fireEvent.paste(titre, { clipboardData: { files: [png("image.png")], getData: () => "du texte" } });
    expect(envoisImages(appels)).toHaveLength(0);
  });

  it("uploads images dropped on the task window", async () => {
    const appels = stubServeur([tache({ id: 1, titre: "Carte" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Carte");

    fireEvent.dragEnter(modale, { dataTransfer: { types: ["Files"], files: [] } });
    expect(within(modale).getByText("Déposez les images pour les joindre à la tâche")).toBeInTheDocument();
    fireEvent.drop(modale, { dataTransfer: { types: ["Files"], files: [png("a.png"), png("b.webp", "image/webp")] } });

    await waitFor(() => expect(envoisImages(appels)).toHaveLength(2));
    expect(within(modale).queryByText("Déposez les images pour les joindre à la tâche")).not.toBeInTheDocument();
    await waitFor(() => expect(within(modale).getAllByRole("button", { name: /^Agrandir/ })).toHaveLength(2));
  });

  it("refuses an SVG or an oversized file before sending anything", async () => {
    const appels = stubServeur([tache({ id: 1, titre: "Carte" })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Carte");
    const lourd = png("enorme.png");
    Object.defineProperty(lourd, "size", { value: 9 * 1024 * 1024 });

    fireEvent.change(modale.querySelector('input[type="file"]')!, {
      target: { files: [png("logo.svg", "image/svg+xml"), lourd] },
    });

    const alerte = await within(modale).findByRole("alert");
    expect(alerte).toHaveTextContent("« logo.svg » : format non accepté (PNG, JPEG, WebP ou GIF).");
    expect(alerte).toHaveTextContent("« enorme.png » : trop lourde (8 Mo au maximum).");
    expect(envoisImages(appels)).toHaveLength(0);
  });

  it("shows thumbnails and a preview navigable with the arrows, closed by Escape without closing the task", async () => {
    stubServeur([
      tache({ id: 1, titre: "Trois captures", images: [image(10, 1, "a.png"), image(11, 1, "b.png"), image(12, 1, "c.png")] }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Trois captures");

    expect(within(modale).getAllByRole("button", { name: /^Agrandir/ })).toHaveLength(3);
    expect(within(modale).getByText("3/10")).toBeInTheDocument();
    fireEvent.click(within(modale).getByRole("button", { name: "Agrandir « b.png »" }));

    const apercu = screen.getByRole("dialog", { name: "Aperçu de « b.png », image 2 sur 3" });
    expect(within(apercu).getByRole("img", { name: "b.png" })).toHaveAttribute("src", "/taches/1/images/11");
    expect(within(apercu).getByRole("button", { name: "Fermer l’aperçu" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "Aperçu de « c.png », image 3 sur 3" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(screen.getByRole("dialog", { name: "Aperçu de « a.png », image 1 sur 3" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /^Aperçu/ })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: /^Modifier la tâche #\d+$/ })).toBeInTheDocument();
  });

  it("removes an image after a light confirmation", async () => {
    const appels = stubServeur([tache({ id: 1, titre: "Carte", images: [image(10, 1, "a.png"), image(11, 1, "b.png")] })]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    const modale = await ouvrirModification("Carte");

    fireEvent.click(within(modale).getByRole("button", { name: "Retirer « a.png »" }));
    const confirmation = within(modale).getByRole("group", { name: "Retirer « a.png » ?" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Garder" }));
    expect(appels.some((a) => a.method === "DELETE")).toBe(false);

    fireEvent.click(within(modale).getByRole("button", { name: "Retirer « a.png »" }));
    fireEvent.click(within(within(modale).getByRole("group", { name: "Retirer « a.png » ?" })).getByRole("button", { name: "Retirer" }));

    await waitFor(() => expect(within(modale).queryByRole("button", { name: "Agrandir « a.png »" })).not.toBeInTheDocument());
    expect(appels.find((a) => a.method === "DELETE")?.url).toBe("/taches/1/images/10");
    expect(within(modale).getByRole("button", { name: "Agrandir « b.png »" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Voir l’image de « Carte »" })).toHaveTextContent("1");
  });

  it("shows an image counter on the card that opens the preview", async () => {
    stubServeur([
      tache({ id: 1, titre: "Avec images", images: [image(10, 1), image(11, 1)] }),
      tache({ id: 2, titre: "Sans image" }),
    ]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Avec images")).toBeInTheDocument());

    const compteur = screen.getByRole("button", { name: "Voir les 2 images de « Avec images »" });
    expect(compteur).toHaveTextContent("2");
    expect(compteur.querySelector("svg")).not.toBeNull(); // icône, pas d'emoji
    expect(screen.queryByRole("button", { name: /^Voir .* de « Sans image »$/ })).not.toBeInTheDocument();

    fireEvent.click(compteur);
    expect(screen.getByRole("dialog", { name: "Aperçu de « image-10.png », image 1 sur 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Image suivante" }));
    expect(screen.getByRole("dialog", { name: "Aperçu de « image-11.png », image 2 sur 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fermer l’aperçu" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("lets a read-only account view images without any add or remove control", async () => {
    stubServeur([tache({ id: 1, titre: "Lecture", images: [image(10, 1, "a.png")] })]);
    render(<KanbanView payload={payload} role="read_only" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Lecture")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Voir l’image de « Lecture »" }));
    expect(screen.getByRole("dialog", { name: "Aperçu de « a.png »" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ajouter une image" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Retirer/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Modifier/ })).not.toBeInTheDocument();
  });

  it("keeps images chosen while creating a task and sends them once it exists", async () => {
    const appels = stubServeur([]);
    render(<KanbanView payload={payload} role="edit" setRoute={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByText("Aucune tâche.").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Nouvelle tâche" }));
    const modale = screen.getByRole("dialog", { name: "Nouvelle tâche" });
    fireEvent.change(within(modale).getByPlaceholderText("ex. Prévenir Kyllian, absent jeudi"), {
      target: { value: "Capture du bug" },
    });

    fireEvent.paste(document, { clipboardData: { files: [png("image.png")], getData: () => "" } });
    await waitFor(() => expect(within(modale).getByText("en attente")).toBeInTheDocument());
    expect(envoisImages(appels)).toHaveLength(0);

    await act(async () => {
      fireEvent.click(within(modale).getByRole("button", { name: "Créer" }));
    });
    await waitFor(() => expect(envoisImages(appels)).toHaveLength(1));
    expect(envoisImages(appels)[0].url).toBe("/taches/999/images");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Voir l’image de « Capture du bug »" })).toBeInTheDocument();
  });
});

describe("trierFichiers / nommerCapture", () => {
  it("accepts the four formats up to the remaining places", () => {
    const { acceptes, refus } = trierFichiers(
      [png("a.png"), png("b.jpg", "image/jpeg"), png("c.gif", "image/gif"), png("d.webp", "image/webp")],
      3,
    );
    expect(acceptes.map((f) => f.name)).toEqual(["a.png", "b.jpg", "c.gif"]);
    expect(refus).toEqual(["1 image de trop : 10 au maximum par tâche."]);
  });

  it("names a pasted screenshot after the date, keeps a real name", () => {
    const quand = new Date(2026, 8, 30, 14, 5);
    expect(nommerCapture(png("image.png"), quand).name).toBe("capture-2026-09-30-14h05.png");
    expect(nommerCapture(png("", "image/jpeg"), quand).name).toBe("capture-2026-09-30-14h05.jpg");
    expect(nommerCapture(png("schema-salle.png"), quand).name).toBe("schema-salle.png");
  });
});
