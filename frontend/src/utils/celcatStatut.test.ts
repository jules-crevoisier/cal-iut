/**
 * Ce que l'écran Celcat affirme — calme quand ça va, rouge quand ça casse.
 *
 * Critique design du 16/09/2026 : « Tout concorde » était gris, « relevé
 * périmé » en noir, et la seule couleur forte de la page était le rouge de
 * « ÉCRITURE ON », l'état NORMAL. Ces tests tiennent la règle inverse.
 */
import { describe, expect, it } from "vitest";

import type { CelcatComparaison, CelcatEtat, CelcatFile, CelcatInstantane, LigneComparaison } from "../api/client";
import { ageLisible, dateLisible, jourDate, signauxSysteme, verdictSemaine } from "./celcatStatut";

const ETAT: CelcatEtat = {
  saisie_active: true,
  worker_actif: true,
  semaines_validees: [],
  semaines_passees: [],
  semaines_lancees: [],
  semaines_completes: [],
  valide_le: null,
  dernier_job: null,
  derniere_ecriture_celcat: null,
  compteurs: { created: 0, modified: 0, deleted: 0, blocked: 0 },
  worker_ok: true,
};

const RELEVE: CelcatInstantane = {
  evenements: [],
  groupes: [],
  releve_le: "2026-09-16T10:00:00+00:00",
  age_secondes: 600,
  perime: false,
  demande_en_cours: false,
  erreur: null,
};

const FILE: CelcatFile = {
  en_attente: 0,
  par_action: {},
  passe_le: "2026-09-16T10:05:00+00:00",
  age_secondes: 40,
  reussis: 3,
  echecs: 0,
  ignores: 0,
  differes: 0,
  resume: "",
};

function ligne(statut: LigneComparaison["statut"]): LigneComparaison {
  return { statut, session_id: `s-${statut}`, course_code: "WR101", caliut: null, celcat: null, ecarts: [] };
}

function comparaison(lignes: LigneComparaison[], extra: Partial<CelcatComparaison> = {}): CelcatComparaison {
  return {
    semaine: 2,
    semaine_celcat: 5,
    lundi: "2026-09-14",
    releve_le: "2026-09-16T10:00:00+00:00",
    age_secondes: 300,
    perime: false,
    lignes,
    ...extra,
  };
}

describe("signaux du système", () => {
  it("dit « active » en ton calme quand l'écriture fonctionne", () => {
    const [ecriture] = signauxSysteme(ETAT, RELEVE, FILE);
    expect(ecriture.etat).toBe("active");
    expect(ecriture.ton).toBe("ok");
  });

  it("réserve le rouge à l'écriture COUPÉE", () => {
    const [ecriture] = signauxSysteme({ ...ETAT, saisie_active: false }, RELEVE, FILE);
    expect(ecriture.etat).toBe("coupée");
    expect(ecriture.ton).toBe("panne");
  });

  it("distingue une pause voulue d'un worker muet", () => {
    const pause = signauxSysteme({ ...ETAT, worker_actif: false }, RELEVE, FILE)[1];
    const muet = signauxSysteme({ ...ETAT, worker_ok: false }, RELEVE, FILE)[1];
    expect([pause.etat, pause.ton]).toEqual(["en pause", "attention"]);
    expect([muet.etat, muet.ton]).toEqual(["muet", "panne"]);
  });

  it("dit qu'aucun relevé n'existe, sans faire croire que Celcat est vide", () => {
    const releve = signauxSysteme(ETAT, { ...RELEVE, releve_le: null }, FILE)[2];
    expect(releve.etat).toBe("aucun");
    expect(releve.detail).toMatch(/pas encore été relu/);
  });

  it("remonte la raison d'un relevé en échec", () => {
    const releve = signauxSysteme(ETAT, { ...RELEVE, erreur: "Celcat injoignable : VPN" }, FILE)[2];
    expect([releve.etat, releve.ton]).toEqual(["en échec", "panne"]);
    expect(releve.detail).toContain("VPN");
  });

  it("signale un relevé périmé au lieu de le présenter comme courant", () => {
    const releve = signauxSysteme(ETAT, { ...RELEVE, perime: true, age_secondes: 3 * 3600 }, FILE)[2];
    expect(releve.etat).toBe("périmé");
    expect(releve.detail).toContain("il y a 3 h");
  });
});

describe("verdict d'une semaine", () => {
  it("annonce une concordance complète en ton calme, avec ce qui a été vérifié", () => {
    const v = verdictSemaine(comparaison([ligne("identique"), ligne("identique"), ligne("hors_celcat")]));
    expect(v.ton).toBe("ok");
    expect(v.titre).toBe("Tout concorde avec Celcat");
    expect(v.detail).toContain("2 séances identiques");
    expect(v.corrigeable).toBe(false);
  });

  it("compte les écarts par nature, sans y mêler les séances hors Celcat", () => {
    const v = verdictSemaine(
      comparaison([ligne("ecart"), ligne("ecart"), ligne("absente_celcat"), ligne("en_trop_celcat"), ligne("hors_celcat")]),
    );
    expect(v.titre).toBe("4 écarts avec Celcat");
    expect(v.detail).toContain("2 à modifier · 1 à créer · 1 en trop");
    expect(v.horsCelcat).toBe(1);
    expect(v.corrigeable).toBe(true);
  });

  it("refuse de conclure sans relevé", () => {
    const v = verdictSemaine(comparaison([ligne("ecart")], { releve_le: null }));
    expect(v.titre).toMatch(/pas encore de relevé/i);
    expect(v.corrigeable).toBe(false);
  });

  it("refuse de conclure sur un relevé périmé", () => {
    // Corriger d'après une photo de trois heures pousserait des modifications
    // contre un Celcat qui a changé.
    const v = verdictSemaine(comparaison([ligne("ecart")], { perime: true, age_secondes: 3 * 3600 }));
    expect(v.titre).toMatch(/trop ancien/);
    expect(v.corrigeable).toBe(false);
  });
});

describe("formats lisibles", () => {
  it("rend une date ISO lisible, et la garde telle quelle si elle est illisible", () => {
    expect(dateLisible("2026-09-16T08:42:00")).toBe("16/09 à 08:42");
    expect(dateLisible("pas une date")).toBe("pas une date");
    expect(dateLisible(null)).toBe("");
  });

  it("dit l'âge en clair", () => {
    expect(ageLisible(20)).toBe("il y a moins d’une minute");
    expect(ageLisible(47 * 60)).toBe("il y a 47 min");
    expect(ageLisible(125 * 60)).toBe("il y a 2 h 5 min");
    expect(ageLisible(null)).toBe("");
  });

  it("donne le jour ET sa date", () => {
    expect(jourDate(1, "2026-09-14")).toBe("mardi 15/09");
    expect(jourDate(null, "2026-09-14")).toBe("—");
  });
});
