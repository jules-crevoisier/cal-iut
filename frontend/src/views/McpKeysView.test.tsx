/**
 * Clés MCP : le brut n'apparaît qu'après génération, jamais au rechargement.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { McpKeysView } from "./McpKeysView";

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
});
