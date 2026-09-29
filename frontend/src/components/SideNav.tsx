/**
 * Navigation principale — rail sombre à icônes (refonte du 29/09/2026).
 *
 * Mêmes vues, mêmes libellés, même ordre qu'avant (les utilisateurs les
 * connaissent) ; « Accueil » (tableau de bord) s'ajoute en tête. Le rail se
 * replie en icônes seules (choix gardé sur l'appareil) pour rendre la
 * largeur aux grilles. Recherche et compte vivent désormais dans la barre
 * supérieure (`TopBar`), présente sur chaque écran.
 *
 * Historique des regroupements (toujours valable) : « Vue Groupe » revenue
 * sous le nom « Vue TD / TP » (22/09/2026) ; « Vue Salle » et « Salles
 * libres » sorties de la nav (25/09/2026 — lien public + recherche).
 */

import { useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  CalendarDays,
  CalendarRange,
  ChevronsLeft,
  ChevronsRight,
  ClipboardList,
  DatabaseBackup,
  GraduationCap,
  LayoutDashboard,
  Library,
  ListChecks,
  RefreshCcw,
  ShieldCheck,
  Users,
  UsersRound,
  X,
} from "lucide-react";

import type { RouteView } from "../hooks/useHashRoute";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import "./SideNav.css";

interface NavItem {
  id: RouteView;
  label: string;
  icone: LucideIcon;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Planning",
    items: [
      { id: "accueil", label: "Accueil", icone: LayoutDashboard },
      { id: "semaine", label: "Vue Semaine", icone: CalendarDays },
    ],
  },
  {
    label: "Perspectives",
    items: [
      { id: "prof", label: "Vue Enseignant", icone: GraduationCap },
      { id: "promo", label: "Vue Promo", icone: CalendarRange },
      { id: "groupe", label: "Vue TD / TP", icone: UsersRound },
    ],
  },
  {
    label: "Référentiel",
    items: [
      { id: "reference", label: "Référence", icone: Library },
      { id: "contraintes", label: "Contraintes", icone: ShieldCheck },
    ],
  },
  {
    label: "À faire",
    // « Tâches » (22/09/2026) : suivi HUMAIN, distinct de « À traiter »,
    // seul onglet alimenté automatiquement par le solveur/l'audit.
    items: [
      { id: "apf", label: "À traiter", icone: ListChecks },
      { id: "taches", label: "Tâches", icone: ClipboardList },
    ],
  },
];

// Réservé au rôle admin (le backend refuse déjà le reste).
const GROUPE_ADMIN: NavGroup = {
  label: "Administration",
  items: [
    { id: "comptes", label: "Comptes", icone: Users },
    { id: "celcat", label: "Celcat", icone: RefreshCcw },
    { id: "sauvegardes", label: "Sauvegardes", icone: DatabaseBackup },
  ],
};

const CLE_REPLIEE = "cal-iut:nav-repliee";

interface SideNavProps {
  activeTab: RouteView;
  onSelect: (id: RouteView) => void;
  hasPayload: boolean;
  /** Nombre total de points « À traiter ». */
  todoCount: number;
  todoHasBad: boolean;
  /** Dont « à corriger » (le reste est « à revoir ») : c'est lui que montre
   * le badge — 300 points dont 200 compromis acceptés ne disent pas combien
   * de choses sont réellement cassées. */
  todoACorriger?: number;
  /** Tiroir ouvert (écran étroit). */
  open: boolean;
  onClose: () => void;
  estAdmin?: boolean;
  // Conservés pour compatibilité d'appel : la recherche et le compte sont
  // désormais dans la barre supérieure.
  onOpenSearch?: () => void;
  email?: string;
  onLogout?: () => void;
}

/**
 * Badge « À traiter » : le nombre de points À CORRIGER en rouge ; s'il n'y en
 * a aucun, le nombre de points à revoir en neutre ; rien quand tout est
 * propre (un « 0 » vert permanent n'apprend rien et attire l'œil).
 */
