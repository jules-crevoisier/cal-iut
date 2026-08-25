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

  const hits = useMemo(() => runSearch(index, query), [index, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSel(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const activate = (hit: SearchHit | undefined) => {
    if (!hit) return;
    onClose();
    onNavigate(hit.route);
  };

  if (!open) return null;

  return (
    <div className="searchoverlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="searchbox">
        <input
          ref={inputRef}
          type="search"
          placeholder="Enseignant, cours, salle ou groupe…"
          autoComplete="off"
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
        <div className="searchresults">
          {hits.length === 0 ? (
            <div className="searchempty">Aucun résultat.</div>
          ) : (
            hits.map((h, i) => (
              <button
                key={`${h.kind}-${h.sub}-${h.label}`}
                type="button"
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
