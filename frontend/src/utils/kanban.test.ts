import { describe, expect, it } from "vitest";

import { emptyPayload, placedRow } from "../test/payloadFixture";
import { estArchivee, rapportTaches, texteTache, dateReelleRow, libelleDatesTache, routeVersSeance, seancesConcernees } from "./kanban";

const payload = emptyPayload({
  weekRows: [
    { monday: "2026-09-21", label: "Semaine du 21/09", blocked: false, weekIndex: 0 },
    { monday: "2026-09-28", label: "Semaine du 28/09", blocked: false, weekIndex: 1 },
  ],
  teacherLabels: { KBR: "Kyllian Bresson" },
  rows: [
    placedRow({ id: "s1", w: 0, d: 0, s: 0, te: ["KBR"], c: "WR106" }), // lundi 21/09
    placedRow({ id: "s2", w: 0, d: 3, s: 1, te: ["KBR"], c: "WR107" }), // jeudi 24/09
    placedRow({ id: "s3", w: 1, d: 0, s: 0, te: ["KBR"], c: "WR108" }), // lundi 28/09
    placedRow({ id: "s4", w: 0, d: 0, s: 0, te: ["AUT"], c: "WR109" }), // autre enseignant, même jour
  ],
});

describe("dateReelleRow", () => {
  it("computes the real ISO date from the week's monday plus the day offset", () => {
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 0, d: 0 }))).toBe("2026-09-21");
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 0, d: 3 }))).toBe("2026-09-24");
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 1, d: 2 }))).toBe("2026-09-30");
  });

  it("returns null when the row's week has no known monday", () => {
    expect(dateReelleRow(payload, placedRow({ id: "x", w: 99, d: 0 }))).toBeNull();
  });
});

describe("seancesConcernees", () => {
  it("returns nothing when the tache has no teacher", () => {
    expect(seancesConcernees(payload, { enseignant_code: null, date_debut: "2026-09-21", date_fin: null })).toEqual([]);
  });

  it("returns nothing when the tache has no date_debut", () => {
    expect(seancesConcernees(payload, { enseignant_code: "KBR", date_debut: null, date_fin: null })).toEqual([]);
  });

  it("filters by teacher, excluding sessions of another teacher on the same day", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-21", date_fin: "2026-10-05" });
    expect(result.map((r) => r.row.id)).not.toContain("s4");
  });

  it("treats a missing date_fin as a single-day range (date_debut only)", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-21", date_fin: null });
    expect(result.map((r) => r.row.id)).toEqual(["s1"]);
  });

  it("includes every session across a multi-day range", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-21", date_fin: "2026-09-28" });
    expect(result.map((r) => r.row.id)).toEqual(["s1", "s2", "s3"]);
  });

  it("excludes sessions outside the declared range", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-22", date_fin: "2026-09-27" });
    expect(result.map((r) => r.row.id)).toEqual(["s2"]);
  });

  it("sorts results chronologically", () => {
    const result = seancesConcernees(payload, { enseignant_code: "KBR", date_debut: "2026-09-01", date_fin: "2026-10-01" });
    expect(result.map((r) => r.dateIso)).toEqual(["2026-09-21", "2026-09-24", "2026-09-28"]);
  });
});

describe("routeVersSeance", () => {
  it("sends the raw solver week index as sem, never a display index", () => {
    expect(routeVersSeance(placedRow({ id: "x", w: 7, d: 2 }))).toEqual({ vue: "promo", sem: 7, jour: 2 });
  });
});

describe("libelleDatesTache", () => {
  it("returns null without a start date", () => {
    expect(libelleDatesTache(null, null)).toBeNull();
  });

  it("formats a single day", () => {
    expect(libelleDatesTache("2026-09-25", null)).toBe("25 sept. 2026");
  });

  it("formats identical start/end as a single day", () => {
    expect(libelleDatesTache("2026-09-25", "2026-09-25")).toBe("25 sept. 2026");
  });

  it("formats a multi-day range", () => {
    expect(libelleDatesTache("2026-09-25", "2026-10-02")).toBe("25 sept. – 2 oct. 2026");
  });
});

