/**
 * Occupations hors MMI (Celcat, 01/10/2026) côté écran : blocs « Occupé
 * ailleurs », salles libres, fraîcheur, et « À traiter » — même fixture et
 * mêmes valeurs que `tests/test_occupations_externes_2026_10_01.py::
 * test_forme_du_point_comme_le_frontend` (parité).
 */
import { describe, expect, it } from "vitest";

import { catalogRoom, emptyPayload } from "../test/payloadFixture";
import type { ConflitOccupationExterne, OccupationExterne, OccupationsExternesPayload } from "../types/app";
import {
  bandeauFraicheur,
  detailOccupation,
  libelleOccupation,
  libellesParCase,
  lignesOccupation,
  lignesParCase,
  occupationsParCase,
} from "./occupationsExternes";
import { sallesLibresAuCreneau } from "./sallesLibres";
import { buildTodoList, NATURE_PAR_ID } from "./todo";

const AFR: OccupationExterne = {
  t: "enseignant",
  code: "AFR",
  w: 9,
  d: 0,
  s: [1, 2],
  date: "2026-11-09",
  debut: "10:00",
  fin: "12:30",
  dep: "TC",
  lib: "Marketing digital",
  cat: "[CM]",
};
const AMPHI: OccupationExterne = {
  t: "salle",
  code: "h018",
  w: 9,
  d: 1,
  s: [3, 4],
  date: "2026-11-10",
  debut: "14:00",
  fin: "17:00",
  dep: "",
  lib: "Conseil de département",
  cat: "Réunion",
};

// Même fixture que le test Python.
const CONFLIT: ConflitOccupationExterne = {
  seance_id: "td-afr",
  course_code: "WR101",
  nom: "Culture numérique",
  type: "TD",
  semaine: 9,
  jour: 0,
  creneau: 1,
  groupes: ["but1-td-ab"],
  enseignants: ["AFR"],
  ressource_type: "enseignant",
  ressource: "AFR",
  message:
    "Enseignant indisponible — Anthony Froli est déjà programmé dans le département TC sur ce créneau (lundi 09/11, 10h00–12h30, Celcat).",
};

function oe(partiel: Partial<OccupationsExternesPayload> = {}): OccupationsExternesPayload {
  return {
    releveLe: new Date().toISOString(),
    ageSecondes: 0,
    absent: false,
    perime: false,
    fraicheurHeures: 6,
    strict: false,
    erreur: null,
    occupations: [AFR, AMPHI],
    conflits: [],
    ...partiel,
  };
}

describe("occupations hors MMI", () => {
  it("libellés des blocs discrets", () => {
    expect(libelleOccupation(AFR)).toBe("Occupé ailleurs (TC)");
    expect(libelleOccupation(AMPHI)).toBe("Réservé dans Celcat (administration)");
    expect(detailOccupation(AFR)).toBe("10h00–12h30 · TC · [CM] Marketing digital");
  });

  it("range les occupations d'un enseignant par case de la semaine", () => {
    const payload = emptyPayload({ occupationsExternes: oe() });
    const cases = libellesParCase(occupationsParCase(payload, "enseignant", "AFR", 9));
    expect([...cases.keys()].sort()).toEqual(["0-1", "0-2"]);
    expect(cases.get("0-1")).toEqual(["Occupé ailleurs (TC)"]);
    expect(occupationsParCase(payload, "enseignant", "AFR", 8).size).toBe(0);
    expect(occupationsParCase(payload, "enseignant", "KBR", 9).size).toBe(0);
  });

  it("une salle fusionnée voit l'occupation de sa moitié", () => {
    const payload = emptyPayload({
      rooms: [
        catalogRoom("h007", { label: "H.007" }),
        catalogRoom("h007_h008", { label: "H.007-008", combines: ["h007", "h008"] }),
      ],
      occupationsExternes: oe({ occupations: [{ ...AMPHI, code: "h007" }] }),
    });
    expect(occupationsParCase(payload, "salle", "h007_h008", 9).get("1-3")).toHaveLength(1);
  });

  it("une salle réservée dans Celcat n'est pas proposée dans les salles libres", () => {
    const payload = emptyPayload({
      rooms: [catalogRoom("h018", { label: "H.018 (Amphi MMI)", capacity: 150, type: "amphi" })],
      occupationsExternes: oe(),
    });
    expect(sallesLibresAuCreneau(payload, 9, 1, 3).map((r) => r.id)).toEqual([]);
    expect(sallesLibresAuCreneau(payload, 9, 1, 5).map((r) => r.id)).toEqual(["h018"]);
  });

  it("bandeau de fraîcheur : rien si frais ou absent, l'âge sinon", () => {
    const maintenant = new Date("2026-10-01T15:00:00Z");
    expect(bandeauFraicheur(emptyPayload(), maintenant)).toBeNull();
    expect(bandeauFraicheur(emptyPayload({ occupationsExternes: oe({ releveLe: "2026-10-01T12:00:00Z" }) }), maintenant)).toBeNull();
    expect(
      bandeauFraicheur(emptyPayload({ occupationsExternes: oe({ releveLe: "2026-10-01T06:00:00Z" }) }), maintenant),
    ).toMatch(/^Occupations Celcat relevées il y a 9 h/);
    expect(bandeauFraicheur(emptyPayload({ occupationsExternes: oe({ releveLe: null, absent: true }) }), maintenant)).toBeNull();
  });

  it("« À traiter » : même point que le miroir serveur (parité)", () => {
    const items = buildTodoList(
      emptyPayload({ groupParcours: { "but1-td-ab": "BUT1" }, occupationsExternes: oe({ conflits: [CONFLIT] }) }),
    );
    const p = items.find((i) => i.nature === "occupation-externe");
    expect(p).toBeDefined();
    expect({
      nature: p!.nature,
      cle: p!.cle,
      titre: p!.title,
      detail: p!.sub,
      semaine: p!.semaine,
      jour: p!.jour,
      creneau: p!.creneau,
      parcours: p!.parcours,
      enseignants: p!.enseignants,
      nombre: p!.n,
    }).toEqual({
      nature: "occupation-externe",
      cle: "oe|td-afr|enseignant|AFR",
      titre: "WR101 — Culture numérique",
      detail: CONFLIT.message,
      semaine: 9,
      jour: 0,
      creneau: 1,
      parcours: ["BUT1"],
      enseignants: ["AFR"],
      nombre: 1,
    });
    // 02/10/2026 soir : alerte molle, même gravité que « Encadrement SAE ».
    expect(p!.sev).toBe("warn");
    expect(NATURE_PAR_ID["occupation-externe"].sev).toBe("warn");
    expect(p!.route).toEqual({ vue: "prof", prof: "AFR", sem: 9 });
  });
});

