/**
 * Recherche globale (Ctrl+K) — enseignant, promo, groupe, cours, salle ou
 * écran de l'application ; ouvre directement la bonne vue.
 *
 * Refonte du 29/09/2026 : résultats groupés par type (le groupe le plus
 * pertinent en tête), correspondance surlignée, ↑/↓ qui bouclent, Début/Fin,
 * la ligne choisie reste visible au défilement, et les derniers résultats
 * ouverts sont proposés dès l'ouverture (on cherche souvent les mêmes).
 */

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import {
  buildSearchIndex,
  ECRANS,
  rechercheGroupee,
  surligner,
  type GroupeResultats,
  type SearchHit,
} from "../utils/search";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import "./GlobalSearch.css";

const CLE_RECENTS = "cal-iut:recherche:recents:v1";
const MAX_RECENTS = 6;

const DESTINATION: Record<SearchHit["kind"], string> = {
  Enseignant: "Vue Enseignant",
  Promo: "Vue Promo",
  Groupe: "Vue TD / TP",
  Cours: "Vue Cours",
  Salle: "Vue Salle",
  Écran: "Ouvrir",
};

function estListeHits(v: unknown): v is SearchHit[] {
  return Array.isArray(v) && v.every((h) => typeof h === "object" && h !== null && "label" in h && "route" in h);
}

interface GlobalSearchProps {
  payload: AppPayload;
  open: boolean;
  onClose: () => void;
  onNavigate: (patch: Partial<Route>) => void;
}

export function GlobalSearch({ payload, open, onClose, onNavigate }: GlobalSearchProps) {
  const index = useMemo(() => [...buildSearchIndex(payload), ...ECRANS], [payload]);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const [recents, setRecents] = useState<SearchHit[]>(() => lireLocal(CLE_RECENTS, [], estListeHits));
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  // Élément qui avait le focus AVANT l'ouverture : sans lui, refermer la
  // recherche renvoyait le focus sur `<body>`.
  const previousFocus = useRef<HTMLElement | null>(null);

  const groupes: GroupeResultats[] = useMemo(() => {
    if (query.trim()) return rechercheGroupee(index, query);
    const g: GroupeResultats[] = [];
    if (recents.length) g.push({ kind: "Récents", titre: "Ouverts récemment", hits: recents, total: recents.length });
    g.push({ kind: "Écran", titre: "Écrans", hits: ECRANS, total: ECRANS.length });
    return g;
  }, [index, query, recents]);
  const plats = useMemo(() => groupes.flatMap((g) => g.hits), [groupes]);

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

  // La ligne choisie au clavier reste visible dans la liste qui défile.
  useEffect(() => {
    document.getElementById(`resultat-${sel}`)?.scrollIntoView?.({ block: "nearest" });
  }, [sel]);

  // Piège à focus : sans lui, la tabulation sort de la boîte de dialogue.
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
    const suivants = [hit, ...recents.filter((r) => !(r.kind === hit.kind && r.label === hit.label))].slice(0, MAX_RECENTS);
    setRecents(suivants);
    ecrireLocal(CLE_RECENTS, suivants);
    onClose();
    onNavigate(hit.route);
  };

  if (!open) return null;

  let rang = -1;

  return (
    <div className="searchoverlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="searchbox" ref={boxRef} role="dialog" aria-modal="true" aria-label="Recherche globale">
        <label className="sr-only" htmlFor="recherche-globale">
          Rechercher un enseignant, un cours, une salle, un groupe, une promo ou un écran
        </label>
        <div className="searchbox-champ">
          <input
            id="recherche-globale"
            ref={inputRef}
            type="search"
            placeholder="Enseignant, cours, salle, groupe, promo ou écran…"
            autoComplete="off"
            spellCheck={false}
            role="combobox"
            aria-expanded="true"
            aria-controls="recherche-resultats"
            aria-activedescendant={plats[sel] ? `resultat-${sel}` : undefined}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSel(0);
            }}
            onKeyDown={(e) => {
              const n = plats.length;
              if (e.key === "ArrowDown") {
                e.preventDefault();
                if (n) setSel((s) => (s + 1) % n);
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                if (n) setSel((s) => (s - 1 + n) % n);
              } else if (e.key === "Home" && e.ctrlKey) {
                e.preventDefault();
                setSel(0);
              } else if (e.key === "End" && e.ctrlKey) {
                e.preventDefault();
                setSel(Math.max(0, n - 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                activate(plats[sel]);
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
          />
          <button type="button" className="btn btn--ghost btn--sm searchbox-fermer" onClick={onClose}>
            Échap
          </button>
        </div>
        <p className="sr-only" aria-live="polite">
          {plats.length === 0 ? "Aucun résultat" : `${plats.length} résultat${plats.length > 1 ? "s" : ""}`}
        </p>
        <div className="searchresults" id="recherche-resultats" role="listbox" aria-label="Résultats">
          {plats.length === 0 ? (
            <div className="searchempty">
              Aucun résultat pour « {query.trim()} ». Essayez un code (KBR, WR101), un nom ou une salle (H.201).
            </div>
          ) : (
            groupes.map((g) => (
              <Fragment key={g.kind}>
                <div className="searchgroup" role="presentation">
                  <span>{g.titre}</span>
                  {g.total > g.hits.length && (
                    <span className="searchgroup-plus">
                      {g.hits.length} sur {g.total} — précisez la recherche
                    </span>
                  )}
                </div>
                {g.hits.map((h) => {
                  rang += 1;
                  const i = rang;
                  return (
                    <button
                      key={`${g.kind}-${h.kind}-${h.sub}-${h.label}`}
                      id={`resultat-${i}`}
                      type="button"
                      role="option"
                      tabIndex={-1}
                      aria-selected={i === sel}
                      className={`hit ${i === sel ? "sel" : ""}`}
                      onMouseMove={() => i !== sel && setSel(i)}
                      onClick={() => activate(h)}
                    >
                      <span className="hit-texte">
                        <span className="hit-label">
                          <Surligne texte={h.label} query={query} />
                        </span>
                        {h.sub && (
                          <span className="hit-sub">
                            <Surligne texte={h.sub} query={query} />
                          </span>
                        )}
                      </span>
                      <span className="hit-dest">{g.kind === "Récents" ? h.kind : DESTINATION[h.kind]}</span>
                    </button>
                  );
                })}
              </Fragment>
            ))
          )}
        </div>
        <div className="searchhint" aria-hidden="true">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> choisir
          </span>
          <span>
            <kbd>Entrée</kbd> ouvrir
          </span>
          <span>
            <kbd>Échap</kbd> fermer
          </span>
        </div>
      </div>
    </div>
  );
}

function Surligne({ texte, query }: { texte: string; query: string }) {
  return (
    <>
      {surligner(texte, query).map((s, i) => (s.surligne ? <mark key={i}>{s.texte}</mark> : <Fragment key={i}>{s.texte}</Fragment>))}
    </>
  );
}
