/**
 * Découpe le compte rendu du worker en lignes lisibles.
 *
 * Retour utilisateur 08/09/2026, capture d'écran à l'appui : « fix moi cette
 * interface, on ne comprend rien du tout là ». L'écran affichait le résumé
 * brut, c'est-à-dire un paragraphe de vingt lignes sans ponctuation utile :
 *
 *   « 396 correction(s) en attente (392 create, 4 update). Dernier passage du
 *     worker il y a 3 min : 414 job(s) — 18 réussi(s) — 7 en échec — 1× TD
 *     exige event_cat_id pour [TD] — reçu vide (risque historique : CM saisi
 *     comme [TP]) [ids irrésolus : RessourceIntrouvable : matière TSBZC05M]
 *     (ex. WRA305M-S3-TD-1-but2-creacom-fc-td-gh) | 1× TD exige … »
 *
 * Les chiffres qui décident (combien attendent, combien ont réussi, quand)
 * y étaient noyés au milieu des motifs d'échec.
 *
 * Le résumé est ASSEMBLÉ par `nuit.py::BilanDrainage.resume()` : les parties
 * sont jointes par « — » et les motifs entre eux par « | ». On le redécoupe
 * donc sur ces deux séparateurs — ce qui suppose que le format ne change pas
 * sans qu'on le sache, d'où les tests. Un découpage raté ne perd rien : la
 * ligne reste affichée entière, simplement moins bien rangée.
 */

/** Les motifs du compte rendu, un par ligne, sans les compteurs déjà affichés. */
export function segmentsResume(resume: string): string[] {
  const texte = String(resume || "").trim();
  if (!texte) return [];
  return texte
    .split(/\s+\|\s+|\s+—\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
    // Les compteurs bruts sont déjà rendus en haut, en clair : « 414 job(s) »
    // ou « 18 réussi(s) » répétés ici n'apprendraient rien et rallongeraient
    // la liste qu'on cherche justement à raccourcir.
    .filter((s) => !/^\d+\s+(job\(s\)|réussi\(s\))$/i.test(s));
}

/** « il y a 3 min », à partir d'un âge en secondes. */
export function ageLisible(secondes: number | null): string {
  if (secondes === null) return "";
  if (secondes < 60) return `il y a ${Math.max(1, Math.round(secondes))} s`;
  const minutes = Math.floor(secondes / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const heures = Math.floor(minutes / 60);
  return heures < 24 ? `il y a ${heures} h` : `il y a ${Math.floor(heures / 24)} j`;
}
