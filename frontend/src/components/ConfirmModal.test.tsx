/**
 * La modale de confirmation, utilisée partout (forçage, suppressions,
 * écriture Celcat) : clavier, focus, et listes lisibles.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ConfirmModal } from "./ConfirmModal";
import { confirmAsync, resolveConfirm } from "../utils/confirmDialog";

afterEach(() => {
  resolveConfirm(false);
});

describe("ConfirmModal", () => {
  it("rend une énumération comme une vraie liste", async () => {
    render(<ConfirmModal />);
    void confirmAsync("• WR402 Anglais — mercredi\n• WR210 Culture — vendredi\n\nCes évènements seront supprimés.", {
      title: "Supprimer 2 évènements",
      confirmLabel: "Supprimer 2 évènements",
      variant: "danger",
    });
    const liste = await screen.findByRole("list");
    expect(liste.querySelectorAll("li")).toHaveLength(2);
    expect(liste.textContent).toContain("WR402 Anglais");
    expect(screen.getByText("Ces évènements seront supprimés.")).toBeTruthy();
  });

  it("annule avec Échap", async () => {
    render(<ConfirmModal />);
    let resultat: boolean | null = null;
    void confirmAsync("Forcer ?").then((r) => (resultat = r));
    await screen.findByRole("alertdialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(resultat).toBe(false));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("garde le focus dans la modale et le rend à l'élément d'origine", async () => {
    render(
      <>
        <button type="button">Origine</button>
        <ConfirmModal />
      </>,
    );
    const origine = screen.getByRole("button", { name: "Origine" });
    origine.focus();
    void confirmAsync("Forcer ?", { confirmLabel: "Forcer" });
    const annuler = await screen.findByRole("button", { name: "Annuler" });
    await waitFor(() => expect(annuler).toHaveFocus());

    const forcer = screen.getByRole("button", { name: "Forcer" });
    forcer.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(annuler).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(forcer).toHaveFocus();

    act(() => resolveConfirm(false));
    await waitFor(() => expect(origine).toHaveFocus());
  });
});
