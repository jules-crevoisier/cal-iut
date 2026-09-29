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

    it("otherwise invites to choose, with the selector in the same place, and never picks the first one", () => {
      const setRoute = vi.fn();
      render(
        <EnseignantView
          payload={deux}
          route={testRoute({ vue: "prof" })}
          setRoute={setRoute}
          emailCompte="secretariat@iut.test"
        />,
      );
      expect(screen.getByText("Choisissez un enseignant, ou cherchez-le avec Ctrl+K.")).toBeInTheDocument();
      expect(screen.getByLabelText("Enseignant")).toHaveValue("");
      expect(screen.queryByText(/séance/)).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("Enseignant"), { target: { value: "AAA" } });
      expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "AAA" });
    });
  });
});
