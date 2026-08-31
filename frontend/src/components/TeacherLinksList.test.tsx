import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TeacherLinksList } from "./TeacherLinksList";
import { emptyPayload } from "../test/payloadFixture";

describe("TeacherLinksList", () => {
  it("should offer an open-in-new-tab control next to copy for each teacher link", () => {
    render(
      <TeacherLinksList
        payload={emptyPayload({
          teacherLabels: { KBR: "Lefèvre Kevin" },
          teacherTokens: { KBR: "jeton-kbr" },
        })}
      />,
    );
    expect(screen.getByRole("button", { name: "Copier" })).toBeInTheDocument();
    const ouvrir = screen.getByRole("link", { name: /ouvrir dans un nouvel onglet/i });
    expect(ouvrir).toHaveAttribute("target", "_blank");
    expect(ouvrir.getAttribute("href")).toContain("prof=KBR");
  });
});