function BadgeATraiter({ total, aCorriger }: { total: number; aCorriger: number }) {
  const aRevoir = Math.max(0, total - aCorriger);
  if (total === 0) return null;
  const detail = `${aCorriger} à corriger, ${aRevoir} à revoir`;
  return aCorriger > 0 ? (
    <span className="pill mini bad sidenav-badge" aria-label={detail} title={detail}>
      {aCorriger}
    </span>
  ) : (
    <span className="pill mini sidenav-badge" aria-label={detail} title={detail}>
      {aRevoir}
    </span>
  );
}

export function SideNav({
  activeTab,
  onSelect,
  hasPayload,
  todoCount,
  todoHasBad,
  todoACorriger,
  open,
  onClose,
  estAdmin,
}: SideNavProps) {
  const groupes = estAdmin ? [...NAV_GROUPS, GROUPE_ADMIN] : NAV_GROUPS;
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const [repliee, setRepliee] = useState(() => lireLocal<boolean>(CLE_REPLIEE, false, (v): v is boolean => typeof v === "boolean"));

  // Tiroir mobile : le focus va sur « fermer » à l'ouverture (audit a11y du
  // 27/08/2026). Sans effet ≥1024px, où `open` ne passe jamais à `true`.
  useEffect(() => {
    if (open) closeBtnRef.current?.focus();
  }, [open]);

  const basculer = () => {
    setRepliee((r) => {
      ecrireLocal(CLE_REPLIEE, !r);
      return !r;
    });
  };

  return (
    <>
      {open && <div className="sidenav-scrim no-print" onClick={onClose} aria-hidden="true" />}

      <nav
        className={`sidenav no-print ${open ? "open" : ""} ${repliee ? "is-repliee" : ""}`}
        aria-label="Vues de l'emploi du temps"
      >
        <div className="sidenav-brand">
          <span className="brand-mark" aria-hidden="true">
            ci
          </span>
          <div className="sidenav-brand-text">
            <strong>cal-iut</strong>
            <span className="sidenav-sub">MMI Troyes</span>
          </div>
          <button
            type="button"
            ref={closeBtnRef}
            className="sidenav-close"
            onClick={onClose}
            aria-label="Fermer la navigation"
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        {/* Boutons de navigation (et non `role="tab"`) : `aria-current="page"`
            est le bon vocabulaire (audit a11y du 27/08/2026). */}
        <div className="sidenav-tabs">
          {groupes.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-group-label" aria-hidden="true">
                {group.label}
              </span>
              {group.items.map((t) => {
                const Icone = t.icone;
                return (
                  <button
                    key={t.id}
                    type="button"
                    id={`onglet-${t.id}`}
                    aria-current={activeTab === t.id ? "page" : undefined}
                    aria-controls="contenu"
                    className={`navbtn ${activeTab === t.id ? "active" : ""}`}
                    title={repliee ? t.label : undefined}
                    onClick={() => {
                      onSelect(t.id);
                      onClose();
                    }}
                  >
                    <Icone size={18} strokeWidth={1.75} aria-hidden="true" className="navbtn-icone" />
                    <span className="navbtn-libelle">{t.label}</span>
                    {t.id === "apf" && hasPayload && (
                      <BadgeATraiter
                        total={todoCount}
                        aCorriger={todoACorriger ?? (todoHasBad ? todoCount : 0)}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <button
          type="button"
          className="sidenav-replier"
          onClick={basculer}
          aria-pressed={repliee}
          title={repliee ? "Déplier la navigation" : "Replier la navigation"}
        >
          {repliee ? <ChevronsRight size={18} aria-hidden="true" /> : <ChevronsLeft size={18} aria-hidden="true" />}
          <span className="navbtn-libelle">{repliee ? "Déplier" : "Replier"}</span>
        </button>
      </nav>
    </>
  );
}
