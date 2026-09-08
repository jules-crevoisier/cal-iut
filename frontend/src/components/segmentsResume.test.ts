/**
 * Le compte rendu du worker, découpé en lignes lisibles.
 *
 * Retour utilisateur 08/09/2026, capture à l'appui : « fix moi cette
 * interface, on ne comprend rien du tout là ». L'écran affichait le résumé
 * brut — un paragraphe de vingt lignes où les trois chiffres qui décident
 * étaient noyés au milieu des motifs d'échec.
 *
 * Le format vient de `nuit.py::BilanDrainage.resume()` : parties jointes par
 * « — », motifs entre eux par « | ». Ces tests figent ce contrat côté
 * interface, sans quoi un changement du côté Python casserait l'affichage
 * sans que rien ne le dise.
 */
import { describe, expect, it } from "vitest";

import { ageLisible, segmentsResume } from "./segmentsResume";

// Le résumé RÉEL vu en production le 08/09/2026, tronqué à trois motifs.
const REEL =
  "414 job(s) — 18 réussi(s) — 7 en échec — 1× TD exige event_cat_id pour [TD] — reçu vide " +
  "(risque historique : CM saisi comme [TP]) [ids irrésolus : RessourceIntrouvable : matière " +
  "TSBZC05M] (ex. WRA305M-S3-TD-1-but2-creacom-fc-td-gh) | 1× TD exige event_cat_id pour [TD] " +
  "— reçu vide [ids irrésolus : matière TSBZC12M] (ex. WRA312M-S3-TP-2-but2-creacom-fc-tp-g) " +
  "— 57 en attente d'une semaine posée — 9× semaine 8 pas encore posée dans Celcat " +
  "(12 cours sur 234 prévus) — en attente (ex. WRA502D-S5-TD-1-but3-dev-fc-td-ef)";

describe("segmentsResume", () => {
  it("découpe le compte rendu réel en lignes distinctes", () => {
    const lignes = segmentsResume(REEL);

    expect(lignes.length).toBeGreaterThan(3);
    expect(lignes.some((l) => l.includes("TSBZC05M"))).toBe(true);
    expect(lignes.some((l) => l.includes("semaine 8 pas encore posée"))).toBe(true);
  });

  it("retire les compteurs déjà affichés en clair au-dessus", () => {
    // « 414 job(s) » et « 18 réussi(s) » sont rendus séparément : les répéter
    // rallongerait la liste qu'on cherche justement à raccourcir.
    const lignes = segmentsResume(REEL);

    expect(lignes).not.toContain("414 job(s)");
    expect(lignes).not.toContain("18 réussi(s)");
  });

  it("garde les motifs entiers plutôt que de les tronquer", () => {
    // Un motif coupé en deux ne permet plus d'aller voir dans Celcat : c'est
    // l'exemple de séance qui rend la ligne actionnable.
    const lignes = segmentsResume(REEL);
    const premier = lignes.find((l) => l.includes("TSBZC05M")) ?? "";

    expect(premier).toContain("WRA305M-S3-TD-1-but2-creacom-fc-td-gh");
  });

  it("rend une liste vide sur un résumé absent", () => {
    expect(segmentsResume("")).toEqual([]);
    expect(segmentsResume(undefined as unknown as string)).toEqual([]);
  });

  it("laisse passer un résumé d'un seul tenant sans le perdre", () => {
    // Un découpage qui ne trouve pas ses séparateurs ne doit rien jeter.
    expect(segmentsResume("file d’attente vide")).toEqual(["file d’attente vide"]);
  });
});

describe("ageLisible", () => {
  it("dit les secondes, minutes, heures et jours", () => {
    expect(ageLisible(30)).toBe("il y a 30 s");
    expect(ageLisible(180)).toBe("il y a 3 min");
    expect(ageLisible(7200)).toBe("il y a 2 h");
    expect(ageLisible(86400 * 3)).toBe("il y a 3 j");
  });

  it("ne dit jamais « il y a 0 s »", () => {
    // Un âge qui s'affiche zéro se lit « à l'instant » et fait douter de
    // l'horodatage plutôt que de rassurer.
    expect(ageLisible(0.2)).toBe("il y a 1 s");
  });

  it("ne dit rien quand l'âge est inconnu", () => {
    expect(ageLisible(null)).toBe("");
  });
});
