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

  it("should never repeat a blocking motive under Forçable", () => {
    // `blocking_conflicts` est par contrat un SOUS-ENSEMBLE de
    // `hard_conflicts` (cf. schemas.ValidationResponse). Lister
    // `hard_conflicts` en entier sous « Forçable » affichait donc TOUT motif
    // bloquant deux fois — signalé le 08/09/2026, capture à l'appui : le
    // même « Enseignant indisponible (RDE) » sous « Impossible » ET sous
    // « Forçable », ce qui laisse croire qu'on peut forcer ce qui est
    // justement non forçable.
    const texte = texteContraintes({
      blocking_conflicts: ["Jeudi PAC"],
      hard_conflicts: ["Jeudi PAC", "Enseignant indisponible (MRI)"],
      soft_warnings: [],
    });

    expect(texte.match(/Jeudi PAC/g)).toHaveLength(1);
    expect(texte).toContain("Enseignant indisponible (MRI)");
  });

  it("should omit the Forçable section when everything is blocking", () => {
    const texte = texteContraintes({
      blocking_conflicts: ["Jeudi PAC"],
      hard_conflicts: ["Jeudi PAC"],
      soft_warnings: [],
    });

    expect(texte).toContain("Impossible (non forçable)");
    expect(texte).not.toContain("Forçable :");
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
