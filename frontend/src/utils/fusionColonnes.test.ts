import { describe, expect, it } from "vitest";

import { cleSeances, fusionnerColonnes } from "./fusionColonnes";

// BUT1 : TP A→D, TD AB = {A, B}, TD CD = {C, D} ; puis un second parcours.
const PARCOURS = ["BUT1", "BUT1", "BUT1", "BUT1", "BUT2", "BUT2"];
const fusion = (contenus: string[][]) =>
  fusionnerColonnes(
    contenus.length,
    (i) => cleSeances(contenus[i]),
    (i) => PARCOURS[i],
  );

describe("fusionnerColonnes — un TD, une case ; un CM, une case", () => {
  it("un TD AB n'occupe qu'une case pour les TP A et B", () => {
    expect(fusion([["td-ab"], ["td-ab"], ["td-cd"], ["td-cd"], [], []])).toEqual([2, 0, 2, 0, 1, 1]);
  });

  it("un CM occupe une seule case pour toute la promo, sans déborder sur la suivante", () => {
    expect(fusion([["cm"], ["cm"], ["cm"], ["cm"], ["cm"], ["cm"]])).toEqual([4, 0, 0, 0, 2, 0]);
  });

  it("des TP différents restent séparés", () => {
    expect(fusion([["tp-a"], ["tp-b"], [], [], [], []])).toEqual([1, 1, 1, 1, 1, 1]);
  });

  it("un conflit reste visible : colonnes au contenu différent non fusionnées", () => {
    expect(fusion([["td-ab", "tp-a"], ["td-ab"], [], [], [], []])).toEqual([1, 1, 1, 1, 1, 1]);
  });

  it("l'ordre des séances dans une case ne change rien", () => {
    expect(fusion([["x", "y"], ["y", "x"], [], [], [], []])).toEqual([2, 0, 1, 1, 1, 1]);
  });

  it("les cases vides ne fusionnent jamais : chacune reste une cible de dépôt", () => {
    expect(fusion([[], [], [], [], [], []])).toEqual([1, 1, 1, 1, 1, 1]);
  });
});
