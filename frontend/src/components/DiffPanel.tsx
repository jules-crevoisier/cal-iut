import type { DiffEntry, DiffResponse, FeedbackAnalysis } from "../types";
import { dayName, slotLabel } from "../utils/slots";

interface DiffPanelProps {
  diff: DiffResponse | null;
  analysis: FeedbackAnalysis | null;
  onApplyFeedback: () => void;
  onExportCsv: () => void;
  onExportJson: () => void;
  loading: boolean;
}

export function DiffPanel({
  diff,
  analysis,
  onApplyFeedback,
  onExportCsv,
  onExportJson,
  loading,
}: DiffPanelProps) {
  return (
    <div className="diff-panel">
      <h2>Diff & export</h2>

      <div className="diff-actions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={onExportCsv} disabled={loading}>
          Export CSV
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onExportJson} disabled={loading}>
          Export JSON
        </button>
        <button type="button" className="btn btn--accent btn--sm" onClick={onApplyFeedback} disabled={loading}>
          Appliquer feedback
        </button>
      </div>

      {diff && (
        <div className="diff-summary">
          <span className="metric-inline">
            <strong>{diff.changed_count}</strong> / {diff.total} séances modifiées
          </span>
        </div>
      )}

      {analysis && analysis.total_corrections > 0 && (
        <div className="feedback-block">
          <h3>Apprentissage ({analysis.total_corrections} corrections)</h3>
          {analysis.patterns.map((p) => (
            <p key={p} className="pattern">{p}</p>
          ))}
          {Object.keys(analysis.suggestions).length > 0 && (
            <ul className="suggestions">
              {Object.entries(analysis.suggestions).map(([k, v]) => (
                <li key={k}>{k}: +{v}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {diff && diff.entries.length > 0 && (
        <ul className="diff-list">
          {diff.entries.slice(0, 20).map((e) => (
            <DiffItem key={e.session_id} entry={e} />
          ))}
          {diff.entries.length > 20 && (
            <li className="muted">… et {diff.entries.length - 20} autres</li>
          )}
        </ul>
      )}
    </div>
  );
}

function DiffItem({ entry }: { entry: DiffEntry }) {
  return (
    <li className={`diff-item ${entry.locked ? "locked" : ""}`}>
      <strong>{entry.course_code}</strong>
      <span>
        S{entry.solver_week + 1} {dayName(entry.solver_day)} {slotLabel(entry.solver_slot)}
        {" → "}
        S{entry.current_week + 1} {dayName(entry.current_day)} {slotLabel(entry.current_slot)}
      </span>
      {entry.locked && <span className="badge lock">🔒</span>}
    </li>
  );
}
