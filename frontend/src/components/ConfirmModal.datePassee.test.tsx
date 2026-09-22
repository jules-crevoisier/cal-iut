/**
 * Le bouton de confirmation passe en `.btn--danger` quand la requête porte
 * `variant: "danger"` — item A, 22/09/2026 : la popup « Modifier une date
 * passée » doit se distinguer visuellement d'une confirmation ordinaire
 * (`.btn--accent`).
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ConfirmModal } from "./ConfirmModal";
import { confirmAsync, resolveConfirm } from "../utils/confirmDialog";

afterEach(() => {
  resolveConfirm(false); // ne laisse aucune Promise en attente entre les tests
});

describe("ConfirmModal — variante danger", () => {
  it("applique btn--danger quand confirmAsync est appelé avec variant: danger", async () => {
    render(<ConfirmModal />);

    void confirmAsync("Le lundi 21/09/2026 est déjà écoulé.", {
      title: "Modifier une date passée",
      confirmLabel: "Oui, modifier le passé",
      variant: "danger",
    });

    const bouton = await screen.findByRole("button", { name: "Oui, modifier le passé" });
    expect(bouton).toHaveClass("btn--danger");
    expect(bouton).not.toHaveClass("btn--accent");
  });

  it("reste btn--accent sans variant (comportement par défaut, inchangé)", async () => {
    render(<ConfirmModal />);

    void confirmAsync("Conflit ordinaire", { confirmLabel: "Forcer quand même" });

    const bouton = await screen.findByRole("button", { name: "Forcer quand même" });
    expect(bouton).toHaveClass("btn--accent");
    expect(bouton).not.toHaveClass("btn--danger");
  });

  it("le bouton Annuler garde le focus par défaut, même en variante danger", async () => {
    render(<ConfirmModal />);

    void confirmAsync("Le lundi 21/09/2026 est déjà écoulé.", {
      title: "Modifier une date passée",
      confirmLabel: "Oui, modifier le passé",
      variant: "danger",
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "Annuler" })).toHaveFocus());
  });
});
