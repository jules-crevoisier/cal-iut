/**
 * Clés MCP : le brut n'apparaît qu'après génération, jamais au rechargement.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { McpKeysView } from "./McpKeysView";
import { confirmAsync } from "../utils/confirmDialog";

// Révoquer est irréversible : confirmé (refonte du 29/09/2026).
vi.mock("../utils/confirmDialog", () => ({ confirmAsync: vi.fn() }));

const CLES = [
  {
    id: 1,
    prefix: "caliut_abc12",
    created_at: "2026-09-01T10:00:00+00:00",
    last_used_at: null,
  },
];

function stubFetch(opts?: { create?: Record<string, unknown> }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST" && String(url).includes("/auth/mcp-keys")) {
        return Promise.resolve({
          ok: true,
          json: async () =>
            opts?.create ?? {
              id: 2,
              token: "caliut_token-brut-une-fois",
              prefix: "caliut_token",
              created_at: "2026-09-01T11:00:00+00:00",
              last_used_at: null,
            },
        });
      }
      if (init?.method === "DELETE") {
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ keys: CLES }) });
    }),
  );
}

describe("McpKeysView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.mocked(confirmAsync).mockReset();
  });

  it("should list prefixes without the raw token on load", async () => {
    stubFetch();
    render(<McpKeysView />);

    await waitFor(() => expect(screen.getByText("caliut_abc12")).toBeInTheDocument());
    expect(screen.queryByText("caliut_token-brut-une-fois")).not.toBeInTheDocument();
  });

  it("should show the raw token only after generate", async () => {
    stubFetch();
    render(<McpKeysView />);

    await waitFor(() => expect(screen.getByText("caliut_abc12")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /générer/i }));

    await waitFor(() => expect(screen.getByText("caliut_token-brut-une-fois")).toBeInTheDocument());
  });

  it("should DELETE the key when revoking", async () => {
    stubFetch();
    vi.mocked(confirmAsync).mockResolvedValue(true);
    render(<McpKeysView />);

    await waitFor(() => expect(screen.getByText("caliut_abc12")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /révoquer/i }));

    await waitFor(() => {
      const del = vi
        .mocked(fetch)
        .mock.calls.find((c) => String(c[0]).includes("/auth/mcp-keys/1") && c[1]?.method === "DELETE");
      expect(del).toBeDefined();
    });
  });

  it("ne révoque rien si la confirmation est refusée", async () => {
    stubFetch();
    vi.mocked(confirmAsync).mockResolvedValue(false);
    render(<McpKeysView />);

    await waitFor(() => expect(screen.getByText("caliut_abc12")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /révoquer/i }));
    await waitFor(() => expect(confirmAsync).toHaveBeenCalled());
    expect(vi.mocked(confirmAsync).mock.calls[0][1]?.variant).toBe("danger");
    expect(vi.mocked(fetch).mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);
  });

  it("donne de quoi coller la clé neuve là où elle sert, puis la masque", async () => {
    stubFetch();
    render(<McpKeysView />);

    await waitFor(() => expect(screen.getByText("caliut_abc12")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /générer/i }));
    await screen.findByText("caliut_token-brut-une-fois");
    expect(screen.getByRole("button", { name: "Copier la clé" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copier la valeur" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copier l’adresse" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copier le bloc" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "J’ai copié la clé" }));
    expect(screen.queryByText("caliut_token-brut-une-fois")).not.toBeInTheDocument();
  });
  it("nomme les clés (29/09/2026) : nom à la génération, nom et début de clé dans la liste", async () => {
    stubFetch({
      create: {
        id: 2, token: "caliut_token-brut-une-fois", prefix: "caliut_token", nom: "Claude",
        created_at: "2026-09-01T11:00:00+00:00", last_used_at: null,
      },
    });
    render(<McpKeysView />);

    await waitFor(() => expect(screen.getByText("caliut_abc12")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/nom de la nouvelle clé/i), { target: { value: "  Claude " } });
    fireEvent.click(screen.getByRole("button", { name: /générer/i }));
    await screen.findByText("caliut_token-brut-une-fois");
    const post = vi.mocked(fetch).mock.calls.find((c) => c[1]?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ nom: "Claude" });
    expect(screen.getByText("Claude", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("caliut_token")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Révoquer la clé Claude" })).toBeInTheDocument();
    // Variante compte ordinaire : le connecteur MCP reste proposé.
    expect(screen.getByRole("button", { name: "Copier le bloc" })).toBeInTheDocument();
  });

  it("au plus 5 clés actives : la génération est bloquée, en le disant", async () => {
    const cinq = Array.from({ length: 5 }, (_, i) => ({ ...CLES[0], id: i + 1, prefix: `caliut_k${i}` }));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ keys: cinq }) })));
    render(<McpKeysView variante="api" />);

    await screen.findByText("caliut_k0");
    expect(screen.getByRole("button", { name: /générer une clé/i })).toBeDisabled();
    expect(screen.getByText(/5 clés actives au plus/)).toBeInTheDocument();
  });
});
