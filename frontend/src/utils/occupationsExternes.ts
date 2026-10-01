/**
 * Occupations HORS MMI relevées dans Celcat (01/10/2026, demande de Kyllian
 * Bresson : « Lecture de Celcat pour vérifier les disponibilités des salles
 * et des enseignants »).
 *
 * Le serveur a déjà fait la conversion vers NOS créneaux
 * (`api/occupations_externes.py::pour_payload`) : une occupation de 10h00 à
 * 12h30 arrive avec `s: [1, 2]` (9h30-11h et 11h-12h30). Ici, uniquement de
 * l'affichage : blocs « Occupé ailleurs (TC) » / « Réservé dans Celcat », et
 * fraîcheur du relevé. Les conflits, eux, sont jugés par le serveur.
 */

import type { AppPayload, OccupationExterne } from "../types/app";

/** « Occupé ailleurs (TC) », « Réservé dans Celcat (administration) ». */
export function libelleOccupation(o: OccupationExterne): string {
  if (o.t === "enseignant") return `Occupé ailleurs (${o.dep || "Celcat"})`;
  return `Réservé dans Celcat (${o.dep ? o.dep : "administration"})`;
}

/** Détail lisible : « 10h00–12h30 · TC · [CM] Marketing ». */
export function detailOccupation(o: OccupationExterne): string {
  const h = (x: string) => (x || "").replace(":", "h");
  const quoi = [o.cat, o.lib].filter(Boolean).join(" ");
  return [`${h(o.debut)}–${h(o.fin)}`, o.dep || (o.t === "salle" ? "administration" : ""), quoi]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Les occupations d'UNE ressource sur UNE semaine solveur, par case
 * « jour-créneau ». Pour une salle, celles des salles liées (H.007-008 ↔
 * H.007/H.008) comptent aussi — même règle que le serveur au placement.
 */
export function occupationsParCase(
  payload: Pick<AppPayload, "occupationsExternes" | "rooms">,
  type: "enseignant" | "salle",
  code: string,
  week: number | null,
): Map<string, OccupationExterne[]> {
  const parCase = new Map<string, OccupationExterne[]>();
  const occupations = payload.occupationsExternes?.occupations ?? [];
  if (week === null || occupations.length === 0 || !code) return parCase;
  const codes = new Set<string>([type === "salle" ? code.toLowerCase() : code.toUpperCase()]);
  if (type === "salle") {
    const room = payload.rooms.find((r) => r.id === code);
    for (const partie of room?.combines ?? []) codes.add(partie);
    for (const r of payload.rooms) if (r.combines.includes(code)) codes.add(r.id);
  }
  for (const o of occupations) {
    if (o.t !== type || o.w !== week || !codes.has(o.code)) continue;
    for (const s of o.s) {
      const cle = `${o.d}-${s}`;
      const liste = parCase.get(cle) ?? [];
      if (!liste.some((x) => x.date === o.date && x.debut === o.debut && x.lib === o.lib)) liste.push(o);
      parCase.set(cle, liste);
    }
  }
  return parCase;
}

/** Libellés par case, prêts pour la grille (`SessionGrid.externes`). */
export function libellesParCase(parCase: Map<string, OccupationExterne[]>): Map<string, string[]> {
  const sortie = new Map<string, string[]>();
  for (const [cle, liste] of parCase) {
    sortie.set(cle, [...new Set(liste.map(libelleOccupation))]);
  }
  return sortie;
}

/**
 * Bandeau de fraîcheur : `null` si tout va bien (ou rien n'a jamais été
 * relevé — l'écran Celcat le dit, pas chaque vue), sinon « Occupations
 * Celcat relevées il y a 9 h ». L'âge se calcule ICI, à partir de
 * l'horodatage : le payload est mis en cache par révision, son
 * `ageSecondes` vieillit avec lui.
 */
export function bandeauFraicheur(
  payload: Pick<AppPayload, "occupationsExternes">,
  maintenant: Date = new Date(),
): string | null {
  const oe = payload.occupationsExternes;
  if (!oe || !oe.releveLe) return null;
  const releve = new Date(oe.releveLe).getTime();
  if (Number.isNaN(releve)) return null;
  const heures = (maintenant.getTime() - releve) / 3_600_000;
  if (heures <= (oe.fraicheurHeures || 6)) return null;
  const texte = heures >= 48 ? `il y a ${Math.floor(heures / 24)} jours` : `il y a ${Math.floor(heures)} h`;
  return `Occupations Celcat relevées ${texte} — les blocs « Occupé ailleurs » et « Réservé dans Celcat » peuvent ne plus être à jour.`;
}
