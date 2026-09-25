/**
 * Aides pures pour la section « Doublons salle / enseignant » de l'écran
 * « À traiter » (retour Kyllian Bresson 25/09/2026, cf. `api/doublons.py`
 * côté serveur). Fonctions pures, testées indépendamment de `TodoView`.
 */

import type { Doublon } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { dateForWeekDay } from "./weekDates";
import { SLOT_TIMES } from "./slots";

const FMT_JOUR_LONG = new Intl.DateTimeFormat("fr-FR", { weekday: "long" });
const FMT_MOIS_COURT = new Intl.DateTimeFormat("fr-FR", { month: "short" });

/** « 1er » pour le 1er du mois, le nombre brut sinon — `Intl.DateTimeFormat`
 * ne sait pas produire d'ordinal français, et « 1 oct. » lu à voix haute
 * sonne faux à côté de « 2 oct. », « 3 oct. » (retour attendu : « jeudi 1er
 * oct. »). */
function jourOrdinal(jour: number): string {
  return jour === 1 ? "1er" : String(jour);
}

/**
 * « jeudi 1er oct., 14h–15h30 » — date réelle (résolue depuis
 * `payload.weekDates`, cf. `utils/weekDates.ts::dateForWeekDay`) suivie de
 * l'horaire du créneau. Repli sur le jour de semaine seul si la date est
 * inconnue (semaine hors horizon), jamais une chaîne vide.
 */
export function libelleCreneauDoublon(
  payload: Pick<AppPayload, "weekDates">,
  semaine: number,
  jour: number,
  creneau: number,
): string {
  const d = dateForWeekDay(payload, semaine, jour);
  const datePart = d
    ? `${FMT_JOUR_LONG.format(d)} ${jourOrdinal(d.getDate())} ${FMT_MOIS_COURT.format(d)}`
    : "?";
  return `${datePart}, ${SLOT_TIMES[creneau]?.label ?? "?"}`;
}

/** Lien Vue Promo sur le bon jour — `sem` porte l'indice SOLVEUR (`d.semaine`),
 * jamais l'indice d'affichage : même convention que `utils/todo.ts` et
 * `utils/kanban.ts::routeVersSeance`. */
export function routeVersDoublon(d: Pick<Doublon, "semaine" | "jour">): Partial<Route> {
  return { vue: "promo", sem: d.semaine, jour: d.jour };
}

export interface GroupeDoublonsSemaine {
  semaine: number;
  libelle: string;
  doublons: Doublon[];
}

/**
 * Regroupe par semaine SOLVEUR, dans l'ordre où `api/doublons.py::doublons`
 * les rend déjà (semaine, jour, créneau, type, ressource) — un simple
 * regroupement stable, aucun tri supplémentaire ici.
 */
export function grouperDoublonsParSemaine(
  payload: Pick<AppPayload, "weekLabels">,
  doublons: Doublon[],
): GroupeDoublonsSemaine[] {
  const groupes: GroupeDoublonsSemaine[] = [];
  const parIndex = new Map<number, GroupeDoublonsSemaine>();
  for (const d of doublons) {
    let groupe = parIndex.get(d.semaine);
    if (!groupe) {
      groupe = { semaine: d.semaine, libelle: payload.weekLabels[d.semaine] ?? `Semaine ${d.semaine + 1}`, doublons: [] };
      parIndex.set(d.semaine, groupe);
      groupes.push(groupe);
    }
    groupe.doublons.push(d);
  }
  return groupes;
}

/** Libellé court d'un doublon pour une ligne de liste : « Marine Riguet —
 * WR101 / WR205 » (salle) ou « H.201 / H.203 — WR101 / WR205 » selon le
 * type — les deux matières en conflit, jamais un texte générique qui
 * forcerait à rouvrir la Vue Promo pour savoir de quoi il s'agit. */
export function coursEnConflit(d: Doublon): string {
  return Array.from(new Set(d.seances.map((s) => s.course_code))).join(" / ");
}
