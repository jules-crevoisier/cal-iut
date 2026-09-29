/**
 * Ce qui a changé depuis la dernière génération, et les exports (Vue
 * Semaine, colonne de droite). Refonte du 29/09/2026 : l'ancien « Diff &
 * export » parlait le jargon de l'outil (« Appliquer feedback »,
 * `afternoon_preference: +50`, « S1 » = index interne de semaine).
 * Mêmes fonctions, dites en clair ; chaque écart mène à sa semaine.
 */
import type { DiffEntry, DiffResponse, FeedbackAnalysis } from "../types";
import type { WeekRow } from "../types/app";
import { slotLabel } from "../utils/slots";
import "./DiffPanel.css";

interface DiffPanelProps {
  diff: DiffResponse | null;
  analysis: FeedbackAnalysis | null;
  onApplyFeedback: () => void;
  onExportCsv: () => void;
  onExportJson: () => void;
  loading: boolean;
  /** Libellés de la grille (« Semaine 6 ») — sans eux, repli sur l'index. */
  weekRows?: WeekRow[];
  /** Aller à la semaine d'un écart (index d'AFFICHAGE dans `weekRows`). */
  onAllerSemaine?: (displayIndex: number) => void;
}

const JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven."];

/** Réglages du solveur proposés par l'analyse des corrections. */
const REGLAGES: Record<string, string> = {
  afternoon_preference: "préférence pour l'après-midi",
  teacher_preference: "créneaux préférés des enseignants",
  gap_penalty: "éviter les trous dans les journées",
};

export function DiffPanel({
  diff,
  analysis,
  onApplyFeedback,
  onExportCsv,
  onExportJson,
  loading,
  weekRows = [],
  onAllerSemaine,
}: DiffPanelProps) {
  const nomSemaine = (w: number) => {
    const label = weekRows.find((r) => r.weekIndex === w)?.label;
    return label ? label.replace(/\s*\(.*\)\s*$/, "") : `semaine ${w + 1}`;
  };
  const moment = (d: number, s: number) => `${JOURS_COURTS[d] ?? "?"} ${slotLabel(s).split("–")[0]}`;
  const trajet = (e: DiffEntry) =>
    e.solver_week === e.current_week
      ? { texte: `${moment(e.solver_day, e.solver_slot)} → ${moment(e.current_day, e.current_slot)}`, semaine: nomSemaine(e.current_week) }
      : {
          texte: `${nomSemaine(e.solver_week)} ${moment(e.solver_day, e.solver_slot)} → ${nomSemaine(e.current_week)} ${moment(e.current_day, e.current_slot)}`,
          semaine: "",
        };

  return (
    <section className="panel diff-panel" aria-labelledby="diff-panel-titre">
      <h3 id="diff-panel-titre">Modifications et export</h3>

      {diff && (
        <p className="diff-summary">
          <strong>{diff.changed_count}</strong> séance{diff.changed_count > 1 ? "s" : ""} déplacée
          {diff.changed_count > 1 ? "s" : ""} à la main depuis la génération, sur {diff.total}.
        </p>
      )}

      {diff && diff.entries.length > 0 && (
        <ul className="diff-list">
          {diff.entries.slice(0, 20).map((e) => (
            <DiffItem
              key={e.session_id}
              entry={e}
              trajet={trajet(e)}
              onAller={
                onAllerSemaine
                  ? () => {
                      const idx = weekRows.findIndex((r) => r.weekIndex === e.current_week);
                      if (idx >= 0) onAllerSemaine(idx);
                    }
                  : undefined
              }
            />
          ))}
          {diff.entries.length > 20 && <li className="diff-plus">… et {diff.entries.length - 20} autres</li>}
        </ul>
      )}

      <div className="diff-actions">
        <button type="button" className="btn btn--sm" onClick={onExportCsv} disabled={loading}>
          Exporter en CSV
        </button>
        <button type="button" className="btn btn--sm" onClick={onExportJson} disabled={loading}>
          Exporter en JSON
        </button>
      </div>

      {analysis && analysis.total_corrections > 0 && (
        <details className="feedback-block">
          <summary>Tenir compte de vos corrections ({analysis.total_corrections})</summary>
          {analysis.patterns.map((p) => (
            <p key={p} className="pattern">
              {p}
            </p>
          ))}
          {Object.keys(analysis.suggestions).length > 0 && (
            <ul className="suggestions">
              {Object.entries(analysis.suggestions).map(([k, v]) => (
                <li key={k}>
                  {REGLAGES[k] ?? k} : +{v}
                </li>
              ))}
            </ul>
          )}
          <p className="pattern">
            Ajuste les réglages de la génération automatique : la prochaine génération (en ligne de commande)
            reproduira ces tendances.
          </p>
          <button type="button" className="btn btn--sm" onClick={onApplyFeedback} disabled={loading}>
            Ajuster la génération
          </button>
        </details>
      )}
    </section>
  );
}

function DiffItem({
  entry,
  trajet,
  onAller,
}: {
  entry: DiffEntry;
  trajet: { texte: string; semaine: string };
  onAller?: () => void;
}) {
  const contenu = (
    <>
      <span className="diff-item-code">
        {entry.course_code}
        {trajet.semaine && <span className="diff-item-etat">{trajet.semaine}</span>}
        {entry.locked && <span className="diff-item-etat">verrouillée</span>}
      </span>
      <span className="diff-item-trajet">{trajet.texte}</span>
    </>
  );
  return (
    <li className={`diff-item${entry.locked ? " locked" : ""}`}>
      {onAller ? (
        <button type="button" className="diff-item-btn" onClick={onAller} title="Afficher cette semaine">
          {contenu}
        </button>
      ) : (
        contenu
      )}
    </li>
  );
}
