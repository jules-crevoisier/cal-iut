/**
 * Vue « Occupé ailleurs » (02/10/2026, retour de Jules : l'écran Celcat →
 * Occupations hors MMI était « illisible »). Fonctions pures de
 * `frontend/src/utils/occupeAilleurs.ts`, testées sans DOM.
 *
 * ── Contrat du module `utils/occupeAilleurs.ts` ───────────────────────────
 *
 * Types réutilisés : `OccupationExterne`, `ConflitOccupationExterne`
 * (`types/app.ts`). `TypeRessource = "salle" | "enseignant"`.
 *
 * dateCourte(iso: string): string
 *   « 2026-10-08 » -> « jeu. 8 oct. » (jour abrégé, numéro sans zéro, mois
 *   abrégé, points compris). Date illisible ou vide : renvoie `iso` tel quel.
 *
 * horaire(debut: string, fin: string): string
 *   ("08:00", "10:00") -> « 08h00–10h00 » (tiret demi-cadratin U+2013).
 *
 * trierConflits(conflits: ConflitOccupationExterne[]): ConflitOccupationExterne[]
 *   Nouvelle liste (l'entrée n'est pas modifiée), triée par `date` puis
 *   `debut` (ordre alphabétique des chaînes ISO / « HH:MM »). Un conflit sans
 *   `date` (serveur ancien) passe après ceux qui en ont ; ordre d'arrivée
 *   conservé entre égaux.
 *
 * trierOccupations(occupations: OccupationExterne[]): OccupationExterne[]
 *   Idem, par `date` puis `debut`.
 *
 * type LibelleRessource = (type: TypeRessource, code: string) => string
 *   Fournie par la vue (libellé de la salle ou nom de l'enseignant dans le
 *   payload, à défaut le code).
 *
 * interface EntreeAnnuaire { type: TypeRessource; code: string; libelle: string; nombre: number }
 *
 * annuaireRessources(occupations: OccupationExterne[], libelle: LibelleRessource): EntreeAnnuaire[]
 *   Une entrée par couple (type, code), `nombre` = nombre d'occupations.
 *   Trié par `nombre` décroissant puis `libelle` croissant (localeCompare
 *   « fr », insensible aux accents et à la casse).
 *
 * compterDistincts(occupations: OccupationExterne[]): { salles: number; enseignants: number; creneauxSalles: number; creneauxEnseignants: number }
 *   `salles` / `enseignants` : nombre de codes distincts ;
 *   `creneauxSalles` / `creneauxEnseignants` : nombre d'occupations.
 *
 * interface FiltreOccupations {
 *   type?: "" | TypeRessource;                       // "" ou absent : tout
 *   ressource?: { type: TypeRessource; code: string } | null;
 *   texte?: string;
 *   libelle?: LibelleRessource;                      // défaut : le code
 * }
 * filtrerOccupations(occupations: OccupationExterne[], filtre: FiltreOccupations): OccupationExterne[]
 *   Garde les occupations qui satisfont TOUS les critères posés. `texte` :
 *   insensible à la casse et aux accents, espaces de bord ignorés, cherché
 *   dans le libellé de la ressource, son code, le département (`dep`) et
 *   l'intitulé (`lib`). L'ordre d'entrée est conservé.
 */
import { describe, expect, it } from "vitest";

import type { ConflitOccupationExterne, OccupationExterne } from "../types/app";
import {
  annuaireRessources,
  compterDistincts,
  dateCourte,
  filtrerOccupations,
  horaire,
  trierConflits,
  trierOccupations,
} from "./occupeAilleurs";

function occ(patch: Partial<OccupationExterne>): OccupationExterne {
  return {
    t: "salle",
    code: "h018",
    w: 3,
    d: 3,
    s: [0],
    date: "2026-10-08",
    debut: "08:00",
    fin: "10:00",
    dep: "TC",
    lib: "TC101 Anglais",
    cat: "[CM]",
    ...patch,
  };
}

