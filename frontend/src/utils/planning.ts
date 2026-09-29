/**
 * Calculs communs aux écrans de consultation (Vue Enseignant, Vue TD/TP,
 * Vue Cours, Vue Salle et leurs liens publics) : heures, horaires réels,
 * prochaine séance, repérage d'aujourd'hui.
 *
 * Fonctions pures, `maintenant` toujours passé en paramètre : c'est ce qui
 * les rend testables sans truquer l'horloge.
 */

import type { AppPayload, AppRow, InstitutionalEvent, WeekRow } from "../types/app";
import type { IcsSession } from "./ics";
import { SLOT_TIMES } from "./slots";

/** Un créneau dure 1 h 30 : c'est la convention de tout l'outil (histogramme
 *  de la barre des semaines, mail à l'enseignant, agenda du semestre). */
export const HEURES_PAR_CRENEAU = 1.5;

export function heuresDe(rows: Pick<AppRow, "dur">[]): number {
  return rows.reduce((n, r) => n + Math.max(1, r.dur || 1) * HEURES_PAR_CRENEAU, 0);
}

/** « 12 h », « 247,5 h » — virgule décimale française. */
export function formatHeures(h: number): string {
  return `${h.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} h`;
}

export function pluriel(n: number, singulier: string, plurielForme = `${singulier}s`): string {
  return `${n.toLocaleString("fr-FR")} ${n > 1 ? plurielForme : singulier}`;
}

/** « 8h », « 9h30 » depuis « 08:00:00 ». */
function heureCourte(hms: string): string {
  const [h, m] = hms.split(":");
  return `${Number(h)}h${m === "00" ? "" : m}`;
}

const HOR_RE = /^(\d{1,2})h(\d{2})?\s*[–-]\s*(\d{1,2})h(\d{2})?$/;

/** Horaire réel d'une séance : l'horaire libre (`hor`, ex. « 13h15–14h »)
 *  quand il existe, sinon du début de son créneau à la fin du dernier
 *  créneau qu'elle occupe (une séance de 3 h court sur deux créneaux). */
export function horaireSeance(row: Pick<AppRow, "s" | "dur" | "hor">): { debut: string; fin: string; libelle: string } {
  if (row.hor) {
    const m = HOR_RE.exec(row.hor.trim());
    if (m) {
      const debut = `${Number(m[1])}h${m[2] ?? ""}`;
      const fin = `${Number(m[3])}h${m[4] ?? ""}`;
      return { debut, fin, libelle: `${debut}–${fin}` };
    }
    return { debut: row.hor, fin: "", libelle: row.hor };
  }
  const premier = SLOT_TIMES[row.s] ?? SLOT_TIMES[0];
  const dernier = SLOT_TIMES[Math.min(SLOT_TIMES.length - 1, row.s + Math.max(1, row.dur || 1) - 1)];
  const debut = heureCourte(premier.start);
  const fin = heureCourte(dernier.end);
  return { debut, fin, libelle: `${debut}–${fin}` };
}

function aHeure(date: Date, libelle: string): Date | null {
  const m = /^(\d{1,2})h(\d{2})?$/.exec(libelle);
  if (!m) return null;
  const d = new Date(date);
  d.setHours(Number(m[1]), Number(m[2] ?? 0), 0, 0);
  return d;
}

/** Début et fin datés d'une séance (null si sa semaine n'a pas de date). */
export function bornesSeance(item: IcsSession): { debut: Date; fin: Date } | null {
  if (!item.date) return null;
  const h = horaireSeance(item);
  const debut = aHeure(item.date, h.debut);
  const fin = aHeure(item.date, h.fin) ?? (debut ? new Date(debut.getTime() + 90 * 60000) : null);
  return debut && fin ? { debut, fin } : null;
}

export interface ProchaineSeance {
  item: IcsSession;
  debut: Date;
  fin: Date;
  /** Vrai quand la séance a déjà commencé : on la dit « en cours ». */
  enCours: boolean;
}

/** La séance en cours, sinon la prochaine à venir. */
export function prochaineSeance(items: IcsSession[], maintenant: Date): ProchaineSeance | null {
  let meilleure: ProchaineSeance | null = null;
  for (const item of items) {
    const b = bornesSeance(item);
    if (!b || b.fin <= maintenant) continue;
    if (!meilleure || b.debut < meilleure.debut) {
      meilleure = { item, debut: b.debut, fin: b.fin, enCours: b.debut <= maintenant };
    }
  }
  return meilleure;
}

export function memeJour(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

const JOUR_COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });

/** « aujourd'hui », « demain », sinon « mar. 13 oct. ». */
export function jourRelatif(date: Date, maintenant: Date): string {
  if (memeJour(date, maintenant)) return "aujourd'hui";
  const demain = new Date(maintenant);
  demain.setDate(demain.getDate() + 1);
  if (memeJour(date, demain)) return "demain";
  return JOUR_COURT.format(date);
}

export function jourCourt(date: Date): string {
  return JOUR_COURT.format(date);
}

/** Jour (0 = lundi) de `maintenant` dans la semaine solveur `week`, ou null
 *  si aujourd'hui n'est pas dans cette semaine (ou tombe un week-end). */
export function jourAujourdhuiDansSemaine(
  payload: Pick<AppPayload, "weekDates">,
  week: number | null,
  maintenant: Date,
): number | null {
  if (week === null) return null;
  const iso = payload.weekDates[week];
  if (!iso) return null;
  const lundi = new Date(`${iso}T00:00:00`);
  for (let d = 0; d < 5; d += 1) {
    const jour = new Date(lundi);
    jour.setDate(lundi.getDate() + d);
    if (memeJour(jour, maintenant)) return d;
  }
  return null;
}

/** « Semaine 6 (28 sept.–2 oct. 2026) » → titre « Semaine 6 » et dates
 *  « 28 sept.–2 oct. 2026 ». Un libellé sans parenthèses reste entier. */
export function decouperLibelleSemaine(label: string): { titre: string; dates: string } {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(label);
  return m ? { titre: m[1], dates: m[2] } : { titre: label, dates: "" };
}

/** Période du calendrier institutionnel (vacances, fermeture) qui couvre le
 *  lundi d'une semaine bloquée — pour dire POURQUOI il n'y a pas cours. */
export function periodeBloquee(
  semaine: WeekRow | undefined,
  calendrier: InstitutionalEvent[],
): InstitutionalEvent | null {
  if (!semaine) return null;
  const lundi = semaine.monday;
  const v = new Date(`${lundi}T00:00:00`);
  v.setDate(v.getDate() + 4);
  const p = (n: number) => String(n).padStart(2, "0");
  const vendredi = `${v.getFullYear()}-${p(v.getMonth() + 1)}-${p(v.getDate())}`;
  // Chevauchement de la période avec lundi–vendredi (dates ISO comparables
  // telles quelles). Les vacances d'abord : un férié isolé n'explique pas
  // une semaine entière bloquée.
  const chevauche = calendrier.filter((e) => e.start <= vendredi && e.end >= lundi);
  return chevauche.find((e) => e.kind === "vacances") ?? chevauche[0] ?? null;
}

/** Première semaine NON bloquée après `index` (reprise des cours). */
export function semaineDeReprise(semaines: WeekRow[], index: number): number | null {
  for (let i = index + 1; i < semaines.length; i += 1) {
    if (!semaines[i].blocked && semaines[i].weekIndex !== null) return i;
  }
  return null;
}
