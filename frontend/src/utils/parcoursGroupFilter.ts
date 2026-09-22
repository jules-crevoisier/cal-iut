/**
 * Filtre TP/TD pour la modale semaine par parcours.
 */
import type { AppPayload, AppRow } from "../types/app";
import { lettresGroupe } from "./years";

export type FiltreGroupeId = "Tout" | string;

export interface GroupeParcoursOption {
  id: string;
  label: string;
  kind: string;
}

/**
 * TD puis TP du parcours, hors promo. Ordre : kind, puis lettres (A, B, EF…).
 */
export function listerGroupesParcours(payload: AppPayload, parcours: string): GroupeParcoursOption[] {
  const options: GroupeParcoursOption[] = [];
  for (const [id, label] of Object.entries(payload.groupLabels)) {
    if (payload.groupParcours[id] !== parcours) continue;
    const kind = payload.groupKind[id] ?? "";
    if (kind !== "td" && kind !== "tp") continue;
    options.push({ id, label, kind });
  }
  return options.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "td" ? -1 : 1;
    return lettresGroupe(a.label).localeCompare(lettresGroupe(b.label), "fr");
  });
}

/**
 * IDs visibles pour un filtre groupe : la cohorte du groupe choisi, telle
 * qu'envoyée par le serveur (`payload.groupCohort`, construite par
 * `expand_group_filter` dans `src/cal_iut/models/group_scope.py` — lecture
 * seule ici).
 *
 * Bug corrigé le 22/09/2026 (todo département, retour Kyllian Bresson :
 * « quand je souhaite afficher uniquement le TP A, il m'affiche quand même
 * le TP B »). La boucle qui suivait ajoutait, en plus de la cohorte du
 * groupe choisi, TOUT groupe du parcours dont la cohorte CONTIENT ce
 * groupe. Or côté serveur la cohorte d'un TD liste déjà TOUS ses TP
 * enfants (TD AB -> TD AB + TP A + TP B + promo) : filtrer sur TP A faisait
 * matcher la cohorte du TD AB (qui contient TP A) et réimportait donc TP B
 * en entier. La cohorte du groupe choisi seule suffit dans les deux sens :
 * - TP choisi  -> cohort[TP] = {TP, TD parent, promo} (jamais le TP frère).
 * - TD choisi  -> cohort[TD] = {TD, tous ses TP, promo} (déjà complet).
 */
export function idsVisiblesPourFiltre(
  payload: AppPayload,
  _parcours: string,
  filtre: FiltreGroupeId,
): Set<string> | null {
  if (filtre === "Tout") return null;
  return new Set<string>(payload.groupCohort[filtre] ?? [filtre]);
}

export function filtrerRowsParGroupe(
  rows: AppRow[],
  filtre: FiltreGroupeId,
  payload: AppPayload,
  parcours: string,
  parcoursIds: Set<string>,
): AppRow[] {
  const dansParcours = rows.filter((r) => r.g.some((gid) => parcoursIds.has(gid)));
  const visibles = idsVisiblesPourFiltre(payload, parcours, filtre);
  if (!visibles) return dansParcours;
  return dansParcours.filter((r) => r.g.some((gid) => visibles.has(gid)));
}
