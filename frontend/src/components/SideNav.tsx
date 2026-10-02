/**
 * Navigation principale — rail sombre à icônes (refonte du 29/09/2026).
 *
 * Mêmes vues, mêmes libellés, même ordre qu'avant (les utilisateurs les
 * connaissent) ; « Accueil » (tableau de bord) s'ajoute en tête. Le rail se
 * replie en icônes seules (choix gardé sur l'appareil) pour rendre la
 * largeur aux grilles. La recherche (Ctrl K) est en tête, le compte (clé
 * API, thème, déconnexion, état de la synchro) en pied — comme sur la
 * maquette « Lumière » validée le 29/09/2026.
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
  CalendarX2,
  ChevronsLeft,
  ChevronsRight,
  ClipboardList,
  DatabaseBackup,
  GraduationCap,
  KeyRound,
  LayoutDashboard,
  Library,
  ListChecks,
  RefreshCcw,
  Search,
  ShieldBan,
  ShieldCheck,
  Users,
  UsersRound,
  X,
} from "lucide-react";

import type { RouteView } from "../hooks/useHashRoute";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import { MenuCompte } from "./MenuCompte";
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
      { id: "occupations", label: "Occupé ailleurs", icone: CalendarX2 },
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
    { id: "trafic", label: "Trafic", icone: ShieldBan },
  ],
};

// Compte « Accès API » (29/09/2026) : aucun écran de données, un seul écran.
const GROUPES_ACCES_API: NavGroup[] = [
  { label: "Compte", items: [{ id: "mcp", label: "Accès API", icone: KeyRound }] },
];

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
  /** Compte « Accès API » : navigation réduite à son écran, sans recherche. */
  compteApi?: boolean;
  onOpenSearch?: () => void;
  email?: string;
  role?: string;
  /** `true` = serveur injoignable (pastille sur l'avatar). */
  panne?: boolean;
  onCle?: () => void;
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
  compteApi = false,
  onOpenSearch,
  email,
  role,
  panne = false,
  onCle,
  onLogout,
}: SideNavProps) {
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  const groupes = compteApi ? GROUPES_ACCES_API : estAdmin ? [...NAV_GROUPS, GROUPE_ADMIN] : NAV_GROUPS;
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

        {onOpenSearch && !compteApi && (
          <button
            type="button"
            className="sidenav-recherche"
            onClick={() => {
              onClose();
              onOpenSearch();
            }}
            aria-keyshortcuts="Control+K"
            title={repliee ? "Rechercher (Ctrl K)" : undefined}
          >
            <Search size={15} aria-hidden="true" />
            <span className="navbtn-libelle">Rechercher…</span>
            <kbd>{mac ? "⌘K" : "Ctrl K"}</kbd>
          </button>
        )}

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

        <div className="sidenav-pied">
          {email && (
            <MenuCompte
              email={email}
              role={role}
              panne={panne}
              onCle={
                compteApi
                  ? undefined
                  : () => {
                      onClose();
                      onCle?.();
                    }
              }
              onDeconnexion={() => onLogout?.()}
            />
          )}

          <button
            type="button"
            className="sidenav-replier"
            onClick={basculer}
            aria-pressed={repliee}
            title={repliee ? "Déplier la navigation" : "Replier la navigation"}
          >
            {repliee ? <ChevronsRight size={18} aria-hidden="true" /> : <ChevronsLeft size={18} aria-hidden="true" />}
            <span className="sr-only">{repliee ? "Déplier la navigation" : "Replier la navigation"}</span>
          </button>
        </div>
      </nav>
    </>
  );
}
