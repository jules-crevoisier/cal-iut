/**
 * Semaine / journée de SAE (tâches 14 et 18, 09/10/2026) : popup dédiée,
 * « ⚠ Semaine de SAE » + question + bouton « Forcer le placement ».
 */
import { describe, expect, it, vi } from "vitest";

import { texteEtOptionsForcage } from "./placement";

vi.mock("./confirmDialog", () => ({ confirmAsync: vi.fn(), alerterAsync: vi.fn() }));

const SEMAINE =
  "Semaine de SAE : ce créneau se situe pendant une semaine réservée à une SAE (WS501C). Placement possible en forçant.";
const JOURNEE = "Journée de SAE : ce créneau est dédié à une SAE (WS501C). Placement possible en forçant.";

describe("popup de forçage SAE", () => {
  it("titre « Semaine de SAE », phrase lisible puis la question", () => {
    const { texte, options } = texteEtOptionsForcage([SEMAINE], [], [], "Forcer le déplacement");
    expect(options.title).toBe("⚠ Semaine de SAE");
    expect(options.confirmLabel).toBe("Forcer le placement");
    expect(texte.startsWith("Ce créneau se situe pendant une semaine réservée à une SAE (WS501C).")).toBe(true);
    expect(texte).toContain("Voulez-vous malgré tout placer cette séance sur ce créneau ?");
    expect(texte).not.toContain("Placement possible en forçant");
  });

  it("titre « Journée de SAE » et les autres conflits restent listés", () => {
    const { texte, options } = texteEtOptionsForcage([JOURNEE, "Ordre pédagogique"], [], [], "Forcer");
    expect(options.title).toBe("⚠ Journée de SAE");
    expect(texte).toContain("Forçable aussi :\nOrdre pédagogique");
  });

  it("sans motif SAE, la popup ordinaire est inchangée", () => {
    const { options } = texteEtOptionsForcage(["Ordre pédagogique"], [], [], "Forcer le déplacement");
    expect(options.title).toBeUndefined();
    expect(options.confirmLabel).toBe("Forcer le déplacement");
  });
});
