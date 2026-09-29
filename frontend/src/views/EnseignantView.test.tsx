/**
 * Contrat fiche enseignant : prof inconnu → introuvable + recherche ;
 * enseignant connu sans séance cette semaine → grille vide.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EnseignantView } from "./EnseignantView";
import { catalogTeacher, emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  teacherLabels: { KBR: "Lefèvre Kevin" },
  teachers: [catalogTeacher("KBR", "Lefèvre Kevin")],
});

describe("EnseignantView", () => {
  it("should show introuvable and a way to open search when the teacher code is unknown", () => {
    render(
      <EnseignantView
        payload={payload}
        route={testRoute({ vue: "prof", prof: "ZZZ" })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByText(/introuvable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recherche/i })).toBeInTheDocument();
  });

  it("should still show the week grid when the teacher exists but has no rows that week", () => {
    render(
      <EnseignantView
        payload={payload}
        route={testRoute({ vue: "prof", prof: "KBR", sem: 0 })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("8h–9h30").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vendredi").length).toBeGreaterThan(0);
  });

  // Onglet ouvert sans enseignant : plus le premier par ordre alphabétique,
  // souvent quelqu'un sans aucune séance (« 0 séance »).
  describe("without a teacher in the route", () => {
    const deux = emptyPayload({
      teacherLabels: { AAA: "Abel Anne", KBR: "Lefèvre Kevin" },
      teacherEmails: { AAA: "anne.abel@iut.test", KBR: "Kevin.Lefevre@iut.test" },
      teachers: [catalogTeacher("AAA", "Abel Anne"), catalogTeacher("KBR", "Lefèvre Kevin")],
    });

    it("opens on the signed-in account's own sheet when its address is a teacher's", () => {
      render(
        <EnseignantView
          payload={deux}
          route={testRoute({ vue: "prof" })}
          setRoute={vi.fn()}
          emailCompte=" kevin.lefevre@IUT.test "
        />,
      );
      expect(screen.getByLabelText("Enseignant")).toHaveValue("KBR");
      expect(screen.getByText("KBR")).toBeInTheDocument();
    });

    // Refonte v2 (29/09/2026) : plus de boîte vide « Choisissez un
    // enseignant » — l'annuaire, et toujours pas la fiche du premier venu.
    it("otherwise shows the directory, never the first teacher's sheet, and a click opens a sheet", () => {
      const setRoute = vi.fn();
      render(
        <EnseignantView
          payload={deux}
          route={testRoute({ vue: "prof" })}
          setRoute={setRoute}
          emailCompte="secretariat@iut.test"
        />,
      );
      expect(screen.getByRole("region", { name: "Annuaire des enseignants" })).toBeInTheDocument();
      expect(screen.queryByText("Choisissez un enseignant, ou cherchez-le avec Ctrl+K.")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Enseignant")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Abel Anne" }));
      expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "AAA" });
    });

    it("leads back to the directory from the account's own sheet", () => {
      const setRoute = vi.fn();
      const { rerender } = render(
        <EnseignantView
          payload={deux}
          route={testRoute({ vue: "prof" })}
          setRoute={setRoute}
          emailCompte="kevin.lefevre@iut.test"
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: /retour à l'annuaire/i }));
      expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "" });
      rerender(
        <EnseignantView
          payload={deux}
          route={testRoute({ vue: "prof" })}
          setRoute={setRoute}
          emailCompte="kevin.lefevre@iut.test"
        />,
      );
      expect(screen.getByRole("region", { name: "Annuaire des enseignants" })).toBeInTheDocument();
    });
  });
});
