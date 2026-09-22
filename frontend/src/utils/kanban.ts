/**
 * Aide pure pour le kanban « Tâches » (22/09/2026, retour utilisateur
 * Jules) — le point du kanban n'est pas seulement de lister des mémos, mais
 * de les relier au planning réel : « ce prof a dit qu'il ne serait pas
 * présent ce jour, déplacer » suppose de pouvoir MONTRER les séances de ce
 * prof concernées par la période déclarée, pas de le faire chercher à la
 * main dans les autres vues.
 *
 * Fonctions pures, testées indépendamment de `KanbanView` (pas d'accès
 * réseau ni de DOM ici).
 */

import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, AppRow } from "../types/app";

function toIsoDate(d: Date): string {
  // Construit la chaîne depuis les composants LOCAUX (jamais
  // `toISOString()`, qui repasse par UTC et peut décaler la date d'un jour
  // selon le fuseau du navigateur) — même précaution que `utils/slots.ts`,
  // qui manipule ces dates uniquement en heure locale.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Date réelle (ISO "AAAA-MM-JJ") d'une séance — lundi de sa semaine
 * (`weekRows[].monday`, indexé par semaine SOLVEUR comme `row.w`, cf.
 * `AppRow.w`) plus son jour (`row.d`, 0 = lundi). `null` si la semaine n'a
 * pas de lundi connu (hors horizon calculé) — ne devrait pas arriver pour
 * une séance réellement placée, mais ne doit pas planter le cas échéant.
 */
export function dateReelleRow(payload: AppPayload, row: AppRow): string | null {
  const semaine = payload.weekRows.find((w) => w.weekIndex === row.w);
  if (!semaine?.monday) return null;
  const d = new Date(`${semaine.monday}T00:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  d.setDate(d.getDate() + row.d);
  return toIsoDate(d);
}

function dateDansPlage(dateIso: string, debut: string, fin: string): boolean {
  // Comparaison lexicographique valide pour deux dates ISO "AAAA-MM-JJ" —
  // même ordre que la comparaison numérique, pas besoin de reparser en Date.
  return dateIso >= debut && dateIso <= fin;
}

export interface SeanceConcernee {
  row: AppRow;
  dateIso: string;
}

/**
 * Séances du planning concernées par une tâche : celles de l'enseignant
 * déclaré, dont la date réelle tombe dans [date_debut, date_fin]. Vide sans
 * enseignant OU sans date de début — une tâche sans les deux ne désigne
 * rien de vérifiable dans le planning. `date_fin` absente = tâche sur un
 * seul jour (`date_debut` compte pour les deux bornes).
 */
export function seancesConcernees(
  payload: AppPayload,
  tache: { enseignant_code: string | null; date_debut: string | null; date_fin: string | null },
): SeanceConcernee[] {
  if (!tache.enseignant_code || !tache.date_debut) return [];
  const fin = tache.date_fin ?? tache.date_debut;
  const resultats: SeanceConcernee[] = [];
  for (const row of payload.rows) {
    if (!row.te.includes(tache.enseignant_code)) continue;
    const dateIso = dateReelleRow(payload, row);
    if (!dateIso) continue;
    if (!dateDansPlage(dateIso, tache.date_debut, fin)) continue;
    resultats.push({ row, dateIso });
  }
  return resultats.sort((a, b) => a.dateIso.localeCompare(b.dateIso) || a.row.s - b.row.s);
}

/**
 * Lien Vue Promo pour une séance concernée — `sem` porte l'indice SOLVEUR
 * (`row.w`), JAMAIS l'indice d'affichage : c'est ce que fait déjà
 * `utils/todo.ts` (« À traiter »), et c'est la vue cible (`PromoView`) qui
 * convertit à la lecture via `weekDisplay.ts::displayIndexForSolverWeek`.
 * Cf. mémoire projet « Trois numérotations de semaines » : toujours ENVOYER
 * l'indice solveur, n'afficher le libellé daté qu'à l'écran.
 */
export function routeVersSeance(row: AppRow): Partial<Route> {
  return { vue: "promo", sem: row.w, jour: row.d };
}

const FMT_JOUR = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const FMT_JOUR_ANNEE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });

/**
 * Libellé français d'une date ou plage de dates de tâche — un seul jour
 * ("25 sept. 2026") ou une plage ("25 sept. – 2 oct. 2026"). `null` sans
 * date de début (tâche sans échéance déclarée).
 */
export function libelleDatesTache(dateDebut: string | null, dateFin: string | null): string | null {
  if (!dateDebut) return null;
  const debut = new Date(`${dateDebut}T00:00:00`);
  if (Number.isNaN(debut.getTime())) return null;
  if (!dateFin || dateFin === dateDebut) return FMT_JOUR_ANNEE.format(debut);
  const fin = new Date(`${dateFin}T00:00:00`);
  if (Number.isNaN(fin.getTime())) return FMT_JOUR_ANNEE.format(debut);
  return `${FMT_JOUR.format(debut)} – ${FMT_JOUR_ANNEE.format(fin)}`;
}
