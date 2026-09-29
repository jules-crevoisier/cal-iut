import { describe, expect, it } from "vitest";

import { nomComplet, nomCourt } from "./nomEnseignant";

describe("nomCourt", () => {
  it("should abbreviate a fully upper-case name as first initial + surname", () => {
    expect(nomCourt("THOMAS PAVIE")).toBe("T. Pavie");
  });

  it("should take the upper-case words as the surname in a mixed-case name", () => {
    expect(nomCourt("Thomas CASTELLENGO")).toBe("T. Castellengo");
  });

  it("should keep hyphenated first names and surnames readable", () => {
    expect(nomCourt("Anne-Laure  Perrone")).toBe("A.-L. Perrone");
    expect(nomCourt("Alexia Petit-Halajko")).toBe("A. Petit-Halajko");
  });

  it("should keep accents and handle a single word", () => {
    expect(nomCourt("Barthélémy TOMASINA")).toBe("B. Tomasina");
    expect(nomCourt("Riguet")).toBe("Riguet");
    expect(nomCourt("")).toBe("");
  });
});

describe("nomComplet", () => {
  it("should normalise the case without abbreviating", () => {
    expect(nomComplet("THOMAS PAVIE")).toBe("Thomas Pavie");
    expect(nomComplet("Anne-Laure  Perrone")).toBe("Anne-Laure Perrone");
  });
});
