/**
 * Carte d'une séance dans la grille de la Vue Promo (refonte du 29/09/2026).
 *
 * Deux lignes au plus : « code · type » puis « salle · enseignant ». Avant,
 * chaque carte empilait code, type, deux icônes sans nom, salle et nom de
 * l'enseignant en capitales italiques sur deux ou trois lignes : une journée
 * faisait 1 200 px de haut. Le nom complet du cours et de l'enseignant reste
 * au survol (`title`).
 *
 * Les actions (modifier, retirer du planning, supprimer une séance ajoutée à
 * la main) sont de vrais boutons nommés, visibles au survol ou au focus, et
 * toujours visibles au toucher. Double-clic sur la carte = modifier.
 */
import type { CSSProperties, DragEvent as ReactDragEvent } from "react";

import type { Placement } from "../types";
import type { AppRow, RoomCatalogEntry } from "../types/app";
import { couleursMatiere } from "../utils/couleursMatiere";
import { nomComplet, nomCourt } from "../utils/nomEnseignant";

/** « H.103 (Anglais) » -> « H.103 » : la précision reste dans l'infobulle. */
export function salleCourte(libelle: string): string {
  return libelle.replace(/\s*\([^)]*\)\s*$/, "");
}

function Icone({ nom }: { nom: "modifier" | "retirer" | "supprimer" }) {
  const d = {
    modifier: "M3 13h2.5L13 5.5 10.5 3 3 10.5V13Zm6.5-9L12 6.5",
    retirer: "M6 4 3 7l3 3M3 7h6.5a3.5 3.5 0 0 1 0 7H7",
    supprimer: "M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 8.5h5.6l.7-8.5",
  }[nom];
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

interface PromoCarteProps {
  row: AppRow;
  /** Placement vivant (salle à jour, verrou) — absent en lecture seule. */
  source: Placement | undefined;
  teacherLabels: Record<string, string>;
  salles: RoomCatalogEntry[];
  /** Salle telle qu'affichée (déjà réconciliée avec `source`). */
  salleAffichee: string;
  highlighted: boolean;
  draggable: boolean;
  dragging: boolean;
  swapTarget: boolean;
  actions: boolean;
  salleModifiable: boolean;
  salleEnEdition: boolean;
  salleEnCours: boolean;
  salleSelectionnee: string;
  onDragStart?: (e: ReactDragEvent) => void;
  onDragEnd?: () => void;
  echangeHandlers: Record<string, unknown>;
  onModifier: () => void;
  onRetirer: () => void;
  onSupprimer: () => void;
  onOuvrirSalle: () => void;
  onChoisirSalle: (roomId: string) => void;
  onFermerSalle: () => void;
}

export function PromoCarte({
  row: r,
  source,
  teacherLabels,
  salles,
  salleAffichee,
  highlighted,
  draggable,
  dragging,
  swapTarget,
  actions,
  salleModifiable,
  salleEnEdition,
  salleEnCours,
  salleSelectionnee,
  onDragStart,
  onDragEnd,
  echangeHandlers,
  onModifier,
  onRetirer,
  onSupprimer,
  onOuvrirSalle,
  onChoisirSalle,
  onFermerSalle,
}: PromoCarteProps) {
  const dur = r.dur || 1;
  const durLabel = dur > 1 ? `${(dur * 1.5).toFixed(1).replace(".0", "").replace(".", ",")} h` : "";
  const nomsComplets = r.te.map((tc) => nomComplet(teacherLabels[tc] ?? tc));
  const nomsCourts = r.te.map((tc) => nomCourt(teacherLabels[tc] ?? tc));
  const verrouillee = source?.locked ?? r.locked;
  const infobulle = [
    `${r.c}${r.n ? ` — ${r.n}` : ""}`,
    [r.t, r.ev ? "évaluation" : "", durLabel].filter(Boolean).join(" · "),
    nomsComplets.join(", "),
    salleAffichee ? `Salle ${salleAffichee}` : "Salle à définir",
    verrouillee ? "Verrouillée : ne peut pas être déplacée" : draggable ? "Glisser pour déplacer · double-clic pour modifier" : "",
  ]
    .filter(Boolean)
    .join("\n");

  const classes = [
    "promo-chip",
    `type-${r.t.toLowerCase()}`,
    r.ev ? "eval" : "",
    highlighted ? "chip-highlight" : "",
    draggable ? "promo-chip--draggable" : "",
    verrouillee ? "promo-chip--verrouillee" : "",
    actions ? "promo-chip--actions" : "",
    dragging ? "dragging" : "",
    swapTarget ? "swap-target" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

  return (
    <div
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDoubleClick={
        actions
          ? (e) => {
              e.stopPropagation();
              onModifier();
            }
          : undefined
      }
      {...echangeHandlers}
      style={couleursMatiere(r.c) as CSSProperties}
      className={classes}
    >
      <div className="promo-chip__l1" title={infobulle}>
        <span className="code">{r.c}</span>
        <span className="ty">
          {r.t}
          {r.ev ? " · éval" : ""}
          {durLabel ? ` · ${durLabel}` : ""}
        </span>
        {swapTarget && <span className="promo-chip__echange">échanger</span>}
      </div>
      <div className="promo-chip__l2">
        {salleEnEdition ? (
          <select
            className="rm promo-chip-salle"
            aria-label={`Salle de ${r.c}`}
            autoFocus
            disabled={salleEnCours}
            defaultValue={salleSelectionnee}
            onClick={stop}
            onMouseDown={stop}
            onKeyDown={(e) => {
              if (e.key === "Escape") onFermerSalle();
              e.stopPropagation();
            }}
            onChange={(e) => onChoisirSalle(e.target.value)}
            onBlur={onFermerSalle}
          >
            <option value="">— choisir une salle —</option>
            <option value="__new__">+ Créer une salle…</option>
            {salles.map((s2) => (
              <option key={s2.id} value={s2.id}>
                {s2.label} ({s2.capacity} pl.)
              </option>
            ))}
          </select>
        ) : salleModifiable ? (
          <button
            type="button"
            className={`rm promo-chip-salle-btn${salleAffichee ? "" : " rm--absente"}`}
            title={`${salleAffichee ? `Salle ${salleAffichee}` : "Aucune salle"} — cliquer pour changer`}
            onClick={(e) => {
              e.stopPropagation();
              onOuvrirSalle();
            }}
            onMouseDown={stop}
          >
            {salleAffichee ? salleCourte(salleAffichee) : "sans salle"}
          </button>
        ) : (
          <span className={`rm${salleAffichee ? "" : " rm--absente"}`} title={salleAffichee || undefined}>
            {salleAffichee ? salleCourte(salleAffichee) : "sans salle"}
          </span>
        )}
        {nomsCourts.length > 0 && (
          <span className="te" title={nomsComplets.join(", ")}>
            {nomsCourts.join(", ")}
          </span>
        )}
      </div>
      {actions && (
        <span className="promo-chip__actions">
          <button
            type="button"
            className="promo-chip__action"
            title="Modifier cette séance"
            aria-label={`Modifier ${r.c}`}
            onClick={(e) => {
              e.stopPropagation();
              onModifier();
            }}
            onMouseDown={stop}
          >
            <Icone nom="modifier" />
          </button>
          <button
            type="button"
            className="promo-chip__action"
            title="Retirer du planning (vers « À placer »)"
            aria-label={`Retirer ${r.c} du planning`}
            onClick={(e) => {
              e.stopPropagation();
              onRetirer();
            }}
            onMouseDown={stop}
          >
            <Icone nom="retirer" />
          </button>
          {r.custom && (
            <button
              type="button"
              className="promo-chip__action promo-chip__action--danger"
              title="Supprimer cette séance"
              aria-label={`Supprimer ${r.c}`}
              onClick={(e) => {
                e.stopPropagation();
                onSupprimer();
              }}
              onMouseDown={stop}
            >
              <Icone nom="supprimer" />
            </button>
          )}
        </span>
      )}
    </div>
  );
}
