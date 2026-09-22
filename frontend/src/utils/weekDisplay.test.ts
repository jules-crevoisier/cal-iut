/**
 * Semaine calendaire (norme ISO-8601, celle qui contient le jeudi) affichée
 * en plus de la semaine universitaire du solveur.
 *
 * Retour utilisateur (todo département, Kyllian Bresson) : « indiquer la
 * semaine calendaire en même temps que la semaine universitaire, exemple
 * Lundi — Semaine 6 (28 sept.–2 oct. 2026) devient [...] semaine calendaire
 * 40 ». Calculée depuis le LUNDI réel de la semaine (`weekRows[].monday`),
 * jamais en reparsant le libellé — celui-ci peut contenir des vacances,
 * des tirets, etc., un format fragile à interroger.
 */
import { describe, expect, it } from "vitest";

import { isoWeekNumber, semaineCalendaireDepuisLundi } from "./weekDisplay";

describe("isoWeekNumber", () => {
  it("should return 53 for 2026-12-28 (Monday of the last ISO week of 2026)", () => {
    expect(isoWeekNumber(new Date(2026, 11, 28))).toBe(53);
  });

  it("should return 53 for 2027-01-01 (still in 2026's last ISO week)", () => {
    expect(isoWeekNumber(new Date(2027, 0, 1))).toBe(53);
  });

  it("should return 1 for 2027-01-04 (Monday of the first ISO week of 2027)", () => {
    expect(isoWeekNumber(new Date(2027, 0, 4))).toBe(1);
  });

  it("should return 40 for 2026-09-28", () => {
    expect(isoWeekNumber(new Date(2026, 8, 28))).toBe(40);
  });
});

describe("semaineCalendaireDepuisLundi", () => {
  it("should compute the ISO week number from a monday ISO date string", () => {
    expect(semaineCalendaireDepuisLundi("2026-09-28")).toBe(40);
  });

  it("should return null for an empty or missing monday (semaine bloquée sans date)", () => {
    expect(semaineCalendaireDepuisLundi("")).toBeNull();
    expect(semaineCalendaireDepuisLundi(undefined)).toBeNull();
  });
});
