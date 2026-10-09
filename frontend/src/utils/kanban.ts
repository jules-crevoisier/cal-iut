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

const LIBELLE_COLONNE: Record<string, string> = {
  a_faire: "À faire",
  en_cours: "En cours",
  fait: "Fait",
};

const LIBELLE_CATEGORIE: Record<string, string> = {
  edt: "Emploi du temps",
  plateforme: "Plateforme",
};

/**
 * Toute une tâche en texte brut, prête à coller dans un mail ou un message.
 *
 * Demande de Jules, 28/09/2026 : « dans les tâches, je voudrais bien un
 * petit bouton copier qui copie toutes les infos d'une tâche ». Donc TOUT
 * ce que la carte porte — y compris les séances concernées, qui sont la
 * raison d'être de la carte quand un enseignant s'absente —, jamais un
 * simple copier du titre.
 *
 * Les libellés sont ceux de l'écran (« À faire », « Emploi du temps ») et
 * non les valeurs stockées : le texte part vers un humain, pas vers l'API.
 */
export function texteTache(
  tache: {
    titre: string;
    description?: string | null;
    colonne: string;
    categorie?: string | null;
    priorite?: string | null;
    concerne?: string | null;
    enseignant_code?: string | null;
    date_debut?: string | null;
    date_fin?: string | null;
    cree_par?: string;
  },
  options: { nomEnseignant?: string | null; seances?: SeanceConcernee[]; libelleSeance?: (s: SeanceConcernee) => string } = {},
): string {
  const lignes: string[] = [];
  const urgent = tache.priorite === "urgente" ? "[Urgent] " : "";
  lignes.push(`${urgent}${tache.titre}`);

  const situation = [
    LIBELLE_CATEGORIE[tache.categorie ?? "edt"] ?? tache.categorie,
    LIBELLE_COLONNE[tache.colonne] ?? tache.colonne,
    tache.concerne ? `pour ${tache.concerne}` : null,
  ].filter(Boolean);
  lignes.push(situation.join(" · "));

  const nomProf = options.nomEnseignant ?? tache.enseignant_code;
  if (nomProf) lignes.push(`Enseignant : ${nomProf}`);
  const dates = libelleDatesTache(tache.date_debut ?? null, tache.date_fin ?? null);
  if (dates) lignes.push(`Dates : ${dates}`);

  const seances = options.seances ?? [];
  if (seances.length > 0) {
    lignes.push(`Séances concernées (${seances.length}) :`);
    for (const s of seances) {
      lignes.push(`  - ${options.libelleSeance ? options.libelleSeance(s) : `${s.dateIso} ${s.row.c}`}`);
    }
  }

  if (tache.description?.trim()) {
    lignes.push("");
    lignes.push(tache.description.trim());
  }
  if (tache.cree_par) {
    lignes.push("");
    lignes.push(`Créée par ${tache.cree_par}`);
  }
  return lignes.join("\n");
}


const FMT_HORODATAGE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeStyle: "short" });

/**
 * Toute la page des tâches en Markdown, à coller tel quel à Claude comme
 * rapport (Jules, 09/10/2026 : « copier toute la page d'un coup [...] te
 * coller le rapport [...] que toi tu regardes »). Les tâches reçues sont
 * celles de l'écran (onglet et filtres appliqués), regroupées par colonne
 * dans l'ordre affiché — y compris la colonne « Fait » repliée à l'écran.
 *
 * Markdown plutôt que texte brut : titres et listes se relisent aussi bien
 * par un humain que par un assistant, et la description reste un bloc à
 * part entière (citée, pour ne pas casser la structure si elle contient
 * elle-même des titres).
 */
export function rapportTaches<
  T extends {
    id: number;
    titre: string;
    description?: string | null;
    colonne: string;
    categorie?: string | null;
    priorite?: string | null;
    concerne?: string | null;
    enseignant_code?: string | null;
    date_debut?: string | null;
    date_fin?: string | null;
    cree_par?: string;
    cree_le?: string;
    maj_le?: string;
    fait_le?: string | null;
    images?: { nom: string }[];
  },
>(
  colonnes: { id: string; label: string; taches: T[] }[],
  options: {
    categorie?: string | null;
    filtres?: string[];
    maintenant?: Date;
    nomEnseignant?: (t: T) => string | null;
    seances?: (t: T) => string[];
  } = {},
): string {
  const horodatage = (iso: string | null | undefined): string | null => {
    if (!iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : FMT_HORODATAGE.format(d);
  };

  const lignes: string[] = [];
  const categorie = options.categorie ? LIBELLE_CATEGORIE[options.categorie] ?? options.categorie : null;
  lignes.push(`# Rapport des tâches${categorie ? ` — ${categorie}` : ""}`);
  lignes.push("");
  lignes.push(`Copié le ${FMT_HORODATAGE.format(options.maintenant ?? new Date())}.`);
  const total = colonnes.reduce((n, c) => n + c.taches.length, 0);
  lignes.push(
    `${total} tâche${total > 1 ? "s" : ""} : ${colonnes.map((c) => `${c.label} ${c.taches.length}`).join(", ")}.`,
  );
  if (options.filtres?.length) lignes.push(`Filtres actifs : ${options.filtres.join(", ")}.`);

  for (const colonne of colonnes) {
    lignes.push("");
    lignes.push(`## ${colonne.label} (${colonne.taches.length})`);
    if (colonne.taches.length === 0) {
      lignes.push("");
      lignes.push("Aucune tâche.");
      continue;
    }
    for (const t of colonne.taches) {
      lignes.push("");
      lignes.push(`### ${t.priorite === "urgente" ? "[Urgent] " : ""}${t.titre} (#${t.id})`);
      lignes.push("");
      const details: string[] = [];
      details.push(`Statut : ${LIBELLE_COLONNE[t.colonne] ?? t.colonne}`);
      details.push(`Priorité : ${t.priorite === "urgente" ? "urgente" : "normale"}`);
      details.push(`Pour : ${t.concerne || "non attribuée"}`);
      const nomProf = options.nomEnseignant?.(t) ?? t.enseignant_code;
      if (nomProf) details.push(`Enseignant : ${nomProf}`);
      const dates = libelleDatesTache(t.date_debut ?? null, t.date_fin ?? null);
      if (dates) details.push(`Dates : ${dates}`);
      const creee = [t.cree_par ? `par ${t.cree_par}` : null, horodatage(t.cree_le) ? `le ${horodatage(t.cree_le)}` : null]
        .filter(Boolean)
        .join(" ");
      if (creee) details.push(`Créée ${creee}`);
      const maj = horodatage(t.maj_le);
      if (maj && maj !== horodatage(t.cree_le)) details.push(`Modifiée le ${maj}`);
      const faite = horodatage(t.fait_le);
      if (faite) details.push(`Faite le ${faite}`);
      const images = t.images ?? [];
      if (images.length) details.push(`Images jointes (${images.length}) : ${images.map((i) => i.nom).join(", ")}`);
      for (const d of details) lignes.push(`- ${d}`);
      const seances = options.seances?.(t) ?? [];
      if (seances.length) {
        lignes.push(`- Séances concernées (${seances.length}) :`);
        for (const s of seances) lignes.push(`  - ${s}`);
      }
      if (t.description?.trim()) {
        lignes.push("");
        for (const l of t.description.trim().split(/\r?\n/)) lignes.push(l.trim() ? `> ${l}` : ">");
      }
    }
  }
  return `${lignes.join("\n")}\n`;
}