function conflit(patch: Partial<ConflitOccupationExterne>): ConflitOccupationExterne {
  return {
    seance_id: "s1",
    course_code: "WR101",
    nom: "Culture numérique",
    type: "TD",
    semaine: 3,
    jour: 3,
    creneau: 0,
    groupes: [],
    enseignants: [],
    ressource_type: "salle",
    ressource: "h018",
    message: "message",
    date: "2026-10-08",
    debut: "08:00",
    fin: "10:00",
    ...patch,
  };
}

const LIBELLES: Record<string, string> = {
  "salle:h018": "H.018 (Amphi MMI)",
  "salle:a018": "A.018",
  "enseignant:AFR": "Anthony Froli",
  "enseignant:RHU": "Émilie Rhu",
};
const libelle = (type: "salle" | "enseignant", code: string) => LIBELLES[`${type}:${code}`] ?? code;

describe("dateCourte", () => {
  it("should write the weekday, the day without zero and the month when given an ISO date", () => {
    expect(dateCourte("2026-10-08")).toBe("jeu. 8 oct.");
    expect(dateCourte("2026-10-05")).toBe("lun. 5 oct.");
  });

  it("should give the text back unchanged when the date is unreadable", () => {
    expect(dateCourte("pas une date")).toBe("pas une date");
    expect(dateCourte("")).toBe("");
  });
});

describe("horaire", () => {
  it("should join start and end with h and an en dash", () => {
    expect(horaire("08:00", "10:00")).toBe("08h00–10h00");
    expect(horaire("14:00", "16:30")).toBe("14h00–16h30");
  });
});

describe("trierConflits", () => {
  it("should order by date then start time without mutating the input", () => {
    const a = conflit({ seance_id: "a", date: "2026-10-09", debut: "08:00" });
    const b = conflit({ seance_id: "b", date: "2026-10-08", debut: "14:00" });
    const c = conflit({ seance_id: "c", date: "2026-10-08", debut: "08:00" });
    const entree = [a, b, c];
    expect(trierConflits(entree).map((x) => x.seance_id)).toEqual(["c", "b", "a"]);
    expect(entree.map((x) => x.seance_id)).toEqual(["a", "b", "c"]);
  });

  it("should put conflicts without a date after the dated ones when the server is old", () => {
    const sansDate = conflit({ seance_id: "x", date: undefined, debut: undefined, fin: undefined });
    const date = conflit({ seance_id: "y", date: "2026-10-20" });
    expect(trierConflits([sansDate, date]).map((x) => x.seance_id)).toEqual(["y", "x"]);
  });

  it("should return an empty list when there is no conflict", () => {
    expect(trierConflits([])).toEqual([]);
  });
});

describe("trierOccupations", () => {
  it("should order by date then start time", () => {
    const tard = occ({ code: "a018", date: "2026-10-08", debut: "14:00" });
    const tot = occ({ code: "h018", date: "2026-10-08", debut: "08:00" });
    const veille = occ({ code: "b002", date: "2026-10-07", debut: "16:00" });
    expect(trierOccupations([tard, tot, veille]).map((x) => x.code)).toEqual(["b002", "h018", "a018"]);
  });
});

describe("annuaireRessources", () => {
  it("should count one entry per (type, code), most occupied first then by label", () => {
    const liste = [
      occ({ t: "salle", code: "h018" }),
      occ({ t: "salle", code: "h018" }),
      occ({ t: "salle", code: "h018" }),
      occ({ t: "enseignant", code: "RHU" }),
      occ({ t: "enseignant", code: "AFR" }),
      occ({ t: "salle", code: "a018" }),
      occ({ t: "enseignant", code: "AFR" }),
    ];
    expect(annuaireRessources(liste, libelle)).toEqual([
      { type: "salle", code: "h018", libelle: "H.018 (Amphi MMI)", nombre: 3 },
      { type: "enseignant", code: "AFR", libelle: "Anthony Froli", nombre: 2 },
      { type: "salle", code: "a018", libelle: "A.018", nombre: 1 },
      { type: "enseignant", code: "RHU", libelle: "Émilie Rhu", nombre: 1 },
    ]);
  });

  it("should keep a room and a teacher sharing the same code apart", () => {
    const liste = [occ({ t: "salle", code: "AFR" }), occ({ t: "enseignant", code: "AFR" })];
    expect(annuaireRessources(liste, libelle)).toHaveLength(2);
  });

  it("should fall back on the code given by the label function and return nothing when empty", () => {
    expect(annuaireRessources([occ({ code: "z999" })], libelle)[0].libelle).toBe("z999");
    expect(annuaireRessources([], libelle)).toEqual([]);
  });
});

