/**
 * Sauvegardes JSON datées (item B, 22/09/2026) — liste, bouton « Faire une
 * sauvegarde maintenant », lien de téléchargement, états vide/chargement/
 * erreur.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SauvegardesView } from "./SauvegardesView";

const SAUVEGARDES = [
  { date: "2026-09-22", taille_octets: 15234, nb_placements: 812 },
  { date: "2026-09-21", taille_octets: 1024, nb_placements: 1 },
];

function stubFetch(sauvegardes: typeof SAUVEGARDES = SAUVEGARDES) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST" && String(url).includes("/sauvegardes")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ date: "2026-09-22", taille_octets: 20000, nb_placements: 900 }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({ sauvegardes }) });
    }),
  );
}

describe("SauvegardesView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("affiche l'état de chargement puis la liste", async () => {
    stubFetch();
    render(<SauvegardesView />);

    expect(screen.getByText("Chargement…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("812 séances placées · 14.9 Ko")).toBeInTheDocument());
    expect(screen.getByText("1 séance placée · 1.0 Ko")).toBeInTheDocument();
  });

  it("affiche un état vide explicite sans aucune sauvegarde", async () => {
    stubFetch([]);
    render(<SauvegardesView />);

    await waitFor(() =>
      expect(
        screen.getByText("Aucune sauvegarde pour l'instant — la première sera prise à la prochaine modification du planning."),
      ).toBeInTheDocument(),
    );
  });

  it("propose un lien de téléchargement par sauvegarde", async () => {
    stubFetch();
    render(<SauvegardesView />);

    await waitFor(() => expect(screen.getAllByRole("link", { name: "Télécharger" })).toHaveLength(2));
    const liens = screen.getAllByRole("link", { name: "Télécharger" });
    expect(liens[0]).toHaveAttribute("href", "/sauvegardes/2026-09-22");
  });

  it("POST /sauvegardes puis recharge la liste au clic sur « Faire une sauvegarde maintenant »", async () => {
    stubFetch();
    render(<SauvegardesView />);

    await waitFor(() => expect(screen.getByText("812 séances placées · 14.9 Ko")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Faire une sauvegarde maintenant" }));

    await waitFor(() => {
      const postCall = vi.mocked(fetch).mock.calls.find((c) => c[1]?.method === "POST");
      expect(postCall).toBeDefined();
      expect(String(postCall?.[0])).toContain("/sauvegardes");
    });
  });

  it("affiche l'erreur de chargement quand la liste échoue", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, json: async () => ({ detail: "Erreur serveur" }) })),
    );
    render(<SauvegardesView />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Erreur serveur"));
  });

  it("affiche l'erreur sans perdre la liste déjà chargée quand la sauvegarde manuelle échoue", async () => {
    stubFetch();
    render(<SauvegardesView />);
    await waitFor(() => expect(screen.getByText("812 séances placées · 14.9 Ko")).toBeInTheDocument());

    vi.mocked(fetch).mockImplementationOnce(() =>
      Promise.resolve({ ok: false, json: async () => ({ detail: "Échec écriture disque" }) } as Response),
    );
    fireEvent.click(screen.getByRole("button", { name: "Faire une sauvegarde maintenant" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Échec écriture disque"));
    // La liste précédente reste affichée — une erreur n'efface pas ce qui marchait.
    expect(screen.getByText("812 séances placées · 14.9 Ko")).toBeInTheDocument();
  });
});
