import type { Quality } from "../types";

interface QualityPanelProps {
  quality: Quality | null;
  correctionsCount: number;
}

/**
 * Détails de qualité qui n'ont PAS d'équivalent dans le nouveau `PageHeader`
 * (§54) — statut solveur, trous et journées isolées y sont déjà affichés,
 * les répéter ici avec des valeurs parfois différentes (deux sources de
 * données distinctes : `appPayload.quality` pour l'en-tête, `quality`
 * local — celui du dernier `/solve` de CETTE session — ici) était trompeur.
 * Retour utilisateur 11/08/2026 : "je veux que celle du html enlève tout le
 * superflu" — cf. docs/DATA.md §55.
 */
export function QualityPanel({ quality, correctionsCount }: QualityPanelProps) {
  if (!quality) return null;

  const hasContent = quality.eval_days_with_multiple > 0 || correctionsCount > 0 || quality.unbalanced_groups.length > 0;
  if (!hasContent) return null;

  return (
    <aside className="quality-panel">
      <h2>Autres indicateurs</h2>
      <div className="metrics">
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
