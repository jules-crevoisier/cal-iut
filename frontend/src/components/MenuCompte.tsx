/**
 * Compte connecté, en bas de la navigation (direction « Lumière / Nuit »,
 * 29/09/2026) : avatar, nom, rôle — et l'état de la synchronisation en
 * pastille sur l'avatar. Le menu s'ouvre vers le haut : Clé API, thème,
 * déconnexion.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { KeyRound, LogOut, Monitor, Moon, Sun } from "lucide-react";

import { choisirTheme, lireTheme, type Theme } from "../utils/theme";

const ROLES: Record<string, string> = {
  admin: "Administrateur",
  edit: "Édition",
  read_only: "Lecture seule",
};

/** « jules.crevoisier@… » → « Jules Crevoisier ». */
export function nomDepuisEmail(email: string): string {
  return email
    .split("@")[0]!
    .split(/[._-]/)
    .filter(Boolean)
    .map((m) => m[0]!.toUpperCase() + m.slice(1))
    .join(" ");
}

interface MenuCompteProps {
  email: string;
  role?: string;
  /** `true` = serveur injoignable (cf. `BandeauPanne`). */
  panne: boolean;
  onCle: () => void;
  onDeconnexion: () => void;
}

export function MenuCompte({ email, role, panne, onCle, onDeconnexion }: MenuCompteProps) {
  const [ouvert, setOuvert] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => lireTheme());
  // Position du menu, en `fixed` : la navigation défile (`overflow-y: auto`),
  // ce qui coupait le menu à sa largeur — « Sombre » disparaissait, et le
  // rail replié (60 px) n'en montrait presque rien (retour du 29/09/2026).
  const [position, setPosition] = useState<CSSProperties>({});
  const racine = useRef<HTMLDivElement>(null);
  const bouton = useRef<HTMLButtonElement>(null);
  const nom = nomDepuisEmail(email) || email;
  const initiales = nom
    .split(" ")
    .slice(0, 2)
    .map((m) => m[0])
    .join("");
  const synchro = panne
    ? "Hors ligne : les modifications des collègues n'arrivent plus."
    : "À jour : les modifications des collègues s'affichent d'elles-mêmes.";

  useEffect(() => {
    if (!ouvert) return;
    const fermer = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) {
        if (e.key === "Escape") setOuvert(false);
        return;
      }
      if (!racine.current?.contains(e.target as Node)) setOuvert(false);
    };
    const fermerAuRedimensionnement = () => setOuvert(false);
    document.addEventListener("mousedown", fermer);
    document.addEventListener("keydown", fermer);
    window.addEventListener("resize", fermerAuRedimensionnement);
    return () => {
      document.removeEventListener("mousedown", fermer);
      document.removeEventListener("keydown", fermer);
      window.removeEventListener("resize", fermerAuRedimensionnement);
    };
  }, [ouvert]);

  const basculer = () => {
    const r = bouton.current?.getBoundingClientRect();
    if (r) setPosition({ left: Math.max(8, r.left), bottom: Math.max(8, window.innerHeight - r.top + 6) });
    setOuvert((o) => !o);
  };

  return (
    <div className="compte" ref={racine}>
      {ouvert && (
        <div className="compte-menu" role="menu" style={position}>
          <p className="compte-menu-email">{email}</p>
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
          <div className="compte-theme" role="radiogroup" aria-label="Thème">
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
      <button
        type="button"
        ref={bouton}
        className="compte-bouton"
        aria-haspopup="menu"
        aria-expanded={ouvert}
        aria-label={`Compte ${email}`}
        title={email}
        onClick={basculer}
      >
        <span className="compte-avatar" aria-hidden="true">
          {initiales || "?"}
          <span className={`compte-synchro ${panne ? "is-panne" : ""}`} />
        </span>
        <span className="compte-texte">
          <strong>{nom}</strong>
          <small>{ROLES[role ?? ""] ?? "Compte"}</small>
        </span>
      </button>
      <span className={`compte-etat ${panne ? "is-panne" : ""}`} role="status" title={synchro}>
        {panne ? "Hors ligne" : <span className="sr-only">À jour</span>}
      </span>
    </div>
  );
}
