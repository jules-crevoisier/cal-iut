/**
 * Contrat SideNav : plus d'onglet « À placer » ; « À traiter » reste.
 */
import { render, screen } from "@testing-library/react";
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
});
