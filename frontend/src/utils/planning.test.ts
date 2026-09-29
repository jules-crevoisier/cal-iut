import { describe, expect, it } from "vitest";

import type { AppRow, WeekRow } from "../types/app";
import type { IcsSession } from "./ics";
import {
  decouperLibelleSemaine,
  formatHeures,
  heuresDe,
  horaireSeance,
  jourAujourdhuiDansSemaine,
  jourRelatif,
  periodeBloquee,
  prochaineSeance,
  semaineDeReprise,
} from "./planning";

function seance(patch: Partial<IcsSession>): IcsSession {
  const base: AppRow = {
    id: "x", w: 0, d: 0, s: 0, c: "WR101", n: "Cours", t: "TD", g: [], te: [], r: "H.101",
    ev: false, dur: 1, locked: false, custom: false,
  };
  return { ...base, date: null, ...patch } as IcsSession;
}

describe("heures", () => {
  it("compte 1 h 30 par créneau, durée comprise", () => {
    expect(heuresDe([{ dur: 1 }, { dur: 2 }, { dur: 0 }])).toBe(6);
  });

  it("écrit les heures à la française", () => {
    expect(formatHeures(247.5)).toBe("247,5 h");
    expect(formatHeures(12)).toBe("12 h");
  });
});

describe("horaireSeance", () => {
  it("va du début du créneau à la fin du dernier créneau occupé", () => {
    expect(horaireSeance({ s: 1, dur: 1 }).libelle).toBe("9h30–11h");
    expect(horaireSeance({ s: 3, dur: 2 }).libelle).toBe("14h–17h");
  });

  it("préfère l'horaire libre quand il existe", () => {
    expect(horaireSeance({ s: 3, dur: 1, hor: "13h15–14h" })).toEqual({ debut: "13h15", fin: "14h", libelle: "13h15–14h" });
  });
});

describe("prochaineSeance", () => {
  const lundi = new Date(2026, 8, 28);
  const mardi = new Date(2026, 8, 29);
  const items = [
    seance({ id: "a", d: 0, s: 0, date: lundi }),
    seance({ id: "b", d: 1, s: 3, date: mardi }),
    seance({ id: "c", d: 1, s: 1, date: mardi }),
  ];

  it("donne la prochaine séance à venir, dans l'ordre chronologique", () => {
    const p = prochaineSeance(items, new Date(2026, 8, 28, 12, 0));
    expect(p?.item.id).toBe("c");
    expect(p?.enCours).toBe(false);
  });

  it("donne la séance en cours quand elle a commencé", () => {
    const p = prochaineSeance(items, new Date(2026, 8, 29, 14, 30));
    expect(p?.item.id).toBe("b");
    expect(p?.enCours).toBe(true);
  });

  it("ne donne rien quand tout est passé", () => {
    expect(prochaineSeance(items, new Date(2026, 9, 1))).toBeNull();
  });
});

describe("repères de date", () => {
  it("dit aujourd'hui et demain en toutes lettres", () => {
    const now = new Date(2026, 8, 29, 10);
    expect(jourRelatif(new Date(2026, 8, 29), now)).toBe("aujourd'hui");
    expect(jourRelatif(new Date(2026, 8, 30), now)).toBe("demain");
    expect(jourRelatif(new Date(2026, 9, 13), now)).toMatch(/13 oct/);
  });

  it("repère le jour d'aujourd'hui dans la semaine affichée, et rien ailleurs", () => {
    const payload = { weekDates: ["2026-09-28", "2026-10-05"] };
    expect(jourAujourdhuiDansSemaine(payload, 0, new Date(2026, 8, 30, 9))).toBe(2);
    expect(jourAujourdhuiDansSemaine(payload, 1, new Date(2026, 8, 30, 9))).toBeNull();
    expect(jourAujourdhuiDansSemaine(payload, 0, new Date(2026, 9, 3))).toBeNull();
  });

  it("sépare le numéro de semaine de ses dates", () => {
    expect(decouperLibelleSemaine("Semaine 6 (28 sept.–2 oct. 2026)")).toEqual({
      titre: "Semaine 6",
      dates: "28 sept.–2 oct. 2026",
    });
    expect(decouperLibelleSemaine("S1")).toEqual({ titre: "S1", dates: "" });
  });
});

describe("semaines bloquées", () => {
  const semaines: WeekRow[] = [
    { monday: "2026-10-19", label: "S9", blocked: false, weekIndex: 7 },
    { monday: "2026-10-26", label: "S10", blocked: true, weekIndex: null },
    { monday: "2026-11-02", label: "S11", blocked: false, weekIndex: 8 },
  ];

  it("retrouve la période de vacances qui explique la semaine bloquée", () => {
    const cal = [
      { label: "Armistice", start: "2026-11-11", end: "2026-11-11", kind: "ferie" as const },
      { label: "Pause pédagogique (Toussaint)", start: "2026-10-26", end: "2026-10-30", kind: "vacances" as const },
    ];
    expect(periodeBloquee(semaines[1], cal)?.label).toBe("Pause pédagogique (Toussaint)");
  });

  it("trouve la semaine de reprise", () => {
    expect(semaineDeReprise(semaines, 1)).toBe(2);
    expect(semaineDeReprise(semaines, 2)).toBeNull();
  });
});
