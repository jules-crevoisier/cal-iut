/**
 * Identité d'un enseignant côté écran (01/10/2026) : la règle prénom / nom
 * est celle du serveur (`ingestion/identite_enseignants.py::separer_nom`),
 * le téléphone suit les mêmes formats (`normaliser_telephone`).
 */
import { describe, expect, it } from "vitest";

import { emptyPayload } from "../test/payloadFixture";
import { formaterTelephone, identiteDe, libelleType, normaliserTelephone, validerTelephone } from "./identiteEnseignant";
import { separerNom } from "./nomEnseignant";

describe("separerNom — mêmes cas que le serveur", () => {
  it.each([
    ["Thomas CASTELLENGO", "Thomas", "CASTELLENGO"],
    ["KYLLIAN BRESSON", "Kyllian", "BRESSON"],
    ["Anne-Laure  Perrone", "Anne-Laure", "PERRONE"],
    ["ANNE-LAURE PERRONE", "Anne-Laure", "PERRONE"],
    ["Barthélémy TOMASINA", "Barthélémy", "TOMASINA"],
    ["Alexia Petit-Halajko", "Alexia", "PETIT-HALAJKO"],
    ["Jean-Marc DE LA TOUR", "Jean-Marc", "DE LA TOUR"],
    ["Marie de la Tour", "Marie", "DE LA TOUR"],
    ["ÉLODIE ÉCHARD", "Élodie", "ÉCHARD"],
    ["Nino", "", "NINO"],
    ["", "", ""],
  ])("%s", (complet, prenom, nom) => {
    expect(separerNom(complet)).toEqual({ prenom, nom });
  });

  it("un libellé qui n'est que le code : ni prénom ni nom", () => {
    expect(separerNom("MRI", "MRI")).toEqual({ prenom: "", nom: "" });
  });
});

describe("identiteDe", () => {
  it("lit `teacherIdentites`, sinon déduit du libellé", () => {
    const p = emptyPayload({
      teacherLabels: { KBR: "Kyllian Bresson", TCA: "Thomas CASTELLENGO" },
      teacherIdentites: { KBR: { prenom: "Kyllian", nom: "BRESSON", type: "vacataire" } },
    });
    expect(identiteDe(p, "KBR")).toEqual({ prenom: "Kyllian", nom: "BRESSON", type: "vacataire" });
    expect(identiteDe(p, "TCA")).toEqual({ prenom: "Thomas", nom: "CASTELLENGO", type: null });
    expect(libelleType(null)).toBe("à préciser");
    expect(libelleType("enseignant")).toBe("Enseignant");
  });
});

describe("téléphone", () => {
  it.each([
    ["06 12 34 56 78", "+33612345678"],
    ["06.12.34.56.78", "+33612345678"],
    ["0612345678", "+33612345678"],
    ["+33 6 12 34 56 78", "+33612345678"],
    ["+33 (0)6 12 34 56 78", "+33612345678"],
    ["0033 3 25 42 46 46", "+33325424646"],
    ["+44 20 7946 0958", "+442079460958"],
  ])("%s -> %s", (saisie, e164) => {
    expect(normaliserTelephone(saisie)).toBe(e164);
    expect(validerTelephone(saisie)).toBeNull();
  });

  it.each(["", "06 12 34 56", "6 12 34 56 78", "+33 06 12 34 56 78", "+1 234", "bonjour"])("refuse « %s »", (saisie) => {
    expect(normaliserTelephone(saisie)).toBeNull();
    expect(validerTelephone(saisie)).not.toBeNull();
  });

  it("affiche un numéro français par paires", () => {
    expect(formaterTelephone("+33612345678")).toBe("06 12 34 56 78");
    expect(formaterTelephone("+442079460958")).toBe("+442079460958");
    expect(formaterTelephone(null)).toBe("");
  });
});
