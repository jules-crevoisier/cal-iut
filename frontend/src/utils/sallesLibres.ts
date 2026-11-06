/**
 * Logique pure de la Vue « Salles libres » (todo département 22/09/2026,
 * Kyllian Bresson : « donner accès aux enseignants de consulter le planning
 * d'une ressource en particulier [...] quelles salles sont libres sur ce
 * créneau ? »). Aucun état React ici — juste occupation + filtrage, pour
 * rester testable indépendamment de la vue.
 */

import type { AppPayload, RoomCatalogEntry } from "../types/app";

const SLOT_COUNT = 6;

export interface OccupationEntree {
  code: string;
  type: string;
  groupes: string[];
}

/** `null` = créneau libre, sinon la/les séance(s) qui l'occupent (plus d'une
 *  seule quand deux moitiés d'une salle fusionnée sont réservées séparément
 *  au même créneau — cas rare mais pas invalide). */
export type CelluleOccupation = OccupationEntree[] | null;

/**
 * Tolère le suffixe que `payload.rows[].r` porte parfois (ex. « (Évaluation)
 * » sur les CM d'examen, cf. `PromoView.tsx`) — `RoomCatalogEntry.label` ne
 * l'a jamais. Même règle exacte que `PromoView.tsx` (recherche de la salle
 * du payload), pour ne pas réinventer une variante qui diverge.
 */
export function normaliserLibelleSalle(label: string): string {
  return label.replace(/\s*\([^)]*\)\s*$/, "").trim();
}

/**
 * Occupation de CHAQUE salle du catalogue pour une semaine SOLVEUR (`w`) et
 * un jour (`d`) donnés — un tableau de 6 cases (une par créneau, cf.
 * `utils/slots.ts::SLOT_TIMES`), `null` = libre. Clé = `RoomCatalogEntry.id`.
 *
 * Salles fusionnées (`RoomCatalogEntry.combines`, ex. `h007_h008` →
 * `["h007", "h008"]`, cf. `Room.combines` / `data/config/rooms.yaml`) :
 * réserver la salle fusionnée occupe aussi CHAQUE moitié ; réserver UNE
 * moitié occupe aussi la salle fusionnée — jamais l'autre moitié, qui reste
 * réservable indépendamment (cloison fermée), cf. commentaire sur
 * `RoomType.COMBINED` dans `models/entities.py`.
 */
export function occupationSalles(
  payload: AppPayload,
  week: number,
  day: number,
  /** Identifiant d'une ligne à ne pas compter (la séance dont on choisit la salle). */
  exclureRowId?: string,
): Map<string, CelluleOccupation[]> {
  const grille = new Map<string, CelluleOccupation[]>();
  for (const room of payload.rooms) {
    grille.set(room.id, Array.from({ length: SLOT_COUNT }, () => null));
  }

  // Salle "partie" (ex. h007) -> salle(s) fusionnée(s) qui la recouvrent
  // (ex. h007_h008) — l'inverse de `RoomCatalogEntry.combines`.
  const fusionsParPartie = new Map<string, string[]>();
  for (const room of payload.rooms) {
    for (const partieId of room.combines) {
      const liste = fusionsParPartie.get(partieId) ?? [];
      liste.push(room.id);
      fusionsParPartie.set(partieId, liste);
    }
  }

  const parLibelle = new Map<string, RoomCatalogEntry>();
  for (const room of payload.rooms) {
    parLibelle.set(normaliserLibelleSalle(room.label), room);
  }

  const marquer = (roomId: string, slot: number, entree: OccupationEntree) => {
    const cases = grille.get(roomId);
    if (!cases || slot < 0 || slot >= SLOT_COUNT) return;
    cases[slot] = cases[slot] ? [...(cases[slot] as OccupationEntree[]), entree] : [entree];
  };

  for (const row of payload.rows) {
    if (row.w !== week || row.d !== day || !row.r || row.id === exclureRowId) continue;
    const room = parLibelle.get(normaliserLibelleSalle(row.r));
    if (!room) continue;

    const entree: OccupationEntree = {
      code: row.c,
      type: row.t,
      groupes: row.g.map((g) => payload.groupLabels[g] ?? g),
    };

    const dur = Math.max(1, row.dur || 1);
    for (let k = 0; k < dur; k++) {
      const slot = row.s + k;
      if (slot >= SLOT_COUNT) break; // ne devrait pas arriver (cf. contraintes solveur), défense seulement.
      marquer(room.id, slot, entree);
      for (const partieId of room.combines) marquer(partieId, slot, entree);
      for (const combineeId of fusionsParPartie.get(room.id) ?? []) marquer(combineeId, slot, entree);
    }
  }

  // Réservations par des tiers (ex. amphi pris par la Direction) : même
  // effet qu'une séance sur la salle et ses fusions. Date réelle = lundi de
  // la semaine solveur + jour, jamais un recalcul depuis le libellé.
  const ligneSemaine = payload.weekRows.find((wr) => wr.weekIndex === week);
  if (ligneSemaine?.monday) {
    const [a, m, j] = ligneSemaine.monday.split("-").map(Number);
    const jour = new Date(Date.UTC(a, m - 1, j + day));
    const iso = jour.toISOString().slice(0, 10);
    for (const resa of payload.roomReservations ?? []) {
      if (resa.date !== iso) continue;
      const entree: OccupationEntree = { code: "Réservée", type: "reservation", groupes: resa.motif ? [resa.motif] : [] };
      for (const slot of resa.slots) {
        marquer(resa.salle, slot, entree);
        const room = payload.rooms.find((r) => r.id === resa.salle);
        for (const partieId of room?.combines ?? []) marquer(partieId, slot, entree);
        for (const combineeId of fusionsParPartie.get(resa.salle) ?? []) marquer(combineeId, slot, entree);
      }
    }
  }

  // Salles prises dans Celcat (relevé du sidecar, 01/10/2026) : même effet
  // qu'une réservation de tiers. Miroir : `v1_vues.py::occupation_salles`.
  for (const o of payload.occupationsExternes?.occupations ?? []) {
    if (o.t !== "salle" || o.w !== week || o.d !== day) continue;
    const entree: OccupationEntree = {
      code: "Celcat",
      type: "celcat",
      groupes: [o.dep ? `Réservé dans Celcat (${o.dep})` : "Réservé dans Celcat", o.lib].filter(Boolean),
    };
    const room = payload.rooms.find((r) => r.id === o.code);
    for (const slot of o.s) {
      marquer(o.code, slot, entree);
      for (const partieId of room?.combines ?? []) marquer(partieId, slot, entree);
      for (const combineeId of fusionsParPartie.get(o.code) ?? []) marquer(combineeId, slot, entree);
    }
  }

  return grille;
}

