/**
 * Navigation principale — barre latérale groupée par intention plutôt qu'une
 * rangée plate de 8 onglets indifférenciés (retour utilisateur 25/08/2026 :
 * « il faut rebosser cela [...] la je suis perdu »). Les 8 vues restent
 * exactement les mêmes, seul le regroupement visuel change :
 *   - Planning     : la vue par défaut, celle qu'on utilise le plus.
 *   - Perspectives : mêmes données, lues depuis un autre angle (groupe/prof/promo).
 *   - Référentiel  : consultation, pas d'action (données sources, contraintes).
 *   - À faire      : ce qui réclame une décision humaine (badges de compte).
 *
 * `role="tablist"`/`aria-selected` conservés à l'identique de l'ancienne
 * `.tabbar` (portage direct) — même sémantique, nouvelle disposition. Les
 * libellés de groupe sont décoratifs (`aria-hidden`) : chaque bouton reste
 * auto-porteur pour un lecteur d'écran (libellé + état sélectionné), le
 * regroupement n'aide que le repérage visuel.
 */

import { useEffect, useRef } from "react";

import type { RouteView } from "../hooks/useHashRoute";

interface NavItem {
  id: RouteView;
  label: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  { label: "Planning", items: [{ id: "semaine", label: "Vue Semaine" }] },
  {
    // "Vue Groupe" retirée de la navigation (retour utilisateur 27/08/2026 :
    // "vue groupe on peut l'enlever") — le composant et sa route restent
    // (le lien personnel `mode=groupe` envoyé à un groupe d'étudiants en a
    // toujours besoin, cf. App.tsx `readOnlyTarget`), seul l'onglet visible
    // dans la nav disparaît.
    label: "Perspectives",
    items: [
      { id: "prof", label: "Vue Enseignant" },
      { id: "promo", label: "Vue Promo" },
    ],
  },
  {
    label: "Référentiel",
    items: [
      { id: "reference", label: "Référence" },
      { id: "contraintes", label: "Contraintes" },
    ],
  },
  {
    label: "À faire",
    items: [{ id: "apf", label: "À traiter" }],
  },
];

// Groupe séparé, ajouté conditionnellement (cf. `SideNav` — `estAdmin`) :
// gestion des comptes (31/08/2026), réservée au rôle admin. Le backend
// refuse déjà tout le reste (`Depends(require_role("admin"))`) ; ne pas
// même proposer l'onglet aux autres rôles évite un aller-retour pour rien.
const GROUPE_ADMIN: NavGroup = {
  label: "Administration",
  items: [{ id: "comptes", label: "Comptes" }],
};

interface SideNavProps {
  activeTab: RouteView;
  onSelect: (id: RouteView) => void;
  onOpenSearch: () => void;
  hasPayload: boolean;
  todoCount: number;
  todoHasBad: boolean;
  open: boolean;
  onClose: () => void;
  estAdmin?: boolean;
  email?: string;
  onLogout?: () => void;
}

export function SideNav({
  activeTab,
  onSelect,
  onOpenSearch,
  hasPayload,
  todoCount,
  todoHasBad,
  open,
  onClose,
  estAdmin,
  email,
  onLogout,
}: SideNavProps) {
  const groupes = estAdmin ? [...NAV_GROUPS, GROUPE_ADMIN] : NAV_GROUPS;
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  // Tiroir mobile : à l'ouverture, le focus clavier reste sur le bouton ☰
  // (masqué derrière le tiroir) si on ne le déplace pas explicitement —
  // l'amener sur le bouton fermer (premier élément utile du panneau) rend
  // le tiroir immédiatement navigable au clavier (audit a11y du 27/08/2026).
  // Sans effet à ≥1024px : `open` n'y passe jamais à `true` (le ☰ qui le
  // déclenche est lui-même masqué par CSS à cette largeur).
  useEffect(() => {
    if (open) closeBtnRef.current?.focus();
  }, [open]);

  return (
    <>
      {/* Fond assombri derrière le tiroir mobile — clic = fermer, ignoré au
          clavier (Échap le fait déjà, cf. App.tsx) et par les lecteurs
          d'écran (purement visuel, jamais atteint au clavier). */}
      {open && <div className="sidenav-scrim no-print" onClick={onClose} aria-hidden="true" />}

      <nav className={`sidenav no-print ${open ? "open" : ""}`} aria-label="Vues de l'emploi du temps">
        <div className="sidenav-brand">
          <span className="brand-mark">CI</span>
          <div className="sidenav-brand-text">
            <strong>cal-iut</strong>
            <span className="sidenav-sub">Emplois du temps</span>
          </div>
          {/* Uniquement visible en tiroir (<1024px, cf. app.css) : sous
              1024px le clic hors du panneau ferme aussi, mais un bouton
              explicite reste nécessaire au clavier/tactile. */}
          <button
            type="button"
            ref={closeBtnRef}
            className="sidenav-close"
            onClick={onClose}
            aria-label="Fermer la navigation"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>

        {/* Pas `role="tablist"`/`role="tab"` : ces boutons naviguent vers une
            page entièrement différente (comme des liens), sans le clavier
            flèches/roving-tabindex qu'un vrai widget ARIA "tab" impose —
            `aria-current="page"` est le bon vocabulaire pour ce cas
            (audit a11y du 27/08/2026 : l'ancien `role="tab"`, porté tel
            quel depuis la barre d'onglets d'origine, annonçait un widget
            dont le clavier ne suivait pas le comportement). */}
        {/* `<div>` et non un second `<nav>` : le `<nav className="sidenav">`
            englobant est déjà le repère de navigation, un nav imbriqué en
            ajouterait un second redondant. */}
        <div className="sidenav-tabs">
          {groupes.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-group-label" aria-hidden="true">
                {group.label}
              </span>
              {group.items.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  id={`onglet-${t.id}`}
                  aria-current={activeTab === t.id ? "page" : undefined}
                  aria-controls="contenu"
                  className={`navbtn ${activeTab === t.id ? "active" : ""}`}
                  onClick={() => {
                    onSelect(t.id);
                    onClose();
                  }}
                >
                  {t.label}
                  {t.id === "apf" && hasPayload && (
                    <span
                      className={`pill mini ${todoHasBad ? "bad" : todoCount ? "warn" : "good"}`}
                      aria-label={`${todoCount} point(s) à traiter`}
                    >
                      {todoCount}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>

        <button
          type="button"
          className="searchopenbtn sidenav-search"
          onClick={onOpenSearch}
          aria-keyshortcuts="Control+K"
        >
          Rechercher <span className="mono kbd" aria-hidden="true">Ctrl+K</span>
        </button>

        {email && (
          <div className="sidenav-compte">
            <span className="sidenav-compte-email" title={email}>
              {email}
            </span>
            <button
              type="button"
              className={`navbtn ${activeTab === "mcp" ? "active" : ""}`}
              aria-current={activeTab === "mcp" ? "page" : undefined}
              onClick={() => {
                onSelect("mcp");
                onClose();
              }}
            >
              Clé Claude / MCP
            </button>
            {onLogout && (
              <button type="button" className="navbtn sidenav-logout" onClick={onLogout}>
                Déconnexion
              </button>
            )}
          </div>
        )}
      </nav>
    </>
  );
}
