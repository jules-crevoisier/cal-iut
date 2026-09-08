/**
 * Ouvrir le planning sur la semaine EN COURS.
 *
 * Retour utilisateur 08/09/2026 : « fais en sorte que dans vue promo on
 * arrive directement dans la semaine actuelle sélectionnée ». L'application
 * s'ouvrait sur la première semaine de l'année — celle dont on n'a plus
 * besoin dès la deuxième semaine de cours, et qui oblige à cliquer à chaque
 * ouverture.
 *
 * Le repère est le LUNDI de chaque ligne, pas un compteur : les semaines
 * bloquées (vacances) créent des trous dans `weekRows`, et compter les
 * lignes depuis la rentrée donnerait la mauvaise dès la Toussaint passée.
 */
import { describe, expect, it } from "vitest";

import { indexSemaineCourante, jourOuvreAujourdhui } from "./semaineCourante";

const SEMAINES = [
  { monday: "2026-08-31", label: "Semaine 1", blocked: false, weekIndex: 0 },
  { monday: "2026-09-07", label: "Semaine 2", blocked: false, weekIndex: 1 },
  { monday: "2026-09-14", label: "Semaine 3", blocked: false, weekIndex: 2 },
  { monday: "2026-10-26", label: "Toussaint", blocked: true, weekIndex: null },
  { monday: "2026-11-02", label: "Semaine 9", blocked: false, weekIndex: 8 },
];

describe("indexSemaineCourante", () => {
  it("trouve la semaine qui contient aujourd'hui", () => {
    // mardi 8 septembre : dans la semaine du lundi 7.
    expect(indexSemaineCourante(SEMAINES, new Date("2026-09-08T10:00:00"))).toBe(1);
  });

  it("tient le lundi lui-même", () => {
    expect(indexSemaineCourante(SEMAINES, new Date("2026-09-07T08:00:00"))).toBe(1);
  });

  it("tient le dimanche qui clôt la semaine", () => {
    expect(indexSemaineCourante(SEMAINES, new Date("2026-09-13T23:00:00"))).toBe(1);
  });

  it("rend une semaine bloquée si c'est là qu'on est", () => {
    // Pendant les vacances, ouvrir sur la ligne correspondante reste plus
    // juste que de renvoyer au début de l'année.
    expect(indexSemaineCourante(SEMAINES, new Date("2026-10-28T10:00:00"))).toBe(3);
  });

  it("retombe sur la première semaine avant la rentrée", () => {
    // En août, aucune semaine ne contient la date : ouvrir sur la première
    // est le comportement d'origine, et il reste le bon.
    expect(indexSemaineCourante(SEMAINES, new Date("2026-08-01T10:00:00"))).toBe(0);
  });

  it("retombe sur la dernière semaine après la fin de l'année", () => {
    // Plutôt que de renvoyer en septembre : ce qu'on consulte en juillet,
    // c'est la fin de l'année écoulée.
    expect(indexSemaineCourante(SEMAINES, new Date("2027-07-01T10:00:00"))).toBe(4);
  });

  it("ne plante pas sans semaines", () => {
    expect(indexSemaineCourante([], new Date())).toBe(0);
  });

  it("ignore une date de lundi illisible", () => {
    const abimees = [{ monday: "pas une date", label: "?", blocked: false, weekIndex: 0 }];
    expect(indexSemaineCourante(abimees, new Date("2026-09-08T10:00:00"))).toBe(0);
  });
});

describe("jourOuvreAujourdhui", () => {
  it("rend l'index du jour en cours, lundi = 0", () => {
    expect(jourOuvreAujourdhui(new Date("2026-09-07T10:00:00"))).toBe(0); // lundi
    expect(jourOuvreAujourdhui(new Date("2026-09-08T10:00:00"))).toBe(1); // mardi
    expect(jourOuvreAujourdhui(new Date("2026-09-11T10:00:00"))).toBe(4); // vendredi
  });

  it("retombe sur lundi le week-end", () => {
    // Aucun cours le samedi : ouvrir sur une colonne vide serait pire que
    // sur le premier jour de la semaine qu'on s'apprête à préparer.
    expect(jourOuvreAujourdhui(new Date("2026-09-12T10:00:00"))).toBe(0); // samedi
    expect(jourOuvreAujourdhui(new Date("2026-09-13T10:00:00"))).toBe(0); // dimanche
  });
});
