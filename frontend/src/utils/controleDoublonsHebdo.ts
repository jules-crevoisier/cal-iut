/**
 * Aides pures pour la section « Contrôle hebdomadaire » de l'écran « À
 * traiter » (Jules Crevoisier, 25/09/2026, dicté : « on veut faire quelque
 * chose qui vérifie chaque semaine [...] »). Le filet lui-même tourne côté
 * serveur, sans écran (`api/controle_doublons_hebdo.py`) ; ce module ne fait
 * que présenter son DERNIER résultat, déjà transmis par `GET /controles/
 * doublons/hebdo` (cf. `api/client.ts::DoublonHebdoRun`).
 */

import type { Doublon, DoublonHebdoRun } from "../api/client";

/** « 2026-09-25 » -> « 25/09/2026 » — même format court que le reste de
 * l'écran de comptes admin, jamais une locale `Intl` ici : une date
 * AAAA-MM-JJ pure, pas un horodatage à convertir de fuseau. */
function formatDateFr(iso: string): string {
  const [annee, mois, jour] = iso.split("-");
  return `${jour}/${mois}/${annee}`;
}

/**
 * « Contrôle du 25/09/2026 : 111 doublons — 4 nouveaux depuis le contrôle
 * précédent ». La clause « depuis le contrôle précédent » disparaît au tout
 * premier contrôle (`premier_controle`, rien à comparer) et quand rien n'a
 * changé depuis le run d'avant (0 nouveau) — pas la peine d'annoncer « 0
 * nouveau » à chaque fois, un vrai changement ne se remarquerait plus.
 */
export function libelleControleHebdo(run: DoublonHebdoRun): string {
  const date = formatDateFr(run.date);
  const compte = run.total === 0 ? "aucun doublon" : `${run.total} doublon${run.total > 1 ? "s" : ""}`;
  const base = `Contrôle du ${date} : ${compte}`;
  if (run.premier_controle || run.nouveaux.length === 0) return base;
  const n = run.nouveaux.length;
  return `${base} — ${n} nouveau${n > 1 ? "x" : ""} depuis le contrôle précédent`;
}

/** Clé stable (semaine, jour, créneau, type, ressource) — même appariement
 * que côté serveur (`api/controle_doublons_hebdo.py::_cle_doublon`). */
function cleDoublon(d: Pick<Doublon, "semaine" | "jour" | "creneau" | "type" | "ressource">): string {
  return `${d.semaine}|${d.jour}|${d.creneau}|${d.type}|${d.ressource}`;
}

/** `true` si `d` fait partie des « nouveaux » du dernier contrôle — pour
 * marquer une ligne de la liste existante (`grouperDoublonsParSemaine`)
 * sans dupliquer la liste ni la recalculer. `run` à `null` (jamais exécuté,
 * ou pas encore chargé) : jamais rien de marqué. */
export function estNouveau(run: DoublonHebdoRun | null, d: Doublon): boolean {
  if (!run) return false;
  const cible = cleDoublon(d);
  return run.nouveaux.some((n) => cleDoublon(n) === cible);
}
