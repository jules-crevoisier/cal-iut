import { describe, expect, it } from "vitest";

import { anneeDepuisParcours, filtrerParcours, listerAnnees, parcoursPourSelect } from "./promoFilters";

const TOUS = ["BUT1", "BUT2-DEV-FI", "BUT2-CREA-FC", "BUT3-DEV-FI"];

describe("promoFilters", () => {
  it("should extract BUT year from parcours", () => {
    expect(anneeDepuisParcours("BUT1")).toBe("BUT1");
    expect(anneeDepuisParcours("BUT2-DEV-FI")).toBe("BUT2");
    expect(anneeDepuisParcours("autre")).toBeNull();
  });

  it("should list unique years sorted", () => {
    expect(listerAnnees(TOUS)).toEqual(["BUT1", "BUT2", "BUT3"]);
  });

  it("should filter by year only", () => {
    expect(filtrerParcours(TOUS, "BUT2", "Tout")).toEqual(["BUT2-CREA-FC", "BUT2-DEV-FI"]);
  });

  it("should filter by year and parcours", () => {
    expect(filtrerParcours(TOUS, "BUT2", "BUT2-DEV-FI")).toEqual(["BUT2-DEV-FI"]);
  });

  it("should return all when both filters are Tout", () => {
    expect(filtrerParcours(TOUS, "Tout", "Tout")).toEqual([...TOUS].sort((a, b) => a.localeCompare(b, "fr")));
  });

  it("should list parcours options for the selected year", () => {
    expect(parcoursPourSelect(TOUS, "BUT1")).toEqual(["BUT1"]);
    expect(parcoursPourSelect(TOUS, "Tout")).toHaveLength(4);
  });
});