/**
 * 02/10/2026 soir — occupations sur le planning, en grisé (retour de Jules).
 *
 * Contrat du module `utils/occupationsExternes.ts` :
 *
 *     interface LigneOccupation { qui: string; quoi: string; horaire: string; detail: string }
 *     lignesOccupation(o: OccupationExterne): LigneOccupation
 *     lignesParCase(parCase: Map<string, OccupationExterne[]>): Map<string, LigneOccupation[]>
 *
 *  - `qui`     : le département, « Administration » s'il est vide ;
 *  - `quoi`    : l'intitulé, à défaut la catégorie ;
 *  - `horaire` : « 09h00–11h00 » (début–fin, « : » devient « h ») ;
 *  - `detail`  : texte complet pour `title` : catégorie, intitulé, horaire, département ;
 *  - `lignesParCase` : mêmes clés « jour-créneau » que `occupationsParCase`,
 *    une ligne par occupation, sans doublon.
 *
 * `SessionGrid.externes` devient `Map<string, LigneOccupation[]>`
 * (cf. `components/SessionGrid.externes.test.tsx`).
 */
describe("occupations sur le planning (02/10/2026 soir)", () => {
  const TD_TC: OccupationExterne = {
    t: "enseignant",
    code: "AFR",
    w: 9,
    d: 0,
    s: [1],
    date: "2026-11-09",
    debut: "09:00",
    fin: "11:00",
    dep: "TC",
    lib: "RR113 Numérique",
    cat: "TD",
  };

  it("should name the department as qui and format the horaire when the occupation has a department", () => {
    const ligne = lignesOccupation(TD_TC);
    expect(ligne.qui).toBe("TC");
    expect(ligne.quoi).toBe("RR113 Numérique");
    expect(ligne.horaire).toBe("09h00–11h00");
  });

  it("should write Administration as qui when the department is empty", () => {
    expect(lignesOccupation({ ...TD_TC, t: "salle", code: "h018", dep: "" }).qui).toBe("Administration");
  });

  it("should fall back to the category as quoi when the title is empty", () => {
    expect(lignesOccupation({ ...TD_TC, lib: "", cat: "Réunion" }).quoi).toBe("Réunion");
  });

  it("should put category, title, horaire and department in the detail", () => {
    const { detail } = lignesOccupation(TD_TC);
    for (const morceau of ["TD", "RR113 Numérique", "09h00–11h00", "TC"]) expect(detail).toContain(morceau);
  });

  it("should give one line per occupation on each case of the week", () => {
    const payload = emptyPayload({ occupationsExternes: oe({ occupations: [AFR, { ...TD_TC, s: [1, 2] }] }) });
    const cases = lignesParCase(occupationsParCase(payload, "enseignant", "AFR", 9));
    expect([...cases.keys()].sort()).toEqual(["0-1", "0-2"]);
    expect(cases.get("0-1")?.map((l) => l.horaire)).toEqual(["10h00–12h30", "09h00–11h00"]);
    expect(cases.get("0-2")).toHaveLength(2);
  });

  it("should give nothing when the resource has no occupation that week", () => {
    const payload = emptyPayload({ occupationsExternes: oe() });
    expect(lignesParCase(occupationsParCase(payload, "enseignant", "RHU", 9)).size).toBe(0);
  });

  it("should word « À traiter » as a soft alert, Pris ailleurs dans Celcat, when the nature is listed", () => {
    const nature = NATURE_PAR_ID["occupation-externe"];
    expect(nature.sev).toBe(NATURE_PAR_ID["compromis-sae"].sev);
    expect(nature.titre).toBe("Pris ailleurs dans Celcat");
    expect(nature.court).toBe("Pris ailleurs");
    expect(nature.aide).toBe(
      "L'enseignant ou la salle est aussi pris dans Celcat (autre département, réunion, réservation) sur le créneau d'une séance placée. À revoir : rien n'est bloqué.",
    );
  });

  it("should flag the todo item as warn, not bad, when a placed session sits on an occupation", () => {
    const items = buildTodoList(
      emptyPayload({ groupParcours: { "but1-td-ab": "BUT1" }, occupationsExternes: oe({ conflits: [CONFLIT] }) }),
    );
    expect(items.find((i) => i.nature === "occupation-externe")?.sev).toBe("warn");
  });
});
