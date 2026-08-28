import { useEffect, useMemo, useRef, useState } from "react";

import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { buildSearchIndex, runSearch, type SearchHit } from "../utils/search";

interface GlobalSearchProps {
  payload: AppPayload;
  open: boolean;
  onClose: () => void;
  onNavigate: (patch: Partial<Route>) => void;
}

/** Recherche globale (Ctrl+K) — enseignant, groupe, cours ou salle, ouvre
 * directement la bonne vue. Portage de la recherche de la page HTML/JS. */
export function GlobalSearch({ payload, open, onClose, onNavigate }: GlobalSearchProps) {
  const index = useMemo(() => buildSearchIndex(payload), [payload]);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  // Élément qui avait le focus AVANT l'ouverture : sans lui, refermer la
  // recherche renvoyait le focus sur `<body>` et il fallait re-tabuler depuis
  // le haut de la page pour reprendre sa navigation.
  const previousFocus = useRef<HTMLElement | null>(null);

  const hits = useMemo(() => runSearch(index, query), [index, query]);

  useEffect(() => {
    if (open) {
      previousFocus.current = document.activeElement as HTMLElement | null;
      setQuery("");
      setSel(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      previousFocus.current?.focus?.();
    }
  }, [open]);

  // Piège à focus : sans lui, la tabulation sort de la boîte de dialogue et
  // parcourt la page derrière, invisible et inatteignable à la souris.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !boxRef.current) return;
      const focusables = boxRef.current.querySelectorAll<HTMLElement>(
        'input, button, [href], [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const premier = focusables[0];
      const dernier = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === premier) {
        e.preventDefault();
        dernier.focus();
      } else if (!e.shiftKey && document.activeElement === dernier) {
        e.preventDefault();
        premier.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const activate = (hit: SearchHit | undefined) => {
    if (!hit) return;
    onClose();
    onNavigate(hit.route);
  };

  if (!open) return null;

  return (
    <div className="searchoverlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className="searchbox"
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label="Recherche globale"
      >
        <label className="sr-only" htmlFor="recherche-globale">
          Rechercher un enseignant, un cours, une salle ou un groupe
        </label>
        <input
          id="recherche-globale"
          ref={inputRef}
          type="search"
          placeholder="Enseignant, cours, salle ou groupe…"
          autoComplete="off"
          role="combobox"
          aria-expanded="true"
          aria-controls="recherche-resultats"
          aria-activedescendant={hits[sel] ? `resultat-${sel}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setSel((s) => Math.min(hits.length - 1, s + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setSel((s) => Math.max(0, s - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              activate(hits[sel]);
            } else if (e.key === "Escape") {
              onClose();
            }
          }}
        />
        {/* Le nombre de résultats n'existait que visuellement : un lecteur
            d'écran ne savait pas que la liste avait changé en tapant. */}
        <p className="sr-only" aria-live="polite">
          {hits.length === 0
            ? "Aucun résultat"
            : `${hits.length} résultat${hits.length > 1 ? "s" : ""}`}
        </p>
        <div className="searchresults" id="recherche-resultats" role="listbox">
          {hits.length === 0 ? (
            <div className="searchempty">Aucun résultat.</div>
          ) : (
            hits.map((h, i) => (
              <button
                key={`${h.kind}-${h.sub}-${h.label}`}
                id={`resultat-${i}`}
                type="button"
                role="option"
                aria-selected={i === sel}
                className={`hit ${i === sel ? "sel" : ""}`}
                onClick={() => activate(h)}
              >
                <span className="kind">{h.kind}</span>
                <span>
                  <strong>{h.label}</strong>
                  {h.sub && <div className="sub">{h.sub}</div>}
                </span>
              </button>
            ))
          )}
        </div>
        <div className="searchhint">↑↓ pour naviguer · Entrée pour ouvrir · Échap pour fermer</div>
      </div>
    </div>
  );
}
