/**
 * Gestion des comptes (31/08/2026) — liste, activation d'un compte en
 * attente, changement de rôle, désactivation.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminUsersView } from "./AdminUsersView";

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
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const id = Number(String(url).match(/\/admin\/users\/(\d+)/)?.[1]);
        const patch = JSON.parse(String(init.body)) as Record<string, string>;
        const utilisateur = UTILISATEURS.find((u) => u.id === id)!;
        return Promise.resolve({ ok: true, json: async () => ({ ...utilisateur, ...patch }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ users: UTILISATEURS }) });
    }),
  );
}

describe("AdminUsersView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should list pending and active accounts separately", async () => {
    stubFetch();
    render(<AdminUsersView />);

    await waitFor(() => expect(screen.getByText("attente@example.test")).toBeInTheDocument());
    expect(screen.getByText("active@example.test")).toBeInTheDocument();
    expect(screen.getByText("En attente d'activation (1)")).toBeInTheDocument();
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
});