export interface FiltresSallesLibres {
  capaciteMin?: number;
  type?: string;
  /** « Inclure les salles hors placement automatique » — décoché par défaut
   *  (retour utilisateur 22/09/2026) : une salle hors placement automatique
   *  reste choisissable à la main (cf. `RoomCatalogEntry.placementAuto`),
   *  mais ne doit pas polluer la liste par défaut. */
  inclureHorsAuto?: boolean;
}

/**
 * Salles libres à un créneau donné, triées par capacité puis libellé — une
 * salle qui suffit tout juste au groupe passe avant un amphi surdimensionné.
 */
export function sallesLibresAuCreneau(
  payload: AppPayload,
  week: number,
  day: number,
  slot: number,
  filtres: FiltresSallesLibres = {},
): RoomCatalogEntry[] {
  const occupation = occupationSalles(payload, week, day);
  const { capaciteMin = 0, type, inclureHorsAuto = false } = filtres;

  return payload.rooms
    .filter((room) => room.capacity >= capaciteMin)
    .filter((room) => !type || room.type === type)
    .filter((room) => inclureHorsAuto || room.placementAuto)
    .filter((room) => !occupation.get(room.id)?.[slot])
    .sort((a, b) => a.capacity - b.capacity || a.label.localeCompare(b.label, "fr"));
}

/**
 * Salles proposées dans les menus de choix de salle (tâche 22, Kyllian
 * Bresson 11/10/2026 : « les entrées H.007-008 et H.201-203 apparaissent
 * encore dans le menu déroulant. Il faut les supprimer et conserver
 * uniquement les salles individuelles »). Une salle fusionnée
 * (`combines` non vide) n'est plus proposée — sauf si c'est la salle
 * ACTUELLE de la séance (`actuelle`), pour que le menu n'affiche pas une
 * autre salle que celle réellement enregistrée.
 */
export function sallesChoisissables<T extends { id: string; combines?: string[] }>(
  rooms: T[],
  actuelle?: string | null,
): T[] {
  return rooms.filter((r) => !r.combines?.length || r.id === actuelle);
}

/**
 * Disponibilité de chaque salle pour UNE séance de la grille (tâche 28) :
 * `true` = libre sur tous ses créneaux, `false` = déjà prise par une autre
 * séance, une réservation ou une occupation Celcat. La séance elle-même ne
 * compte pas. Pour un placement MANUEL, deux moitiés d'une salle à cloison
 * (H.007 / H.008) sont « la même salle » : l'une occupée rend l'autre rouge,
 * comme le refuse le serveur (`build_manual_conflict_map`).
 */
export function disponibiliteSallesPourSeance(
  payload: AppPayload,
  row: { id: string; w: number; d: number; s: number; dur: number },
): Map<string, boolean> {
  const grille = occupationSalles(payload, row.w, row.d, row.id);
  const dur = Math.max(1, row.dur || 1);
  const prise = (roomId: string) => {
    const cases = grille.get(roomId);
    if (!cases) return false;
    for (let k = 0; k < dur; k++) if (cases[row.s + k]) return true;
    return false;
  };
  const resultat = new Map<string, boolean>();
  for (const room of payload.rooms) resultat.set(room.id, !prise(room.id));
  for (const fusion of payload.rooms) {
    if (!fusion.combines?.length) continue;
    if (fusion.combines.some((partie) => prise(partie))) {
      for (const partie of fusion.combines) resultat.set(partie, false);
    }
  }
  return resultat;
}
