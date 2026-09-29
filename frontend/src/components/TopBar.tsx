/**
 * Barre supérieure de l'application connectée (refonte du 29/09/2026).
 *
 * Elle porte ce qui vaut pour TOUT l'écran, au même endroit sur chaque vue :
 *   - le nom de la vue ouverte (remplace l'ancien bandeau de titre) ;
 *   - LA semaine affichée, partagée par toutes les vues du planning (cf.
 *     `contexts/SemaineGlobale.tsx`) — flèches, retour à aujourd'hui, et la
 *     liste de toutes les semaines de l'année pour sauter loin ;
 *   - les actions de la page ouverte (`ActionsDePage`, rendues ici par
 *     portail : « Nouvelle séance », « Lisser une promo »…).
 * Maquette « Lumière » validée le 29/09/2026 : titre, semaine et actions sur
 * une seule ligne ; la recherche et le compte sont dans la navigation.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronLeft, ChevronRight, Menu, Search } from "lucide-react";

import type { RouteView } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { semaineCalendaireDepuisLundi } from "../utils/weekDisplay";
import { TITRES_VUES } from "./PageHeader";
import "./TopBar.css";

/** Vues qui affichent UNE semaine : la navigation n'a de sens que là. */
export const VUES_A_SEMAINE: ReadonlySet<RouteView> = new Set<RouteView>([
  "accueil",
  "semaine",
  "promo",
  "prof",
  "groupe",
  "cours",
  "salle",
  "salles-libres",
  "celcat",
]);

const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** « 28 sept. – 2 oct. » depuis le lundi ISO. */
export function datesSemaine(mondayIso: string | undefined): string {
  if (!mondayIso) return "";
  const lundi = new Date(`${mondayIso}T12:00:00`);
  const vendredi = new Date(lundi);
  vendredi.setDate(lundi.getDate() + 4);
  const d1 = `${lundi.getDate()}${lundi.getMonth() === vendredi.getMonth() ? "" : ` ${MOIS[lundi.getMonth()]}`}`;
  return `${d1} – ${vendredi.getDate()} ${MOIS[vendredi.getMonth()]}`;
}

/** « Semaine 6 » depuis « Semaine 6 (28 sept.–2 oct. 2026) ». */
export function nomSemaine(label: string | undefined, index: number): string {
  if (!label) return `Semaine ${index + 1}`;
  return label.replace(/\s*\(.*\)\s*$/, "");
}

interface TopBarProps {
  vue: RouteView;
  payload: AppPayload | null;
  semaine: number;
  onSemaine: (index: number) => void;
  onOuvrirRecherche: () => void;
  onOuvrirNavigation: () => void;
}

const ID_ACTIONS = "topbar-actions";

/**
 * Actions propres à une vue, affichées à droite de la barre supérieure
 * (bouton principal en dernier). Sans barre (liens publics, tests), elles
 * restent à leur place dans la vue.
 */
export function ActionsDePage({ children }: { children: ReactNode }) {
  const [cible, setCible] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setCible(document.getElementById(ID_ACTIONS));
  }, []);
  if (cible) return createPortal(children, cible);
  return <div className="page-outils-actions">{children}</div>;
}

