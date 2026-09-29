/**
 * Contrat SideNav : plus d'onglet « À placer » ; « À traiter » reste.
 *
 * Retour utilisateur 25/09/2026 (Jules, dicté) : « Vue Salle » et « Salles
 * libres » retirées de « Perspectives » — « Salles libres » devient un lien
 * public (`mode=salles`), « Vue Salle » reste joignable par la recherche et
 * les liens perso. Les deux routes/composants restent, seuls les deux
 * boutons de la nav disparaissent.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SideNav } from "./SideNav";

const baseProps = {
  activeTab: "promo" as const,
  onSelect: vi.fn(),
  onOpenSearch: vi.fn(),
  hasPayload: true,
  todoCount: 2,
  todoHasBad: false,
  open: false,
  onClose: vi.fn(),
};

describe("SideNav groups", () => {
  it("should keep the À traiter tab when the nav is rendered", () => {
    render(<SideNav {...baseProps} />);
    expect(screen.getByRole("button", { name: /à traiter/i })).toBeInTheDocument();
  });

  it("should not include a tab id aplacer when the nav is rendered", () => {
    const { container } = render(<SideNav {...baseProps} />);
    expect(screen.queryByRole("button", { name: /^à placer$/i })).not.toBeInTheDocument();
    expect(container.querySelector("#onglet-aplacer")).toBeNull();
  });

  it("should still expose Vue Promo when À placer is gone from the nav", () => {
    render(<SideNav {...baseProps} />);
    expect(screen.getByRole("button", { name: /vue promo/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vue groupe/i })).not.toBeInTheDocument();
  });

  it("should open on Accueil first, then the known views in their usual order", () => {
    const { container } = render(<SideNav {...baseProps} />);
    const libelles = [...container.querySelectorAll(".navbtn .navbtn-libelle")].map((b) => b.textContent);
    expect(libelles.slice(0, 5)).toEqual(["Accueil", "Vue Semaine", "Vue Enseignant", "Vue Promo", "Vue TD / TP"]);
  });

  it("should remember the collapsed rail on the device", () => {
    const { container, unmount } = render(<SideNav {...baseProps} />);
    fireEvent.click(screen.getByRole("button", { name: /replier/i }));
    expect(container.querySelector(".sidenav")).toHaveClass("is-repliee");
    unmount();
    const second = render(<SideNav {...baseProps} />);
    expect(second.container.querySelector(".sidenav")).toHaveClass("is-repliee");
  });

  it("should not offer Vue Salle or Salles libres in the nav", () => {
    render(<SideNav {...baseProps} />);
    expect(screen.queryByRole("button", { name: /vue salle/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /salles libres/i })).not.toBeInTheDocument();
  });

  it("should show Administration Celcat only when moi.role is admin", () => {
    const { rerender } = render(<SideNav {...baseProps} />);
    expect(screen.queryByRole("button", { name: /celcat/i })).not.toBeInTheDocument();

    rerender(<SideNav {...baseProps} estAdmin />);
    expect(screen.getByText("Administration")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /celcat/i })).toBeInTheDocument();
  });
});

describe("SideNav search and account", () => {
  const compte = {
    ...baseProps,
    email: "jules.crevoisier@univ-reims.fr",
    role: "admin",
    onCle: vi.fn(),
    onLogout: vi.fn(),
  };

  it("should open the search from the nav", () => {
    const onOpenSearch = vi.fn();
    render(<SideNav {...compte} onOpenSearch={onOpenSearch} />);
    fireEvent.click(screen.getByRole("button", { name: /rechercher/i }));
    expect(onOpenSearch).toHaveBeenCalled();
  });

  it("should show who is connected with their role", () => {
    render(<SideNav {...compte} />);
    const bouton = screen.getByRole("button", { name: /compte/i });
    expect(bouton).toHaveTextContent("Jules Crevoisier");
    expect(bouton).toHaveTextContent("Administrateur");
  });

  it("should offer the API key and logout in the account menu", () => {
    const onCle = vi.fn();
    const onLogout = vi.fn();
    render(<SideNav {...compte} onCle={onCle} onLogout={onLogout} />);
    fireEvent.click(screen.getByRole("button", { name: /compte/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /clé api/i }));
    expect(onCle).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /compte/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /déconnexion/i }));
    expect(onLogout).toHaveBeenCalled();
  });

  it("should say when the server cannot be reached", () => {
    render(<SideNav {...compte} panne />);
    expect(screen.getByRole("status")).toHaveTextContent("Hors ligne");
  });
});
