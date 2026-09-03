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
 * IDs visibles pour un filtre groupe : cohort du groupe + tout groupe du
 * parcours dont la cohort contient ce groupe (ex. TP sous un TD choisi).
 */
export function idsVisiblesPourFiltre(
  payload: AppPayload,
  parcours: string,
  filtre: FiltreGroupeId,
): Set<string> | null {
  if (filtre === "Tout") return null;
  const visibles = new Set<string>(payload.groupCohort[filtre] ?? [filtre]);
  for (const [gid, members] of Object.entries(payload.groupCohort)) {
    if (payload.groupParcours[gid] !== parcours) continue;
    if (!members.includes(filtre)) continue;
    visibles.add(gid);
    for (const m of members) visibles.add(m);
  }
  return visibles;
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