describe("texteTache — bouton Copier (28/09/2026)", () => {
  // Jules : « un petit bouton copier qui copie toutes les infos d'une tâche ».
  const base = {
    titre: "Déplacer les TD de KBR",
    description: "Il sera en formation.",
    colonne: "a_faire",
    categorie: "edt",
    priorite: "normale",
    concerne: "Jules",
    enseignant_code: "KBR",
    date_debut: "2026-10-08",
    date_fin: null,
    cree_par: "kyllian.bresson@univ-reims.fr",
  };

  it("reprend tout ce que la carte affiche", () => {
    const texte = texteTache(base, { nomEnseignant: "Kyllian Bresson" });
    expect(texte).toContain("Déplacer les TD de KBR");
    expect(texte).toContain("Emploi du temps · À faire · pour Jules");
    expect(texte).toContain("Enseignant : Kyllian Bresson");
    expect(texte).toMatch(/Dates : 8 oct\. 2026/);
    expect(texte).toContain("Il sera en formation.");
    expect(texte).toContain("Créée par kyllian.bresson@univ-reims.fr");
  });

  it("annonce l'urgence en tête", () => {
    expect(texteTache({ ...base, priorite: "urgente" })).toMatch(/^\[Urgent\] /);
  });

  it("liste les séances concernées, la raison d'être de la carte", () => {
    const texte = texteTache(base, {
      seances: [
        { row: { id: "s1", c: "WR107", s: 1, w: 5, d: 3, g: [], te: ["KBR"] } as never, dateIso: "2026-10-08" },
      ],
      libelleSeance: ({ row }) => `jeudi 8 oct. · ${row.c}`,
    });
    expect(texte).toContain("Séances concernées (1) :");
    expect(texte).toContain("  - jeudi 8 oct. · WR107");
  });

  it("ne met pas de ligne vide pour ce qui n'est pas renseigné", () => {
    const texte = texteTache({ titre: "À trier", colonne: "a_faire" });
    expect(texte).toBe("À trier\nEmploi du temps · À faire");
  });

  it("donne le numéro de la tâche, comme le rapport", () => {
    expect(texteTache({ id: 7, titre: "À trier", colonne: "a_faire" })).toMatch(/^À trier \(#7\)\n/);
  });
});

describe("rapportTaches", () => {
  const base = {
    colonne: "a_faire",
    categorie: "plateforme",
    priorite: "normale",
    concerne: null,
    enseignant_code: null,
    date_debut: null,
    date_fin: null,
    description: null,
    cree_par: "jules@univ.fr",
  };

  it("lists every column with its tasks and details, in Markdown", () => {
    const texte = rapportTaches(
      [
        {
          id: "a_faire",
          label: "À faire",
          taches: [
            {
              ...base,
              id: 3,
              titre: "Bouton cassé",
              priorite: "urgente",
              concerne: "Jules",
              description: "Ligne 1\n\nLigne 2",
              images: [{ nom: "capture.png" }],
            },
          ],
        },
        { id: "en_cours", label: "En cours", taches: [] },
        { id: "fait", label: "Fait", taches: [{ ...base, id: 4, titre: "Fini", colonne: "fait" }] },
      ],
      { categorie: "plateforme", filtres: ["pour Jules"], maintenant: new Date("2026-10-09T15:00:00") },
    );
    expect(texte).toContain("# Rapport des tâches — Plateforme");
    expect(texte).toContain("2 tâches : À faire 1, En cours 0, Fait 1.");
    expect(texte).toContain("Filtres actifs : pour Jules.");
    expect(texte).toContain("### [Urgent] Bouton cassé (#3)");
    expect(texte).toContain("- Pour : Jules");
    expect(texte).toContain("- Images jointes (1) : capture.png");
    expect(texte).toContain("> Ligne 1\n>\n> Ligne 2");
    expect(texte).toContain("## En cours (0)\n\nAucune tâche.");
    expect(texte).toContain("### Fini (#4)\n\n- Statut : Fait");
  });

  it("adds teacher and concerned sessions through the callbacks", () => {
    const texte = rapportTaches(
      [{ id: "a_faire", label: "À faire", taches: [{ ...base, id: 1, titre: "Absence", enseignant_code: "KBR" }] }],
      { nomEnseignant: () => "Kyllian Bresson", seances: () => ["lun. 21 sept. · WR106"] },
    );
    expect(texte).toContain("- Enseignant : Kyllian Bresson");
    expect(texte).toContain("- Séances concernées (1) :\n  - lun. 21 sept. · WR106");
  });
});

describe("estArchivee", () => {
  const maintenant = new Date("2026-10-09T12:00:00");

  it("archives a task done more than two weeks ago", () => {
    expect(estArchivee({ colonne: "fait", fait_le: "2026-09-24T10:00:00" }, maintenant)).toBe(true);
  });

  it("keeps a task done less than two weeks ago in the column", () => {
    expect(estArchivee({ colonne: "fait", fait_le: "2026-09-26T10:00:00" }, maintenant)).toBe(false);
  });

  it("never archives a task that is not done, or done without a date", () => {
    expect(estArchivee({ colonne: "en_cours", fait_le: "2026-01-01T10:00:00" }, maintenant)).toBe(false);
    expect(estArchivee({ colonne: "fait", fait_le: null }, maintenant)).toBe(false);
    expect(estArchivee({ colonne: "fait", fait_le: "pas une date" }, maintenant)).toBe(false);
  });
});