describe("compterDistincts", () => {
  it("should count distinct rooms and teachers, and their slots", () => {
    const liste = [
      occ({ t: "salle", code: "h018" }),
      occ({ t: "salle", code: "h018", debut: "14:00" }),
      occ({ t: "salle", code: "a018" }),
      occ({ t: "enseignant", code: "AFR" }),
      occ({ t: "enseignant", code: "AFR", debut: "10:00" }),
      occ({ t: "enseignant", code: "AFR", debut: "16:00" }),
    ];
    expect(compterDistincts(liste)).toEqual({
      salles: 2,
      enseignants: 1,
      creneauxSalles: 3,
      creneauxEnseignants: 3,
    });
  });

  it("should return zeros when there is no occupation", () => {
    expect(compterDistincts([])).toEqual({ salles: 0, enseignants: 0, creneauxSalles: 0, creneauxEnseignants: 0 });
  });
});

describe("filtrerOccupations", () => {
  const liste = [
    occ({ t: "salle", code: "h018", dep: "TC", lib: "TC101 Anglais" }),
    occ({ t: "salle", code: "a018", dep: "CJ", lib: "Droit fiscal" }),
    occ({ t: "enseignant", code: "AFR", dep: "", lib: "Réunion pédagogique" }),
    occ({ t: "enseignant", code: "RHU", dep: "TC", lib: "Jury" }),
  ];

  it("should keep everything when no criterion is set", () => {
    expect(filtrerOccupations(liste, {})).toHaveLength(4);
    expect(filtrerOccupations(liste, { type: "", ressource: null, texte: "  " })).toHaveLength(4);
  });

  it("should keep only rooms or only teachers according to the type", () => {
    expect(filtrerOccupations(liste, { type: "salle" }).map((o) => o.code)).toEqual(["h018", "a018"]);
    expect(filtrerOccupations(liste, { type: "enseignant" }).map((o) => o.code)).toEqual(["AFR", "RHU"]);
  });

  it("should keep only the chosen resource", () => {
    const r = filtrerOccupations(liste, { ressource: { type: "enseignant", code: "AFR" } });
    expect(r.map((o) => o.code)).toEqual(["AFR"]);
  });

  it("should find by department, ignoring case", () => {
    expect(filtrerOccupations(liste, { texte: "tc" }).map((o) => o.code)).toEqual(["h018", "RHU"]);
  });

  it("should find by label, code and title, ignoring accents", () => {
    expect(filtrerOccupations(liste, { texte: "reunion" }).map((o) => o.code)).toEqual(["AFR"]);
    expect(filtrerOccupations(liste, { texte: "a018" }).map((o) => o.code)).toEqual(["a018"]);
    expect(filtrerOccupations(liste, { texte: "froli", libelle }).map((o) => o.code)).toEqual(["AFR"]);
    expect(filtrerOccupations(liste, { texte: "AMPHI", libelle }).map((o) => o.code)).toEqual(["h018"]);
  });

  it("should combine all the criteria and return nothing when nothing matches", () => {
    expect(filtrerOccupations(liste, { type: "salle", texte: "tc" }).map((o) => o.code)).toEqual(["h018"]);
    expect(filtrerOccupations(liste, { texte: "introuvable" })).toEqual([]);
  });
});
