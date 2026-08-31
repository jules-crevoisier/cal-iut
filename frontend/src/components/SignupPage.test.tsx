/**
 * Inscription (31/08/2026) — ouverte à tous, confirmation par email.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignupPage } from "./SignupPage";

describe("SignupPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should show the check-your-email screen after a successful signup", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "pending_email" }) }));
    render(<SignupPage onRetourConnexion={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nouveau@example.test" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "motdepasse123" } });
    fireEvent.click(screen.getByRole("button", { name: "S'inscrire" }));

    await waitFor(() => expect(screen.getByText("Vérifiez vos mails")).toBeInTheDocument());
    expect(screen.getByText("nouveau@example.test")).toBeInTheDocument();
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/auth/signup");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "nouveau@example.test", password: "motdepasse123" });
  });

  it("should show the mail-not-configured error instead of a silent failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({ ok: false, json: async () => ({ message: "Envoi d'email non configuré." }) }),
    );
    render(<SignupPage onRetourConnexion={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nouveau@example.test" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "motdepasse123" } });
    fireEvent.click(screen.getByRole("button", { name: "S'inscrire" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Envoi d'email non configuré."));
    expect(screen.queryByText("Vérifiez vos mails")).not.toBeInTheDocument();
  });

  it("should keep submit disabled while the password is under 10 characters", () => {
    render(<SignupPage onRetourConnexion={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.test" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "court" } });
    expect(screen.getByRole("button", { name: "S'inscrire" })).toBeDisabled();
  });
});
