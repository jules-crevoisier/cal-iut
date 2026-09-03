/**
 * Messages de contraintes unifiés : blocking + forçable + soft.
 */
import { describe, expect, it } from "vitest";

import { detailConflit, texteContraintes } from "./placement";

describe("texteContraintes", () => {
  it("should list blocking, forceable and soft sections", () => {
    const texte = texteContraintes({
      blocking_conflicts: ["Jour férié"],
      hard_conflicts: ["Enseignant indisponible (MRI)"],
      soft_warnings: ["Capacité salle juste"],
    });
    expect(texte).toContain("Impossible (non forçable)");
    expect(texte).toContain("Jour férié");
    expect(texte).toContain("Forçable");
    expect(texte).toContain("Enseignant indisponible");
    expect(texte).toContain("Avertissement");
    expect(texte).toContain("Capacité salle juste");
  });

  it("should parse blocking_conflicts from error JSON", () => {
    const err = new Error(
      JSON.stringify({
        hard_conflicts: ["Ordre pédagogique"],
        soft_warnings: [],
        blocking_conflicts: ["PAC"],
      }),
    );
    expect(detailConflit(err)?.blocking_conflicts).toEqual(["PAC"]);
  });
});
