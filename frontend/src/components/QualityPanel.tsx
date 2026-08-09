import type { Quality } from "../types";

interface QualityPanelProps {
  quality: Quality | null;
  status: string;
  correctionsCount: number;
}

export function QualityPanel({ quality, status, correctionsCount }: QualityPanelProps) {
  if (!quality) {
    return (
      <aside className="quality-panel empty">
        <h2>Qualité</h2>
        <p className="muted">Générez un planning pour voir les indicateurs.</p>
      </aside>
    );
  }

  const gapLevel = quality.total_gaps === 0 ? "good" : quality.total_gaps < 50 ? "warn" : "bad";

  return (
    <aside className="quality-panel">
      <h2>Qualité du planning</h2>
      <p className="status-line">
        Statut solveur : <strong>{status}</strong>
      </p>

      <div className="metrics">
        <Metric
          label="Trous (priorité #1)"
          value={quality.total_gaps}
          level={gapLevel}
          hint="Créneaux vides entre deux cours le même jour"
        />
        <Metric
          label="Journées isolées"
          value={quality.isolated_days}
          level={quality.isolated_days === 0 ? "good" : "warn"}
        />
        <Metric
          label="Évals empilées"
          value={quality.eval_days_with_multiple}
          level={quality.eval_days_with_multiple === 0 ? "good" : "warn"}
        />
        <Metric label="Corrections manuelles" value={correctionsCount} level="neutral" />
      </div>

      {quality.unbalanced_groups.length > 0 && (
        <div className="alert warn">
          <strong>Déséquilibre</strong>
          <ul>
            {quality.unbalanced_groups.slice(0, 5).map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

function Metric({
  label,
  value,
  level,
  hint,
}: {
  label: string;
  value: number;
  level: "good" | "warn" | "bad" | "neutral";
  hint?: string;
}) {
  return (
    <div className={`metric metric--${level}`} title={hint}>
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}
