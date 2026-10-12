import type { WeekRow } from "../types/app";

/** Index d'AFFICHAGE (dans `weekRows`) de la semaine qui contient `aujourdhui`.
 *
 * Retour utilisateur 08/09/2026 : « fais en sorte que dans vue promo on
 * arrive directement dans la semaine actuelle sélectionnée ». L'application
 * s'ouvrait sur la première semaine de l'année, qu'on n'a plus besoin de
 * voir dès la deuxième semaine de cours.
 *
 * Le repère est le LUNDI de chaque ligne, jamais un compteur : les semaines
 * bloquées (vacances) créent des trous dans `weekRows`, et compter les
 * lignes depuis la rentrée donnerait la mauvaise dès la Toussaint passée —
 * c'est exactement le décalage qui avait déjà valu un bug de régénération
 * sur la mauvaise semaine (cf. `App.tsx`, `solverWeek`).
 *
 * Hors année scolaire, on retombe sur la première ou la dernière ligne
 * plutôt que sur un index arbitraire : en juillet, ce qu'on consulte est la
 * fin de l'année écoulée, pas la rentrée de septembre.
 */
export function indexSemaineCourante(semaines: WeekRow[], aujourdhui: Date = new Date()): number {
  if (semaines.length === 0) return 0;

  const jour = new Date(aujourdhui.getFullYear(), aujourdhui.getMonth(), aujourdhui.getDate());
  let dernierAvant = -1;

  for (let i = 0; i < semaines.length; i += 1) {
    const lundi = new Date(`${semaines[i].monday}T00:00:00`);
    if (Number.isNaN(lundi.getTime())) continue;
    const dimancheSoir = new Date(lundi);
    dimancheSoir.setDate(dimancheSoir.getDate() + 6);
    if (jour >= lundi && jour <= dimancheSoir) return i;
    if (lundi <= jour) dernierAvant = i;
  }

  // Aucune semaine ne contient la date : avant la rentrée -> la première ;
  // après la fin de l'année -> la dernière commencée.
  return dernierAvant >= 0 ? dernierAvant : 0;
}


/** Index du jour de la semaine (lundi = 0), replié sur lundi le week-end.
 *
 * Retour utilisateur 08/09/2026 : « on veut arriver à la bonne semaine et au
 * bon jour ». Ouvrir sur lundi un vendredi oblige à cliquer à chaque fois,
 * et c'est le genre de friction qu'on ne remarque plus mais qu'on subit.
 *
 * Samedi et dimanche retombent sur lundi : il n'y a pas cours, et ouvrir sur
 * une colonne vide serait pire que sur le premier jour de la semaine qu'on
 * s'apprête à préparer.
 */
export function jourOuvreAujourdhui(aujourdhui: Date = new Date()): number {
  const jour = aujourdhui.getDay(); // 0 = dimanche
  if (jour === 0 || jour === 6) return 0;
  return jour - 1;
}


/** Index de la semaine où mène le bouton « Aujourd'hui » (et la touche T).
 *
 * Tâche #21 (Kyllian, 11/10/2026) : MMI n'a pas cours le week-end. Du lundi
 * au vendredi, c'est la semaine qui contient la date du jour ; le samedi ou
 * le dimanche, c'est la semaine du lundi suivant — celle qu'on prépare.
 * Exemple : samedi 10 ou dimanche 11 octobre 2026 -> lundi 12 octobre.
 *
 * Seul ce bouton change : l'ouverture de l'application et le repère
 * « cette semaine » restent sur la semaine calendaire (`indexSemaineCourante`).
 */
export function indexSemaineAujourdhui(semaines: WeekRow[], aujourdhui: Date = new Date()): number {
  const jour = aujourdhui.getDay(); // 0 = dimanche
  if (jour !== 0 && jour !== 6) return indexSemaineCourante(semaines, aujourdhui);
  const lundi = new Date(aujourdhui.getFullYear(), aujourdhui.getMonth(), aujourdhui.getDate());
  lundi.setDate(lundi.getDate() + (jour === 6 ? 2 : 1));
  return indexSemaineCourante(semaines, lundi);
}
