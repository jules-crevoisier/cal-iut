/**
 * Barre supérieure de l'application connectée (refonte du 29/09/2026).
 *
 * Elle porte ce qui vaut pour TOUT l'écran, au même endroit sur chaque vue :
 *   - le nom de la vue ouverte (remplace l'ancien bandeau de titre) ;
 *   - LA semaine affichée, partagée par toutes les vues du planning (cf.
 *     `contexts/SemaineGlobale.tsx`) — flèches, retour à aujourd'hui, et la
 *     liste de toutes les semaines de l'année pour sauter loin ;
 *   - la recherche (Ctrl+K), l'état de la synchronisation, le compte.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, LogOut, KeyRound, Menu, Monitor, Moon, Search, Sun } from "lucide-react";

import type { RouteView } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { semaineCalendaireDepuisLundi } from "../utils/weekDisplay";
import { TITRES_VUES } from "./PageHeader";
import { choisirTheme, lireTheme, type Theme } from "../utils/theme";
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
  email?: string;
  onCle: () => void;
  onDeconnexion: () => void;
  /** `true` = serveur injoignable (cf. `BandeauPanne`). */
  panne: boolean;
}

export function TopBar({
  vue,
  payload,
  semaine,
  onSemaine,
  onOuvrirRecherche,
  onOuvrirNavigation,
  email,
  onCle,
  onDeconnexion,
  panne,
}: TopBarProps) {
  const [titre, sousTitre] = TITRES_VUES[vue] ?? ["cal-iut", ""];
  const avecSemaine = VUES_A_SEMAINE.has(vue) && !!payload?.weekRows.length;
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

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
        <button type="button" className="topbar-recherche" onClick={onOuvrirRecherche} aria-keyshortcuts="Control+K">
          <Search size={16} aria-hidden="true" />
          <span className="topbar-recherche-texte">Enseignant, cours, salle, groupe…</span>
          <kbd>{mac ? "⌘ K" : "Ctrl K"}</kbd>
        </button>
        <span
          className={`topbar-synchro ${panne ? "is-panne" : ""}`}
          role="status"
          title={
            panne
              ? "Serveur injoignable : les modifications des collègues n'arrivent plus."
              : "À jour : les modifications des collègues s'affichent d'elles-mêmes."
          }
        >
          <span className="topbar-synchro-point" aria-hidden="true" />
          <span className="topbar-synchro-texte">{panne ? "Hors ligne" : "À jour"}</span>
        </span>
        {email && <MenuCompte email={email} onCle={onCle} onDeconnexion={onDeconnexion} />}
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

function MenuCompte({ email, onCle, onDeconnexion }: { email: string; onCle: () => void; onDeconnexion: () => void }) {
  const [ouvert, setOuvert] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => lireTheme());
  const racine = useRef<HTMLDivElement>(null);
  const initiales = email
    .split("@")[0]!
    .split(/[._-]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((m) => m[0]!.toUpperCase())
    .join("");

  useEffect(() => {
    if (!ouvert) return;
    const fermer = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) {
        if (e.key === "Escape") setOuvert(false);
        return;
      }
      if (!racine.current?.contains(e.target as Node)) setOuvert(false);
    };
    document.addEventListener("mousedown", fermer);
    document.addEventListener("keydown", fermer);
    return () => {
      document.removeEventListener("mousedown", fermer);
      document.removeEventListener("keydown", fermer);
    };
  }, [ouvert]);

  return (
    <div className="topbar-compte" ref={racine}>
      <button
        type="button"
        className="topbar-avatar"
        aria-haspopup="menu"
        aria-expanded={ouvert}
        aria-label={`Compte ${email}`}
        onClick={() => setOuvert((o) => !o)}
      >
        {initiales || "?"}
      </button>
      {ouvert && (
        <div className="topbar-menu-compte" role="menu">
          <p className="topbar-menu-email">{email}</p>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOuvert(false);
              onCle();
            }}
          >
            <KeyRound size={16} aria-hidden="true" /> Clé API
          </button>
          <div className="topbar-theme" role="radiogroup" aria-label="Thème">
            {(
              [
                ["systeme", "Système", Monitor],
                ["clair", "Clair", Sun],
                ["sombre", "Sombre", Moon],
              ] as const
            ).map(([valeur, libelle, Icone]) => (
              <button
                key={valeur}
                type="button"
                role="radio"
                aria-checked={theme === valeur}
                onClick={() => {
                  choisirTheme(valeur);
                  setTheme(valeur);
                }}
              >
                <Icone size={14} aria-hidden="true" /> {libelle}
              </button>
            ))}
          </div>
          <button type="button" role="menuitem" onClick={onDeconnexion}>
            <LogOut size={16} aria-hidden="true" /> Déconnexion
          </button>
        </div>
      )}
    </div>
  );
}
