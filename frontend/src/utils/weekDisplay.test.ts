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
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AppPayload } from "../types/app";

import { displayIndexForSolverWeek, isoWeekNumber, semaineCalendaireDepuisLundi } from "./weekDisplay";

afterEach(() => vi.useRealTimers());

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

describe("displayIndexForSolverWeek — liens publics (28/09/2026)", () => {
  // Jules : « sur les liens publics on arrive à la semaine en cours, c'est
  // quand même mieux ». Un lien personnel ne porte pas de semaine.
  const payload = {
    weekRows: [
      { monday: "2026-08-31", label: "Semaine 2", blocked: false, weekIndex: 0 },
      { monday: "2026-09-07", label: "Semaine 3", blocked: false, weekIndex: 1 },
      { monday: "2026-09-28", label: "Semaine 6", blocked: false, weekIndex: 4 },
    ],
  } as unknown as AppPayload;

  it("ouvre sur la semaine en cours quand le lien n'en porte aucune", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T09:00:00"));
    expect(displayIndexForSolverWeek(payload, null)).toBe(2);
  });

  it("respecte la semaine demandée par le lien, même passée", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T09:00:00"));
    expect(displayIndexForSolverWeek(payload, 0)).toBe(0);
  });

  it("retombe sur la semaine en cours si la semaine demandée n'existe pas", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T09:00:00"));
    expect(displayIndexForSolverWeek(payload, 99)).toBe(2);
  });
});
