/**
 * Conflits PAR SÉANCE pour la Vue Promo (tâche 25, Kyllian Bresson 03/11/2026).
 *
 * Aucune nouvelle détection : on réutilise celle de « À traiter » —
 * `GET /controles/doublons` (salle ou enseignant mobilisé deux fois, exceptions
 * des duos et des salles voisines déjà appliquées côté serveur) et les
 * conflits d'occupation Celcat du payload (`occupationsExternes.conflits`).
 * Chaque séance reçoit au plus deux indicateurs, indépendants : salle et
 * enseignant.
 */
import type { Doublon } from "../api/client";
import type { AppPayload } from "../types/app";

export interface ConflitsSeance {
  /** Messages du conflit de salle (vide = pas de conflit). */
  salle: string[];
  /** Messages du doublon enseignant (vide = pas de doublon). */
  enseignant: string[];
}

function entree(m: Map<string, ConflitsSeance>, id: string): ConflitsSeance {
  let c = m.get(id);
  if (!c) {
    c = { salle: [], enseignant: [] };
    m.set(id, c);
  }
  return c;
}

function ajouter(liste: string[], message: string): void {
  if (!liste.includes(message)) liste.push(message);
}

export function conflitsParSeance(
  doublons: Doublon[] | null | undefined,
  payload: Pick<AppPayload, "occupationsExternes">,
  semaine: number | null,
): Map<string, ConflitsSeance> {
  const resultat = new Map<string, ConflitsSeance>();
  for (const d of doublons ?? []) {
    if (semaine !== null && d.semaine !== semaine) continue;
    for (const s of d.seances) {
      const autres = d.seances.filter((o) => o.session_id !== s.session_id).map((o) => o.course_code);
      const avec = autres.length ? ` avec ${autres.join(", ")}` : "";
      const c = entree(resultat, s.session_id);
      if (d.type === "salle") ajouter(c.salle, `Salle ${d.ressource} déjà occupée${avec}`);
      else ajouter(c.enseignant, `${d.ressource} est affecté à deux séances en même temps${avec}`);
    }
  }
  // Occupation Celcat d'une salle (autre département) : même indicateur « salle ».
  for (const c of payload.occupationsExternes?.conflits ?? []) {
    if (c.ressource_type !== "salle") continue;
    if (semaine !== null && c.semaine !== semaine) continue;
    ajouter(entree(resultat, c.seance_id).salle, c.message || `Salle ${c.ressource} occupée dans Celcat`);
  }
  return resultat;
}
