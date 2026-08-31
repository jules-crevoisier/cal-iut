/**
 * Contrat fiche groupe : id inconnu → introuvable + recherche ;
 * groupe connu sans séance cette semaine → grille vide.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GroupeView } from "./GroupeView";
import { emptyPayload, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  groupLabels: { G1: "TP A" },
  defaultGroup: "G1",
});

describe("GroupeView", () => {
  it("should show introuvable and a way to open search when the group id is unknown", () => {
    render(
      <GroupeView
        payload={payload}
        route={testRoute({ vue: "groupe", groupe: "INCONNU" })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByText(/introuvable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recherche/i })).toBeInTheDocument();
  });

  it("should still show the week grid when the group exists but has no rows that week", () => {
    render(
      <GroupeView
        payload={payload}
        route={testRoute({ vue: "groupe", groupe: "G1", sem: 0 })}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByText(/introuvable/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("8h–9h30").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vendredi").length).toBeGreaterThan(0);
  });
});
