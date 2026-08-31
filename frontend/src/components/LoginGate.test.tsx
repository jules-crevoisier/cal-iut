/**
 * Connexion par compte (31/08/2026, remplace le mot de passe partagé) :
 * soumission email+mot de passe, message d'erreur lisible, liens vers
 * inscription/mot de passe oublié.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginGate } from "./LoginGate";

function renderGate() {
  const onSuccess = vi.fn();
  const onOuvrirInscription = vi.fn();
  const onOuvrirMotDePasseOublie = vi.fn();
  render(
    <LoginGate
      onSuccess={onSuccess}
      onOuvrirInscription={onOuvrirInscription}
      onOuvrirMotDePasseOublie={onOuvrirMotDePasseOublie}
    />,
  );
  return { onSuccess, onOuvrirInscription, onOuvrirMotDePasseOublie };
}

describe("LoginGate", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should post email and password then call onSuccess when login succeeds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ role: "edit", status: "active" }) }),
    );
    const { onSuccess } = renderGate();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "kbr@example.test" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "motdepasse123" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/auth/login");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "kbr@example.test", password: "motdepasse123" });
  });

  it("should show the server error message when login fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "Email ou mot de passe incorrect." }) }),
    );
    renderGate();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "kbr@example.test" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "mauvais" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Email ou mot de passe incorrect."));
  });

  it("should call the navigation callbacks when the account links are clicked", () => {
    const { onOuvrirInscription, onOuvrirMotDePasseOublie } = renderGate();
    fireEvent.click(screen.getByText("Mot de passe oublié ?"));
    fireEvent.click(screen.getByText("Créer un compte"));
    expect(onOuvrirMotDePasseOublie).toHaveBeenCalled();
    expect(onOuvrirInscription).toHaveBeenCalled();
  });

  it("should disable submit until both fields are filled", () => {
    renderGate();
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.test" } });
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "Se connecter" })).not.toBeDisabled();
  });
});