export function TopBar({
  vue,
  payload,
  semaine,
  onSemaine,
  onOuvrirRecherche,
  onOuvrirNavigation,
}: TopBarProps) {
  const [titre, sousTitre] = TITRES_VUES[vue] ?? ["cal-iut", ""];
  const avecSemaine = VUES_A_SEMAINE.has(vue) && !!payload?.weekRows.length;

  return (
    <header className="topbar no-print">
      <button type="button" className="topbar-menu" onClick={onOuvrirNavigation} aria-label="Ouvrir la navigation">
        <Menu size={20} aria-hidden="true" />
      </button>
      <div className="topbar-titre">
        <h1>{titre}</h1>
        {sousTitre && <p title={sousTitre}>{sousTitre}</p>}
      </div>

      {avecSemaine && payload && (
        <NavigationSemaine payload={payload} semaine={semaine} onSemaine={onSemaine} />
      )}

      <div className="topbar-droite">
        <div className="topbar-actions" id={ID_ACTIONS} />
        <button
          type="button"
          className="topbar-recherche-mobile"
          onClick={onOuvrirRecherche}
          aria-label="Rechercher"
        >
          <Search size={18} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

function NavigationSemaine({
  payload,
  semaine,
  onSemaine,
}: {
  payload: AppPayload;
  semaine: number;
  onSemaine: (index: number) => void;
}) {
  const rows = payload.weekRows;
  const courante = indexSemaineCourante(rows);
  const ligne = rows[semaine];
  const calendaire = semaineCalendaireDepuisLundi(ligne?.monday);
  const [ouverte, setOuverte] = useState(false);
  const racine = useRef<HTMLDivElement>(null);

  // Séances par semaine (toutes promos) : repère la charge dans la liste.
  const parSemaine = useMemo(() => {
    const m = new Map<number, number>();
    for (const r of payload.rows) m.set(r.w, (m.get(r.w) ?? 0) + 1);
    return m;
  }, [payload.rows]);

  useEffect(() => {
    if (!ouverte) return;
    const fermer = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) {
        if (e.key === "Escape") setOuverte(false);
        return;
      }
      if (!racine.current?.contains(e.target as Node)) setOuverte(false);
    };
    document.addEventListener("mousedown", fermer);
    document.addEventListener("keydown", fermer);
    // Amène la semaine choisie dans la liste visible.
    racine.current?.querySelector<HTMLElement>("[aria-current='true']")?.scrollIntoView?.({ block: "center" });
    return () => {
      document.removeEventListener("mousedown", fermer);
      document.removeEventListener("keydown", fermer);
    };
  }, [ouverte]);

  const statut = ligne?.blocked
    ? { texte: "pas de cours", cls: "is-bloquee" }
    : semaine === courante
      ? { texte: "cette semaine", cls: "is-courante" }
      : semaine < courante
        ? { texte: "passée", cls: "is-passee" }
        : null;

  return (
    <div className="topbar-semaine" ref={racine}>
      <button
        type="button"
        className="topbar-fleche"
        onClick={() => onSemaine(Math.max(0, semaine - 1))}
        disabled={semaine <= 0}
        aria-label="Semaine précédente"
        title="Semaine précédente (Maj+←)"
      >
        <ChevronLeft size={18} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="topbar-semaine-choix"
        aria-haspopup="listbox"
        aria-expanded={ouverte}
        onClick={() => setOuverte((o) => !o)}
      >
        <span className="topbar-semaine-nom">{nomSemaine(ligne?.label, semaine)}</span>
        <span className="topbar-semaine-dates">{datesSemaine(ligne?.monday)}</span>
        {statut && <span className={`topbar-semaine-statut ${statut.cls}`}>{statut.texte}</span>}
        <ChevronDown size={14} aria-hidden="true" className="topbar-semaine-ouvrir" />
      </button>
      <button
        type="button"
        className="topbar-fleche"
        onClick={() => onSemaine(Math.min(rows.length - 1, semaine + 1))}
        disabled={semaine >= rows.length - 1}
        aria-label="Semaine suivante"
        title="Semaine suivante (Maj+→)"
      >
        <ChevronRight size={18} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="topbar-aujourdhui"
        onClick={() => onSemaine(courante)}
        disabled={semaine === courante}
        title="Revenir à la semaine en cours (T)"
      >
        Aujourd'hui
      </button>
      {calendaire !== null && <span className="topbar-calendaire">sem. {calendaire}</span>}

      {ouverte && (
        <ul className="topbar-semaines" role="listbox" aria-label="Toutes les semaines">
          {rows.map((r, i) => {
            const n = r.weekIndex === null ? 0 : (parSemaine.get(r.weekIndex) ?? 0);
            return (
              <li key={r.monday}>
                <button
                  type="button"
                  role="option"
                  aria-selected={i === semaine}
                  aria-current={i === semaine ? "true" : undefined}
                  className={`${r.blocked ? "is-bloquee" : ""} ${i === courante ? "is-courante" : ""} ${i < courante ? "is-passee" : ""}`}
                  onClick={() => {
                    onSemaine(i);
                    setOuverte(false);
                  }}
                >
                  <span className="nom">{nomSemaine(r.label, i)}</span>
                  <span className="dates">{datesSemaine(r.monday)}</span>
                  <span className="charge">
                    {r.blocked ? "vacances" : i === courante ? "cette semaine" : n ? `${n} séances` : "—"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
