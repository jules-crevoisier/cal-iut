import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OpenLinkButton } from "./OpenLinkButton";

describe("OpenLinkButton", () => {
  it("should open the given href in a new tab", () => {
    render(<OpenLinkButton href="https://example.test/lien" />);
    const lien = screen.getByRole("link", { name: /ouvrir dans un nouvel onglet/i });
    expect(lien).toHaveAttribute("href", "https://example.test/lien");
    expect(lien).toHaveAttribute("target", "_blank");
    expect(lien).toHaveAttribute("rel", "noopener noreferrer");
  });
});
