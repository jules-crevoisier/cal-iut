/**
 * Un écran qui plante ne doit plus donner une page blanche (audit du
 * 29/09/2026, P1-13) : message, bouton « Recharger », détail repliable, et
 * ce qui est HORS de la zone (la navigation) reste en place.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Plante(): JSX.Element {
  throw new Error("park.items est indéfini");
}

function Page({ cle, plante }: { cle: string; plante: boolean }) {
  return (
    <div>
      <nav>Navigation</nav>
      <ErrorBoundary cle={cle}>{plante ? <Plante /> : <p>Écran sain</p>}</ErrorBoundary>
    </div>
  );
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React journalise l'erreur attrapée : sans intérêt dans la sortie des tests.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a message, a reload button and a folded detail, and keeps the navigation", () => {
    render(<Page cle="promo" plante />);
    expect(screen.getByRole("alert")).toHaveTextContent("Cet écran a rencontré une erreur");
    expect(screen.getByRole("button", { name: "Recharger" })).toBeInTheDocument();
    expect(screen.getByText("Détail technique").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(/park\.items est indéfini/)).toBeInTheDocument();
    expect(screen.getByText("Navigation")).toBeInTheDocument();
  });

  it("reloads the page from the button", () => {
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload });
    render(<Page cle="promo" plante />);
    fireEvent.click(screen.getByRole("button", { name: "Recharger" }));
    expect(reload).toHaveBeenCalled();
  });

  it("forgets the error when another screen is opened", () => {
    const { rerender } = render(<Page cle="promo" plante />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<Page cle="prof" plante={false} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Écran sain")).toBeInTheDocument();
  });
});
