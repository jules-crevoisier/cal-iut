/**
 * En-tête de page : le NOM de la vue ouverte et une ligne qui dit à quoi
 * elle sert.
 *
 * Remplace (refonte du 29/09/2026) le titre fixe « Planning généré — Sortie
 * du solveur CP-SAT cal-iut. », identique sur les 15 onglets : il occupait
 * ~100 px en haut de chaque écran sans jamais dire où l'on était, et parlait
 * du solveur à des utilisateurs qui ne le lancent plus (génération en CLI
 * depuis le 27/08/2026).
 *
 * La pastille de statut du solveur reste, mais seulement quand elle apprend
 * quelque chose : « Optimal » n'est pas une information pour l'utilisateur,
 * « Faisable (limite de temps) » ou « Infaisable » en sont une. `CACHED` (le
 * planning vient de la base) n'est jamais affiché — cf. retour utilisateur
 * 28/08/2026 : « enlève moi ça CACHED ».
 */

import type { RouteView } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";

const STATUS_MAP: Record<string, [string, string]> = {
  FEASIBLE: ["warn", "Solveur : faisable (limite de temps atteinte)"],
  INFEASIBLE: ["bad", "Solveur : infaisable"],
};

/** [titre, ligne d'explication, ligne COURTE]. La ligne courte remplace la
 *  longue dans la barre supérieure quand la page y met ses actions (la place
 *  manque) ; sans elle, rien ne s'affiche à côté du titre dans ce cas. */
export const TITRES_VUES: Record<RouteView, [string, string, string?]> = {
  accueil: ["Accueil", "La semaine en un coup d'œil : ce qui demande une décision, la charge par promo."],
  semaine: ["Vue Semaine", "Le planning d'un groupe, d'un enseignant ou d'une salle, semaine par semaine."],
  prof: ["Vue Enseignant", "Planning, contraintes déclarées et interventions du semestre d'un enseignant.", "Planning et contraintes"],
  promo: ["Vue Promo", "Toutes les promotions sur une même grille, jour par jour — c'est ici qu'on déplace les séances.", "Toutes les promos, jour par jour"],
  groupe: ["Vue TD / TP", "Le planning d'un groupe d'étudiants.", "Le planning d'un groupe"],
  cours: ["Vue Cours", "Toutes les séances d'une ressource ou d'une SAE.", "Ressources et SAE"],
  salle: ["Vue Salle", "L'occupation d'une salle, semaine par semaine.", "Occupation des salles"],
  "salles-libres": ["Salles libres", "Qui occupe quelle salle, créneau par créneau."],
  reference: ["Référence", "Salles, cours, calendrier institutionnel, liens de partage et notifications."],
  contraintes: ["Contraintes", "Chaque règle, avec son verdict recalculé sur le planning actuel."],
  apf: ["À traiter", "Ce qui demande une décision : séances non placées, doublons, violations, journées trouées."],
  aplacer: ["À placer", "Les séances que le solveur n'a pas su placer."],
  taches: ["Tâches", "Le suivi de l'équipe : absences signalées, déplacements à faire, points à suivre.", "Le suivi de l'équipe"],
  comptes: ["Comptes", "Activer, changer le rôle ou désactiver les comptes."],
  celcat: ["Celcat", "Concordance entre ce planning et Celcat, et file des corrections envoyées."],
  sauvegardes: ["Sauvegardes", "Une copie datée des séances placées, chaque jour où le planning change.", "Une copie par jour de changement"],
  mcp: ["Clé API", "Clés d'accès pour Claude (MCP) et les scripts qui lisent l'API.", "Accès pour Claude (MCP) et les scripts"],
};

interface PageHeaderProps {
  vue: RouteView;
  payload: AppPayload | null;
}

export function PageHeader({ vue, payload }: PageHeaderProps) {
  const [titre, sousTitre] = TITRES_VUES[vue] ?? ["cal-iut", ""];
  const statut = STATUS_MAP[payload?.status ?? ""];
  return (
    <header className="top">
      <div className="titles">
        <h1>{titre}</h1>
        {sousTitre && <p>{sousTitre}</p>}
      </div>
      {statut && <span className={`pill dot ${statut[0]}`}>{statut[1]}</span>}
    </header>
  );
}
