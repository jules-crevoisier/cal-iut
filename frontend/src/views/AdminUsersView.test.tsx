/**
 * Gestion des comptes (31/08/2026) — liste, activation d'un compte en
 * attente, changement de rôle, désactivation.
 *
 * Suppression des comptes en attente (25/09/2026) : `confirmAsync` est
 * mocké (même patron que `AdminCelcatView.test.tsx`) — sans ça, la Promise
 * qu'il renvoie ne se résoudrait jamais dans ce test (le vrai `ConfirmModal`
 * n'est monté que par `App.tsx`, pas par ce rendu isolé).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminUsersView } from "./AdminUsersView";
import { confirmAsync } from "../utils/confirmDialog";

vi.mock("../utils/confirmDialog", () => ({ confirmAsync: vi.fn() }));

const UTILISATEURS = [
  {
    id: 1,
    email: "attente@example.test",
    role: "read_only",
    status: "pending_admin_activation",
    created_at: "2026-08-31T10:00:00Z",
    email_confirmed_at: "2026-08-31T10:05:00Z",
    activated_at: null,
  },
  {
    id: 2,
    email: "active@example.test",
    role: "edit",
    status: "active",
    created_at: "2026-08-30T10:00:00Z",
    email_confirmed_at: "2026-08-30T10:05:00Z",
    activated_at: "2026-08-30T11:00:00Z",
  },
  {
    id: 3,
    email: "jamais-confirme@example.test",
    role: "read_only",
    status: "pending_email",
    created_at: "2026-09-01T10:00:00Z",
    email_confirmed_at: null,
    activated_at: null,
  },
];

function stubFetch(options?: { echecSuppression?: boolean }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const id = Number(String(url).match(/\/admin\/users\/(\d+)/)?.[1]);
        const patch = JSON.parse(String(init.body)) as Record<string, string>;
        const utilisateur = UTILISATEURS.find((u) => u.id === id)!;
        return Promise.resolve({ ok: true, json: async () => ({ ...utilisateur, ...patch }) });
      }
      if (init?.method === "DELETE") {
        if (options?.echecSuppression) {
          return Promise.resolve({
            ok: false,
            json: async () => ({ message: "Ce compte a déjà été activé : désactivez-le plutôt que de le supprimer." }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ users: UTILISATEURS }) });
    }),
  );
}

describe("AdminUsersView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.mocked(confirmAsync).mockReset();
  });

  it("should list pending and active accounts separately", async () => {
    stubFetch();
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("attente@example.test")).toBeInTheDocument());
    expect(screen.getByText("active@example.test")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "En attente d'activation 1" })).toBeInTheDocument();
  });

  it("should PATCH the role when activating a pending account", async () => {
    stubFetch();
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("attente@example.test")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Activer en édition" }));

    await waitFor(() => {
      const patchCall = vi
        .mocked(fetch)
        .mock.calls.find((c) => String(c[0]).includes("/admin/users/1") && c[1]?.method === "PATCH");
      expect(patchCall).toBeDefined();
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ role: "edit" });
    });
  });

  it("should PATCH status=disabled when disabling an active account", async () => {
    stubFetch();
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("active@example.test")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() => {
      const patchCall = vi
        .mocked(fetch)
        .mock.calls.find((c) => String(c[0]).includes("/admin/users/2") && c[1]?.method === "PATCH");
      expect(patchCall).toBeDefined();
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ status: "disabled" });
    });
  });

  it("should show the error message when the last-admin guard rejects a change", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") {
          return Promise.resolve({
            ok: false,
            json: async () => ({ message: "Impossible de retirer le dernier administrateur actif." }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({ users: UTILISATEURS }) });
      }),
    );
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("active@example.test")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Impossible de retirer le dernier administrateur actif."),
    );
  });

  it("should show a delete button only on pending rows (pending_email and pending_admin_activation)", async () => {
    stubFetch();
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("active@example.test")).toBeInTheDocument());

    // Une ligne « en attente d'activation » ET une ligne « email non
    // confirmé » ont chacune leur bouton — le compte actif n'en a aucun.
    expect(screen.getAllByRole("button", { name: "Supprimer" })).toHaveLength(2);
    // Les comptes hors demandes d'accès sont des lignes de tableau.
    const ligneActive = screen.getByText("active@example.test").closest("tr")!;
    expect(within(ligneActive).queryByRole("button", { name: "Supprimer" })).not.toBeInTheDocument();
  });

  it("should ask for confirmation naming the address before deleting, and do nothing on cancel", async () => {
    stubFetch();
    vi.mocked(confirmAsync).mockResolvedValue(false);
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("attente@example.test")).toBeInTheDocument());
    const ligne = screen.getByText("attente@example.test").closest("li")!;
    fireEvent.click(within(ligne).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(confirmAsync).toHaveBeenCalled());
    expect(String(vi.mocked(confirmAsync).mock.calls[0][0])).toContain("attente@example.test");

    // Refusé : aucun DELETE envoyé, la ligne reste affichée.
    expect(vi.mocked(fetch).mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);
    expect(screen.getByText("attente@example.test")).toBeInTheDocument();
  });

  it("should DELETE and remove the row with a one-line confirmation on success", async () => {
    stubFetch();
    vi.mocked(confirmAsync).mockResolvedValue(true);
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("jamais-confirme@example.test")).toBeInTheDocument());
    const ligne = screen.getByText("jamais-confirme@example.test").closest("tr")!;
    fireEvent.click(within(ligne).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => {
      const deleteCall = vi.mocked(fetch).mock.calls.find((c) => String(c[0]).includes("/admin/users/3") && c[1]?.method === "DELETE");
      expect(deleteCall).toBeDefined();
    });
    await waitFor(() => expect(screen.queryByText("jamais-confirme@example.test")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("jamais-confirme@example.test");
  });

  it("should show the server's error message and keep the row on delete failure", async () => {
    stubFetch({ echecSuppression: true });
    vi.mocked(confirmAsync).mockResolvedValue(true);
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("attente@example.test")).toBeInTheDocument());
    const ligne = screen.getByText("attente@example.test").closest("li")!;
    fireEvent.click(within(ligne).getByRole("button", { name: "Supprimer" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Ce compte a déjà été activé : désactivez-le plutôt que de le supprimer.",
      ),
    );
    expect(screen.getByText("attente@example.test")).toBeInTheDocument();
  });

  it("filtre les comptes par statut et par adresse", async () => {
    stubFetch();
    render(<AdminUsersView />);
    await waitFor(() => expect(screen.getByText("active@example.test")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /^actifs/i }));
    expect(screen.queryByText("jamais-confirme@example.test")).not.toBeInTheDocument();
    expect(screen.getByText("active@example.test")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^tous/i }));
    fireEvent.change(screen.getByRole("searchbox", { name: /rechercher une adresse/i }), { target: { value: "jamais" } });
    expect(screen.queryByText("active@example.test")).not.toBeInTheDocument();
    expect(screen.getByText("jamais-confirme@example.test")).toBeInTheDocument();
    // Les demandes d'accès restent visibles quel que soit le filtre.
    expect(screen.getByText("attente@example.test")).toBeInTheDocument();
  });

  it("propose d'annuler une désactivation, sans confirmation préalable", async () => {
    stubFetch();
    render(<AdminUsersView />);
    await waitFor(() => expect(screen.getByText("active@example.test")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    const message = await screen.findByText(/active@example\.test désactivé/);
    expect(confirmAsync).not.toHaveBeenCalled();
    fireEvent.click(within(message.parentElement!).getByRole("button", { name: "Annuler" }));
    await waitFor(() => {
      const reactivation = vi
        .mocked(fetch)
        .mock.calls.filter((c) => c[1]?.method === "PATCH")
        .map((c) => JSON.parse(String(c[1]?.body)));
      expect(reactivation).toContainEqual({ status: "active" });
    });
  });
  // Rôle « Accès API » (29/09/2026) : proposé à l'activation et au changement
  // de rôle, expliqué dans la légende, compté dans la tuile.
  it("propose le rôle « Accès API » à l'activation", async () => {
    stubFetch();
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("attente@example.test")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Activer en accès API" }));

    await waitFor(() => {
      const patchCall = vi
        .mocked(fetch)
        .mock.calls.find((c) => String(c[0]).includes("/admin/users/1") && c[1]?.method === "PATCH");
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ role: "api" });
    });
    expect(await screen.findByText("attente@example.test activé en accès API.")).toBeInTheDocument();
  });

  it("propose « Accès API » au changement de rôle, avec sa ligne de légende", async () => {
    stubFetch();
    render(<AdminUsersView />);

    const select = await screen.findByRole("combobox", { name: "Rôle de active@example.test" });
    expect(within(select).getByRole("option", { name: "Accès API" })).toHaveValue("api");
    fireEvent.change(select, { target: { value: "api" } });
    await waitFor(() => {
      const patchCall = vi
        .mocked(fetch)
        .mock.calls.find((c) => String(c[0]).includes("/admin/users/2") && c[1]?.method === "PATCH");
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ role: "api" });
    });
    expect(
      screen.getByText((_, el) =>
        el?.classList.contains("comptes-roles") === true &&
        /Accès API ne voit aucune donnée dans l'appli ; peut créer ses clés d'accès à l'API en\s+lecture\./.test(
          el.textContent ?? "",
        ),
      ),
    ).toBeInTheDocument();
    // La tuile compte le compte passé en accès API.
    expect(await screen.findByText("0 admin · 0 édition · 0 lecture · 1 accès API")).toBeInTheDocument();
  });
});
